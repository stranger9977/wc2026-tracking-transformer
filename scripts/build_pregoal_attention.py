"""Pre-goal attention EDA: aggregate the frame-VAEP model's attention
in the K seconds immediately before every goal in the corpus.

For each goal:
  1. Pull the K-second window of frames preceding it (default 10s @ 5Hz = 50 frames).
  2. Run the frame-VAEP transformer, recording per-frame ball-token attention
     over the 22 player slots.
  3. Track which player_id sits at each slot per frame.
  4. Accumulate:
        - per-player "attention received pre-goal"
        - per-pair "co-attention pre-goal" (outer product of the ball-attention
          vector summed across frames within the window)
        - per-team aggregates
        - per-goal timeline of (p_score, p_concede) across the window

Outputs land at:
    research/data/pregoal_attention/players.parquet   — per-player aggregates
    research/data/pregoal_attention/pairs.parquet     — per-pair aggregates
    research/data/pregoal_attention/timelines.parquet — per-(goal, frame) p_score / p_concede
    research/data/pregoal_attention/goals.parquet     — one row per goal (scorer, team, time)

These then feed the Pre-Goal Attention site section.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.pff import (load_pff_match,
                                                            list_pff_matches)
from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule
from wc2026_tracking_transformer.tasks.frame_vaep_labels import goals_from_pff_events

PFF_STRIDE = 6
FRAME_RATE_HZ = 5.0
WINDOW_S = 10.0
N_PRE_FRAMES = int(WINDOW_S * FRAME_RATE_HZ)  # 50 frames
PFF_ROOT_DEFAULT = "/Users/nick/Desktop/drive-download-20260518T234612Z-3-001"
DATA_DIR = REPO / "research" / "data"
OUT_DIR = DATA_DIR / "pregoal_attention"


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _events_path(match_id: str) -> Path:
    return Path(os.environ.get("PFF_ROOT", PFF_ROOT_DEFAULT)) / "Event Data" / f"{match_id}.json"


def _frame_player_ids(frame, n_slots: int = 22) -> list[int | None]:
    """Pull the player_id at each slot of a TrackingFrame.

    The PFF loader's TrackingFrame stores `players` as an array but we also
    need the parallel player_id list. The loader pushes that through via
    a custom attribute — try common attribute names and fall back to None.
    """
    for attr in ("player_ids", "_player_ids", "player_ids_per_slot"):
        v = getattr(frame, attr, None)
        if v is not None:
            return list(v)[:n_slots] + [None] * max(0, n_slots - len(v))
    # Fallback: no per-slot player_id, can't map attention to players
    return [None] * n_slots


def collect_pregoal(match_id: str, lit: FrameVaepLitModule, device: torch.device,
                    *, k_pre_frames: int = N_PRE_FRAMES,
                    period1_length_ms: int = 47 * 60 * 1000):
    """Run the model on pre-goal windows for one match.

    Returns:
        rows_players: list of dicts (per (goal, slot)) with attention sum
        rows_pairs: list of dicts (per (goal, slot_i, slot_j)) with co-attention sum
        rows_timeline: list of dicts (per (goal, frame_offset))
        rows_goals: list of dicts (one per goal)
    """
    # Load match events + goals
    events = json.loads(_events_path(match_id).read_text())
    goals = goals_from_pff_events(events)
    if not goals:
        return [], [], [], []

    # Load frames once
    frames = list(load_pff_match(match_id, sampling_stride=PFF_STRIDE))
    if not frames:
        return [], [], [], []

    # Absolute-time index of frames for fast lookup
    abs_times_ms = np.asarray([
        f.timestamp_ms if f.period == 1 else period1_length_ms + f.timestamp_ms
        for f in frames
    ])
    # Sort to be safe (loader should already do this)
    order = np.argsort(abs_times_ms)
    frames = [frames[i] for i in order]
    abs_times_ms = abs_times_ms[order]

    rows_players: list[dict] = []
    rows_pairs: list[dict] = []
    rows_timeline: list[dict] = []
    rows_goals: list[dict] = []

    for goal_idx, g in enumerate(goals):
        # Find the frame index closest to the goal time
        end_i = int(np.searchsorted(abs_times_ms, g.abs_ms, side="left"))
        start_i = max(0, end_i - k_pre_frames)
        window = frames[start_i:end_i]
        if not window:
            continue
        # Run the model on this window
        tensors = batch_frames(window)
        x = torch.from_numpy(tensors).to(device)
        with torch.no_grad():
            enc, attn = lit.encode_with_attention(x)
            ps = torch.sigmoid(lit.score_head(enc)).cpu().numpy()
            pc = torch.sigmoid(lit.concede_head(enc)).cpu().numpy()
            attn_mean = attn.mean(dim=(1, 2)).cpu().numpy()    # (n, T, T)
            attn_ball = attn_mean[:, 22, :22]                  # (n, 22) ball→player
            # renormalize across players
            attn_ball = attn_ball / np.maximum(attn_ball.sum(axis=1, keepdims=True), 1e-9)

        # Accumulate per-player attention
        slot_attn_sum = attn_ball.sum(axis=0)  # (22,)
        # Co-attention (off-diagonal): sum over frames of outer-product, symmetrized
        co = np.zeros((22, 22), dtype=np.float64)
        for t in range(attn_ball.shape[0]):
            a = attn_ball[t]
            co += np.outer(a, a)
        # symmetrize + zero diag
        co = (co + co.T) / 2.0
        np.fill_diagonal(co, 0.0)

        # Map slots → player_ids using the LAST frame in the window
        last_frame = window[-1]
        slot_to_pid = _frame_player_ids(last_frame, 22)

        # Per-goal info
        rows_goals.append({
            "match_id": match_id,
            "goal_idx": goal_idx,
            "period": g.period,
            "abs_ms": g.abs_ms,
            "scoring_team_id": g.scoring_team_id,
            "n_pre_frames": len(window),
        })

        # Per-player
        for slot in range(22):
            pid = slot_to_pid[slot]
            if pid is None:
                continue
            rows_players.append({
                "match_id": match_id,
                "goal_idx": goal_idx,
                "scoring_team_id": g.scoring_team_id,
                "slot": slot,
                "player_id": int(pid),
                "attn_sum": float(slot_attn_sum[slot]),
            })

        # Per-pair (i < j)
        for i in range(22):
            pi = slot_to_pid[i]
            if pi is None:
                continue
            for j in range(i + 1, 22):
                pj = slot_to_pid[j]
                if pj is None:
                    continue
                if co[i, j] <= 0:
                    continue
                rows_pairs.append({
                    "match_id": match_id,
                    "goal_idx": goal_idx,
                    "scoring_team_id": g.scoring_team_id,
                    "player_i": int(min(pi, pj)),
                    "player_j": int(max(pi, pj)),
                    "co_attn": float(co[i, j]),
                })

        # Timeline rows
        for t in range(len(window)):
            rows_timeline.append({
                "match_id": match_id,
                "goal_idx": goal_idx,
                "frame_offset": t - len(window),  # negative: -50 ... -1
                "p_score": float(ps[t]),
                "p_concede": float(pc[t]),
            })

    return rows_players, rows_pairs, rows_timeline, rows_goals


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ckpt = REPO / "output" / "transformer_frame_vaep.ckpt"
    if not ckpt.exists():
        raise SystemExit(f"checkpoint not found: {ckpt}")
    device = _device()
    print(f"Device: {device}")
    lit = FrameVaepLitModule.load_from_checkpoint(str(ckpt), map_location=device)
    lit.eval().to(device)

    all_players, all_pairs, all_timelines, all_goals = [], [], [], []
    matches = list_pff_matches()
    print(f"Running on {len(matches)} matches…")
    for i, m in enumerate(matches):
        mid = m.name
        t0 = time.time()
        try:
            rp, rpa, rt, rg = collect_pregoal(mid, lit, device)
        except Exception as e:
            print(f"  skip {mid}: {e}")
            continue
        all_players.extend(rp); all_pairs.extend(rpa)
        all_timelines.extend(rt); all_goals.extend(rg)
        print(f"  [{i+1}/{len(matches)}] {mid}: goals={len(rg)}  "
              f"player-rows={len(rp)} pair-rows={len(rpa)}  ({time.time() - t0:.1f}s)")

    pd.DataFrame(all_players).to_parquet(OUT_DIR / "players.parquet", index=False)
    pd.DataFrame(all_pairs).to_parquet(OUT_DIR / "pairs.parquet", index=False)
    pd.DataFrame(all_timelines).to_parquet(OUT_DIR / "timelines.parquet", index=False)
    pd.DataFrame(all_goals).to_parquet(OUT_DIR / "goals.parquet", index=False)
    print(f"\nWrote 4 parquets to {OUT_DIR}")
    print(f"  players: {len(all_players)} rows")
    print(f"  pairs:   {len(all_pairs)} rows")
    print(f"  timelines: {len(all_timelines)} rows")
    print(f"  goals:   {len(all_goals)} rows")


if __name__ == "__main__":
    main()
