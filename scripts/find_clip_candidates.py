"""Scan PFF matches for near-miss and bad-chemistry candidate windows.

For each match:
  - Load tracking via the slot-stable loader (period+timestamp_ms per frame).
  - Run the frame-VAEP model to get per-frame (p_score, p_concede).
  - Load events; find non-goal shots and possession turnovers.
  - Score candidate windows:
      * near-miss: shot (non-goal) where P(score) peaks > 0.30 in the 10 s
        before the shot, then drops within 6 s after.
      * bad-chemistry: a 12 s window where the team-in-possession net
        (P_score - P_concede) flips from > +0.10 to < -0.15, with a
        challenge/clearance/turnover event in the middle.

Writes JSON of top-K candidates to stdout / a file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "research" / "scripts"))

from wc2026_tracking_transformer.data.batching import batch_frames  # noqa
from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule  # noqa
from extract_transformer_features import _load_match_frames_and_slots  # noqa

PFF_ROOT = Path("/Users/nick/Desktop/drive-download-20260518T234612Z-3-001")


def _device():
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _load_events(match_id: str) -> list[dict]:
    return json.loads((PFF_ROOT / "Event Data" / f"{match_id}.json").read_text())


def _load_meta(match_id: str) -> dict:
    raw = json.loads((PFF_ROOT / "Metadata" / f"{match_id}.json").read_text())
    if isinstance(raw, list):
        raw = raw[0]
    return raw


def _events_compact(events: list[dict]) -> list[dict]:
    out = []
    for ev in events:
        ge = ev.get("gameEvents") or {}
        pe = ev.get("possessionEvents") or {}
        period = int(ge.get("period") or 1)
        clock = float(pe.get("gameClock") or ge.get("startGameClock") or 0)
        if period == 1:
            period_rel_ms = int(clock * 1000)
        else:
            period_rel_ms = int((clock - 2700) * 1000)
        pe_type = pe.get("possessionEventType")
        is_goal = pe_type == "SH" and pe.get("shotOutcomeType") == "G"
        out.append({
            "period": period,
            "period_rel_ms": period_rel_ms,
            "type": pe_type,
            "is_goal": is_goal,
            "shot_outcome": pe.get("shotOutcomeType") if pe_type == "SH" else None,
            "actor_name": pe.get("shooterPlayerName") or pe.get("passerPlayerName")
                           or pe.get("ballCarrierPlayerName"),
        })
    return out


def scan_match(match_id: str, lit, device, stride: int = 6) -> dict:
    print(f"[{match_id}] loading frames...", flush=True)
    frames, slots = _load_match_frames_and_slots(match_id, sampling_stride=stride)
    if not frames:
        return {}
    tensors = batch_frames(frames)
    print(f"[{match_id}] {len(frames)} frames, scoring...", flush=True)
    # Batch through model
    B = 1024
    ps_all = np.zeros(len(frames), dtype=np.float32)
    pc_all = np.zeros(len(frames), dtype=np.float32)
    with torch.no_grad():
        for start in range(0, len(frames), B):
            end = min(start + B, len(frames))
            x = torch.from_numpy(tensors[start:end]).to(device)
            ps, pc = lit(x)
            ps_all[start:end] = ps.cpu().numpy()
            pc_all[start:end] = pc.cpu().numpy()

    # Frame metadata
    f_period = np.array([f.period for f in frames])
    f_ts_ms = np.array([f.timestamp_ms for f in frames])
    f_poss = [f.in_possession_team_id for f in frames]

    events = _events_compact(_load_events(match_id))
    meta = _load_meta(match_id)
    home_id = str(meta.get("homeTeam", {}).get("id", ""))
    away_id = str(meta.get("awayTeam", {}).get("id", ""))

    # NEAR-MISS: for each non-goal shot, find peak P(score) in [shot-10s, shot+1s]
    near_miss = []
    for ev in events:
        if ev["type"] != "SH" or ev["is_goal"]:
            continue
        # the outcome must not be a goal (G); we want misses / saves / blocks
        outcome = ev["shot_outcome"]
        if outcome not in ("S", "O", "B", "W", "F"):  # save/off/block/woodwork/foul-ish
            # Some outcome codes vary; just accept all non-G shots
            pass
        # find frame indices in [shot-10s, shot+2s] same period
        per = ev["period"]
        ts = ev["period_rel_ms"]
        mask = (f_period == per) & (f_ts_ms >= ts - 10000) & (f_ts_ms <= ts + 2000)
        if mask.sum() < 10:
            continue
        ps_win = ps_all[mask]
        peak = float(ps_win.max())
        # require a meaningful drop after the shot
        post_mask = (f_period == per) & (f_ts_ms >= ts + 1000) & (f_ts_ms <= ts + 6000)
        if post_mask.sum() < 5:
            continue
        post_min = float(ps_all[post_mask].min()) if post_mask.any() else 1.0
        drop = peak - post_min
        if peak < 0.20:
            continue
        if drop < 0.10:
            continue
        near_miss.append({
            "match_id": match_id,
            "period": int(per),
            "shot_ts_ms": int(ts),
            "shot_ts_s": ts / 1000.0,
            "peak_p_score": peak,
            "post_p_score_min": post_min,
            "drop": drop,
            "shot_outcome": outcome,
            "actor_name": ev["actor_name"],
        })

    # BAD-CHEMISTRY: scan all windows; team net (from possession team's POV)
    # is p_score if poss==team-in-poss-for-frame, but our p_score is the
    # in-possession team's score-probability already (frame is constructed
    # with attacking-side flag relative to possession). So net = ps - pc.
    net = ps_all - pc_all
    bad = []
    # Sliding window 12s = ~60 frames at 5Hz
    win = 60
    for per in (1, 2):
        idxs = np.where(f_period == per)[0]
        if len(idxs) < win + 1:
            continue
        # We require possession-team continuity for first half of window
        for i in range(0, len(idxs) - win, 5):  # step 1s
            ws = idxs[i]
            we = idxs[i + win]
            pre = net[ws:ws + win // 3]
            post = net[ws + 2 * win // 3:we]
            if pre.mean() < 0.05:
                continue
            if post.mean() > -0.10:
                continue
            flip = pre.mean() - post.mean()
            if flip < 0.20:
                continue
            # Possession must change within window: count distinct poss teams
            poss_seq = f_poss[ws:we]
            distinct = set(p for p in poss_seq if p)
            if len(distinct) < 2:
                continue
            bad.append({
                "match_id": match_id,
                "period": int(per),
                "start_ts_ms": int(f_ts_ms[ws]),
                "end_ts_ms": int(f_ts_ms[we]),
                "start_ts_s": f_ts_ms[ws] / 1000.0,
                "end_ts_s": f_ts_ms[we] / 1000.0,
                "pre_net_mean": float(pre.mean()),
                "post_net_mean": float(post.mean()),
                "flip": float(flip),
                "home_id": home_id,
                "away_id": away_id,
            })

    return {"near_miss": near_miss, "bad_chemistry": bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", nargs="+", required=True)
    ap.add_argument("--ckpt", default="output/transformer_frame_vaep.ckpt")
    ap.add_argument("--out", default="output/clip_candidates.json")
    args = ap.parse_args()

    device = _device()
    print(f"device: {device}", flush=True)
    lit = FrameVaepLitModule.load_from_checkpoint(args.ckpt, map_location=device)
    lit.eval().to(device)

    all_near = []
    all_bad = []
    for mid in args.matches:
        try:
            r = scan_match(mid, lit, device)
        except Exception as exc:
            print(f"[{mid}] FAIL: {exc}", flush=True)
            continue
        all_near.extend(r.get("near_miss", []))
        all_bad.extend(r.get("bad_chemistry", []))

    # Sort: best near-miss by peak; best bad-chem by flip
    all_near.sort(key=lambda x: -x["peak_p_score"])
    all_bad.sort(key=lambda x: -x["flip"])
    out = {"near_miss": all_near[:25], "bad_chemistry": all_bad[:25]}
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}: {len(all_near)} near-miss, {len(all_bad)} bad-chem", flush=True)


if __name__ == "__main__":
    main()
