"""Cross-cutting pre-event EDA on the frame-VAEP model.

For each event class of interest, take the K seconds *immediately before* the
event in every PFF match, run the frame-VAEP transformer, and accumulate:

  - per-(event_class, frame_offset) average P_score and P_concede
  - per-(event_class, slot) average ball-attention
  - sample size (n events per class)

Event classes (derived from our existing SPADL):
  - goal           : type starts with "shot" AND result_name == "success"
  - shot           : any "shot" / "shot_freekick" / "shot_penalty" (incl. misses)
  - big_chance     : pass/cross/dribble with vaep_value > 0.05 (top tail of the corpus)
  - key_pass       : pass that immediately preceded a goal (same team)
  - cross          : any cross
  - turnover       : action where the next action belongs to the opposing team
                     and the current action result was "fail" or it was a take_on
                     or pass that became a defensive recovery

Output:
  research/data/pre_event_eda/timelines.parquet  — (event_class, frame_offset)
  research/data/pre_event_eda/slot_attn.parquet  — (event_class, slot)
  research/data/pre_event_eda/counts.parquet     — (event_class, n_events, n_frames)
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.pff import (load_pff_match,
                                                            list_pff_matches)
from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule

PFF_STRIDE = 6
WINDOW_S = 10.0
N_PRE = int(WINDOW_S * 5)  # 50 frames at 5 Hz
PERIOD1_LEN_MS = 47 * 60 * 1000
DATA_DIR = REPO / "research" / "data"
OUT_DIR = DATA_DIR / "pre_event_eda"


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def label_events(spadl: pd.DataFrame) -> pd.DataFrame:
    """Add event_class columns indicating which buckets each action falls into.

    A single action can fall in multiple buckets (e.g., a goal IS also a shot).
    Returns a copy of spadl with one bool column per class.
    """
    out = spadl.copy()
    out["cls_shot"] = out.type_name.str.startswith("shot")
    out["cls_goal"] = out.cls_shot & (out.result_name == "success")
    out["cls_cross"] = out.type_name == "cross"
    out["cls_big_chance"] = (out.vaep_value > 0.05) & out.type_name.isin(
        ["pass", "cross", "dribble", "take_on"]
    )
    # key_pass: previous action was a pass/cross by same team and current = goal
    out = out.sort_values(["game_id", "period_id", "time_seconds"]).reset_index(drop=True)
    out["cls_key_pass"] = False
    prev_team = out.team_id.shift(1)
    prev_type = out.type_name.shift(1)
    next_goal = out.cls_goal.shift(-1, fill_value=False)
    same_team_next = out.team_id.shift(-1) == out.team_id
    out["cls_key_pass"] = (
        next_goal & same_team_next &
        out.type_name.isin(["pass", "cross"]) &
        (out.result_name == "success")
    )
    # turnover: action where the next action's team is different
    next_team = out.team_id.shift(-1)
    out["cls_turnover"] = (next_team.notna()) & (next_team != out.team_id) & (
        out.result_name == "fail"
    )
    return out


def collect_one_match(match_id: str, spadl_match: pd.DataFrame,
                      lit: FrameVaepLitModule, device: torch.device,
                      classes: list[str]) -> tuple[dict, dict, dict]:
    """Accumulate per-class aggregates for one match."""
    timelines = defaultdict(lambda: np.zeros((N_PRE, 2), dtype=np.float64))
    counts = defaultdict(int)
    slot_attn_sum = defaultdict(lambda: np.zeros(22, dtype=np.float64))

    try:
        frames = list(load_pff_match(match_id, sampling_stride=PFF_STRIDE))
    except Exception as e:
        return timelines, counts, slot_attn_sum
    if not frames:
        return timelines, counts, slot_attn_sum
    abs_t = np.asarray([
        f.timestamp_ms if f.period == 1 else PERIOD1_LEN_MS + f.timestamp_ms
        for f in frames
    ])

    # For each class, find rows with that class in this match
    events_per_cls: dict[str, list[float]] = {}
    for cls in classes:
        col = f"cls_{cls}"
        if col not in spadl_match.columns:
            continue
        rows = spadl_match[spadl_match[col]]
        if rows.empty:
            continue
        # absolute time in ms, similar to TrackingFrame abs_t scheme
        # SPADL time_seconds is the PFF gameClock — P1 in [0, ~2800], P2 in [2700, ~5600]
        # So abs_t for SPADL: P1 -> ts, P2 -> ts (already absolute)
        ts_ms = (rows.time_seconds * 1000).astype(np.int64).to_numpy()
        # For P2 in SPADL time_seconds the value is gameClock (>=2700); we treat
        # as absolute already so no period offset needed.
        events_per_cls[cls] = ts_ms.tolist()

    if not events_per_cls:
        return timelines, counts, slot_attn_sum

    # Build all unique pre-event windows we need to score
    # To avoid re-running overlapping windows, we instead just collect every
    # (frame_idx, dt_idx) write-back and then run model once on the unique set.
    needed_frames: set[int] = set()
    write_back: list[tuple[str, list[int]]] = []
    for cls, ts_list in events_per_cls.items():
        for t_ms in ts_list:
            end_i = int(np.searchsorted(abs_t, t_ms, side="left"))
            start_i = max(0, end_i - N_PRE)
            window = list(range(start_i, end_i))
            if not window:
                continue
            for fi in window:
                needed_frames.add(fi)
            write_back.append((cls, window))

    if not needed_frames:
        return timelines, counts, slot_attn_sum

    sorted_idx = sorted(needed_frames)
    idx_to_pos = {fi: pos for pos, fi in enumerate(sorted_idx)}
    sel_frames = [frames[fi] for fi in sorted_idx]
    tensors = batch_frames(sel_frames)
    x = torch.from_numpy(tensors).to(device)
    # Batch inference in chunks to bound memory
    chunk = 1024
    ps_all: list[np.ndarray] = []
    pc_all: list[np.ndarray] = []
    attn_ball_all: list[np.ndarray] = []
    with torch.no_grad():
        for s in range(0, x.shape[0], chunk):
            xb = x[s:s + chunk]
            enc, attn = lit.encode_with_attention(xb)
            ps = torch.sigmoid(lit.score_head(enc)).cpu().numpy()
            pc = torch.sigmoid(lit.concede_head(enc)).cpu().numpy()
            attn_mean = attn.mean(dim=(1, 2)).cpu().numpy()
            ab = attn_mean[:, 22, :22]
            ab = ab / np.maximum(ab.sum(axis=1, keepdims=True), 1e-9)
            ps_all.append(ps); pc_all.append(pc); attn_ball_all.append(ab)
    ps_arr = np.concatenate(ps_all)
    pc_arr = np.concatenate(pc_all)
    attn_arr = np.concatenate(attn_ball_all)

    # Aggregate into per-class timeline and slot_attn
    for cls, window in write_back:
        counts[cls] += 1
        n = len(window)
        # offsets: window[0] is the earliest, at offset -n; window[-1] at offset -1
        for j, fi in enumerate(window):
            offset = j - n            # negative
            timeline_idx = N_PRE + offset  # maps -N_PRE..-1 to 0..N_PRE-1
            if 0 <= timeline_idx < N_PRE:
                pos = idx_to_pos[fi]
                timelines[cls][timeline_idx, 0] += ps_arr[pos]
                timelines[cls][timeline_idx, 1] += pc_arr[pos]
                slot_attn_sum[cls] += attn_arr[pos]

    return timelines, counts, slot_attn_sum


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ckpt = REPO / "output" / "transformer_frame_vaep.ckpt"
    if not ckpt.exists():
        raise SystemExit(f"frame-vaep checkpoint not found at {ckpt}")
    device = _device()
    print(f"Device: {device}")
    lit = FrameVaepLitModule.load_from_checkpoint(str(ckpt), map_location=device)
    lit.eval().to(device)

    spadl = pd.read_parquet(DATA_DIR / "spadl_vaep.parquet")
    print(f"Loaded {len(spadl)} SPADL rows")
    spadl = label_events(spadl)
    classes = ["goal", "shot", "cross", "big_chance", "key_pass", "turnover"]
    for c in classes:
        n = int(spadl[f"cls_{c}"].sum())
        print(f"  {c}: {n} events")

    matches = list_pff_matches()
    # Only run on matches we have SPADL for AND tracking
    all_timelines = defaultdict(lambda: np.zeros((N_PRE, 2), dtype=np.float64))
    all_counts = defaultdict(int)
    all_slot_attn = defaultdict(lambda: np.zeros(22, dtype=np.float64))
    for i, m in enumerate(matches):
        mid = m.name
        # game_id in SPADL is int
        try:
            game_id = int(mid)
        except ValueError:
            continue
        sm = spadl[spadl.game_id == game_id]
        if sm.empty:
            continue
        t0 = time.time()
        tl, c, sa = collect_one_match(mid, sm, lit, device, classes)
        for k, v in tl.items():
            all_timelines[k] += v
        for k, v in c.items():
            all_counts[k] += v
        for k, v in sa.items():
            all_slot_attn[k] += v
        print(f"  [{i+1}/{len(matches)}] {mid}: "
              + " ".join(f"{k}={c.get(k, 0)}" for k in classes)
              + f"  ({time.time() - t0:.1f}s)")

    # Build outputs
    timeline_rows = []
    for cls, arr in all_timelines.items():
        n = all_counts.get(cls, 1) or 1
        for j in range(N_PRE):
            timeline_rows.append({
                "event_class": cls,
                "frame_offset": j - N_PRE,  # -50 .. -1
                "seconds_before": (j - N_PRE) / 5.0,
                "p_score_avg": float(arr[j, 0] / n),
                "p_concede_avg": float(arr[j, 1] / n),
            })
    pd.DataFrame(timeline_rows).to_parquet(OUT_DIR / "timelines.parquet", index=False)

    slot_rows = []
    for cls, arr in all_slot_attn.items():
        n = all_counts.get(cls, 1) or 1
        norm = arr / n
        # Frame count for that class
        n_frames = n * N_PRE
        # We summed across frames inside collect_one_match for *each event*'s window
        # → divide by n_events*N_PRE to get average attention per frame per slot.
        # Actually `slot_attn_sum` adds per-frame attention vector for each frame
        # in each event's window; so total contributions = n_events * N_PRE.
        per_frame_norm = arr / max(n_frames, 1)
        for slot in range(22):
            slot_rows.append({
                "event_class": cls,
                "slot": slot,
                "avg_attention_per_frame": float(per_frame_norm[slot]),
            })
    pd.DataFrame(slot_rows).to_parquet(OUT_DIR / "slot_attn.parquet", index=False)

    count_rows = [{"event_class": k, "n_events": int(v)} for k, v in all_counts.items()]
    pd.DataFrame(count_rows).to_parquet(OUT_DIR / "counts.parquet", index=False)
    print(f"\nWrote 3 parquets to {OUT_DIR}")
    print(f"  events per class: {dict(all_counts)}")


if __name__ == "__main__":
    main()
