"""Per-match player-pair attention chemistry with ball-distance baseline.

Mirrors ``extract_attention_chemistry_frame_vaep.py`` but additionally
accumulates a per-(distance-bin, pair) attention sum and a per-bin global
sum so we can compute a *baseline* attention level for any (pair, mean-
distance-to-ball) bucket and subtract it from the observed pair-attention.

The motivation: the raw per-pair sum gives high marks to anyone who
happens to be near the ball a lot (GKs during defensive sequences,
centre-backs in build-up). The ball-distance baseline correction asks
"how much MORE than a typical pair at this distance was the model
attending to these two players?" and is the real chemistry signal.

Methodology:
  - For each accepted frame, compute every player's Euclidean distance
    to the ball (meters).
  - For each unordered pair (i, j) of player slots: mean_dist =
    0.5 * (d(i) + d(j)). Bin into 10-meter buckets up to 50m+.
  - Sum that frame's pair-attention into:
      * pair_attention_by_bin[(pid_a, pid_b)][bin]      (per-pair-per-bin)
      * frames_by_bin[(pid_a, pid_b)][bin]              (so we know the
                                                         pair's weighted
                                                         mean bin)
      * global_attention_by_bin[bin]                    (sum of every
                                                         pair-attention
                                                         contribution in
                                                         that bin)
      * global_pairs_by_bin[bin]                        (count of (frame,
                                                         pair) entries)
  - After all matches are processed, baseline_per_bin[b] =
    global_attention_by_bin[b] / global_pairs_by_bin[b].
  - Each pair's expected attention is the dot product of its per-bin
    frame counts with the global baseline. The corrected ("lift over
    distance baseline") value is observed - expected.

Output schema (``research/data/attention_chemistry_baselined.parquet``):
  game_id, team_id, player_p, name_p, player_q, name_q, same_team,
  pair_attention                   (= sum of symmetrized attention, same
                                     as the old parquet)
  pair_attention_expected          (sum over bins of frames_in_bin *
                                     global_baseline_per_bin)
  pair_attention_baselined         (pair_attention - expected; the
                                     "real" chemistry signal)

Usage:
    PYTHONPATH=research/src uv run python \\
      research/scripts/extract_attention_with_baseline.py
    # ...then:
    PYTHONPATH=research/src uv run python \\
      research/scripts/extract_attention_with_baseline.py --combine
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "research" / "src"))

# Reuse the streaming logic from the original extractor.
from extract_attention_chemistry import (  # noqa: E402
    _stream_match_combined,
    NUM_PLAYER_SLOTS,
    BATCH_SIZE,
)
from wc2026_tracking_transformer.data.schema import (  # noqa: E402
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
)
from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule  # noqa: E402
from chemistry.loaders.pff_paths import event_files  # noqa: E402

OUT_PATH = REPO_ROOT / "research" / "data" / "attention_chemistry_baselined.parquet"
SHARD_DIR = REPO_ROOT / "research" / "data" / "attention_chemistry_baselined_shards"
CKPT_PATH = REPO_ROOT / "output" / "transformer_frame_vaep.ckpt"
LINEUPS_PATH = REPO_ROOT / "research" / "data" / "minutes" / "lineups.parquet"

# 10 bins: 0-5, 5-10, 10-15, ..., 40-45, 45+.
# Edges (in meters) — last bucket is open-ended.
BIN_EDGES = np.array([0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0])
N_BINS = len(BIN_EDGES)  # bin idx i covers [BIN_EDGES[i], BIN_EDGES[i+1]] with the last being open
HALF_LEN = PITCH_LENGTH_M / 2.0
HALF_WID = PITCH_WIDTH_M / 2.0


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def process_match(match_id: str, lit: FrameVaepLitModule, device: torch.device):
    """Single-match accumulators.

    Returns:
      pair_sums:        {(pid_a, pid_b): float}  total symmetrized pair attention
      pair_bins:        {(pid_a, pid_b): np.ndarray (N_BINS,)} attention summed within bin
      pair_bin_frames:  {(pid_a, pid_b): np.ndarray (N_BINS,)} frame count within bin
      global_bin_attn:  np.ndarray (N_BINS,) summed pair-attention across all pairs/frames
      global_bin_n:     np.ndarray (N_BINS,) summed pair-frame counts
      player_info:      kloppy player metadata
    """
    out_tensors, out_ids, player_info, _team_names = _stream_match_combined(match_id)
    if not out_tensors:
        return {}, {}, {}, np.zeros(N_BINS), np.zeros(N_BINS), {}

    pair_sums: dict[tuple[int, int], float] = defaultdict(float)
    pair_bins: dict[tuple[int, int], np.ndarray] = defaultdict(
        lambda: np.zeros(N_BINS, dtype=np.float64)
    )
    pair_bin_frames: dict[tuple[int, int], np.ndarray] = defaultdict(
        lambda: np.zeros(N_BINS, dtype=np.int64)
    )
    global_bin_attn = np.zeros(N_BINS, dtype=np.float64)
    global_bin_n = np.zeros(N_BINS, dtype=np.int64)

    n_frames = len(out_tensors)
    iu, ju = np.triu_indices(NUM_PLAYER_SLOTS, k=1)

    for start in range(0, n_frames, BATCH_SIZE):
        end = min(start + BATCH_SIZE, n_frames)
        tensors_np = np.stack(out_tensors[start:end], axis=0)  # (B, 23, 7)
        ids_arr = np.stack(out_ids[start:end], axis=0)         # (B, 22)
        x = torch.from_numpy(tensors_np).to(device)
        with torch.no_grad():
            _, attn = lit.backbone.encode_with_attention(x)
        # Average across layers + heads then symmetrize and drop ball.
        pair_attn = attn.mean(dim=(1, 2)).cpu().numpy()
        pair_attn = pair_attn + np.transpose(pair_attn, (0, 2, 1))
        pair_attn = pair_attn[:, :NUM_PLAYER_SLOTS, :NUM_PLAYER_SLOTS]  # (B, 22, 22)

        # Recover ball + player positions in meters from normalized tensor coords.
        # tensor[..., 0] is x/HALF_LEN, tensor[..., 1] is y/HALF_WID.
        players_xy = tensors_np[:, :NUM_PLAYER_SLOTS, :2].copy()   # (B, 22, 2)
        players_xy[..., 0] *= HALF_LEN
        players_xy[..., 1] *= HALF_WID
        ball_xy = tensors_np[:, NUM_PLAYER_SLOTS, :2].copy()       # (B, 2)
        ball_xy[..., 0] *= HALF_LEN
        ball_xy[..., 1] *= HALF_WID

        # Euclidean distance per (frame, player).
        diff = players_xy - ball_xy[:, None, :]                    # (B, 22, 2)
        dist = np.sqrt(np.sum(diff * diff, axis=2))                # (B, 22)

        # Mean pair-distance to ball.
        pair_dist = 0.5 * (dist[:, iu] + dist[:, ju])              # (B, n_pairs)
        # Bin index: searchsorted with right=True puts each value into [edge_i, edge_{i+1}).
        # We need: dist in [0, 5) -> 0; [5, 10) -> 1; ...; [45, +inf) -> 9.
        # searchsorted(BIN_EDGES[1:], v, side="right") gives 0 for v<5, 1 for v in [5,10), etc.
        bin_idx = np.searchsorted(BIN_EDGES[1:], pair_dist, side="right")  # (B, n_pairs)
        np.clip(bin_idx, 0, N_BINS - 1, out=bin_idx)

        # Pair-attention values.
        batch_vals = pair_attn[:, iu, ju]                          # (B, n_pairs)
        mask = (
            (ids_arr[:, iu] >= 0)
            & (ids_arr[:, ju] >= 0)
            & (ids_arr[:, iu] != ids_arr[:, ju])
        )                                                          # (B, n_pairs)

        # Global accumulators (don't require pair IDs; only the bin).
        masked_vals = batch_vals[mask]
        masked_bins = bin_idx[mask]
        # bincount with weights for sum; with no weights for count.
        global_bin_attn += np.bincount(
            masked_bins, weights=masked_vals, minlength=N_BINS
        ).astype(np.float64)
        global_bin_n += np.bincount(masked_bins, minlength=N_BINS).astype(np.int64)

        # Per-pair accumulators (need to group by (a, b)).
        a_arr = np.minimum(ids_arr[:, iu], ids_arr[:, ju])
        b_arr = np.maximum(ids_arr[:, iu], ids_arr[:, ju])

        a_flat = a_arr[mask].astype(np.int64)
        b_flat = b_arr[mask].astype(np.int64)
        bin_flat = masked_bins.astype(np.int64)
        v_flat = masked_vals.astype(np.float64)

        # Composite key: (a, b, bin).
        # a, b fit in 32 bits; bin is small (< 16).
        composite = (a_flat.astype(np.int64) << 36) | (b_flat.astype(np.int64) << 4) | bin_flat
        uniq, inv = np.unique(composite, return_inverse=True)
        sum_per_key = np.zeros(uniq.shape[0], dtype=np.float64)
        cnt_per_key = np.zeros(uniq.shape[0], dtype=np.int64)
        np.add.at(sum_per_key, inv, v_flat)
        np.add.at(cnt_per_key, inv, 1)

        decoded_a = (uniq >> 36).astype(np.int64)
        decoded_b = ((uniq >> 4) & ((1 << 32) - 1)).astype(np.int64)
        decoded_bin = (uniq & 0xF).astype(np.int64)

        # Scatter into per-pair dicts and pair_sums.
        for k in range(uniq.shape[0]):
            key = (int(decoded_a[k]), int(decoded_b[k]))
            b = int(decoded_bin[k])
            pair_sums[key] += float(sum_per_key[k])
            pair_bins[key][b] += float(sum_per_key[k])
            pair_bin_frames[key][b] += int(cnt_per_key[k])

    return (
        dict(pair_sums),
        {k: v.copy() for k, v in pair_bins.items()},
        {k: v.copy() for k, v in pair_bin_frames.items()},
        global_bin_attn,
        global_bin_n,
        player_info,
    )


def _shard_to_rows(
    match_id: int,
    pair_sums: dict[tuple[int, int], float],
    pair_bins: dict[tuple[int, int], np.ndarray],
    pair_bin_frames: dict[tuple[int, int], np.ndarray],
    player_info: dict[int, dict],
    lineup_team: dict[tuple[int, int], str],
) -> list[dict]:
    rows: list[dict] = []
    for (pi, pj), val in pair_sums.items():
        info_i = player_info.get(pi, {})
        info_j = player_info.get(pj, {})
        team_i = lineup_team.get((match_id, pi)) or info_i.get("team_id", "")
        team_j = lineup_team.get((match_id, pj)) or info_j.get("team_id", "")
        same = bool(team_i and team_j and team_i == team_j)
        row = {
            "game_id": match_id,
            "team_id": team_i,
            "player_p": pi,
            "name_p": info_i.get("name", ""),
            "player_q": pj,
            "name_q": info_j.get("name", ""),
            "same_team": same,
            "pair_attention": val,
        }
        # Per-bin frame counts + per-bin sums for later baseline computation.
        bin_frames = pair_bin_frames.get((pi, pj), np.zeros(N_BINS, dtype=np.int64))
        bin_attn = pair_bins.get((pi, pj), np.zeros(N_BINS, dtype=np.float64))
        for b in range(N_BINS):
            row[f"frames_bin_{b}"] = int(bin_frames[b])
            row[f"attn_bin_{b}"] = float(bin_attn[b])
        rows.append(row)
    return rows


def _save_global_baseline(
    global_bin_attn: np.ndarray, global_bin_n: np.ndarray, path: Path
) -> None:
    df = pd.DataFrame({
        "bin_index": np.arange(N_BINS),
        "bin_lower_m": BIN_EDGES,
        "bin_upper_m": np.append(BIN_EDGES[1:], np.inf),
        "total_attention": global_bin_attn,
        "total_pair_frames": global_bin_n,
    })
    df.to_parquet(path, index=False)


def _load_global_baseline(path: Path) -> tuple[np.ndarray, np.ndarray]:
    df = pd.read_parquet(path)
    return (
        df.total_attention.to_numpy().astype(np.float64),
        df.total_pair_frames.to_numpy().astype(np.int64),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-idx", type=int, default=0)
    ap.add_argument("--end-idx", type=int, default=-1)
    ap.add_argument(
        "--combine",
        action="store_true",
        help="Read all shards, compute per-bin baseline, write the final parquet.",
    )
    args = ap.parse_args()

    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    global_path = SHARD_DIR / "_global_bin_totals.parquet"

    if args.combine:
        shards = sorted(p for p in SHARD_DIR.glob("*.parquet") if p.name != "_global_bin_totals.parquet")
        if not shards:
            print("[combine] no shards present.")
            return 1
        # Always rebuild global totals from the per-match npz files so that
        # parallel workers (which can race on the shared parquet) still
        # produce a deterministic baseline.
        global_attn = np.zeros(N_BINS, dtype=np.float64)
        global_n = np.zeros(N_BINS, dtype=np.int64)
        for npz_path in sorted(SHARD_DIR.glob("*._globals.npz")):
            with np.load(npz_path) as z:
                global_attn += z["attn"].astype(np.float64)
                global_n += z["n"].astype(np.int64)
        _save_global_baseline(global_attn, global_n, global_path)
        # baseline_per_bin = global_attn / global_n; safe-divide for empty bins.
        baseline = np.zeros(N_BINS, dtype=np.float64)
        nz = global_n > 0
        baseline[nz] = global_attn[nz] / global_n[nz]
        print(f"[combine] per-bin baseline (mean pair-attention) by distance:")
        for b in range(N_BINS):
            lo = BIN_EDGES[b]
            hi = BIN_EDGES[b + 1] if b + 1 < N_BINS else float("inf")
            print(
                f"  bin {b} [{lo:.0f}-{hi:.0f}m): n={int(global_n[b]):>10}  "
                f"mean={baseline[b]:.4f}"
            )

        df = pd.concat([pd.read_parquet(p) for p in shards], ignore_index=True)
        bin_frame_cols = [f"frames_bin_{b}" for b in range(N_BINS)]
        frames_mat = df[bin_frame_cols].to_numpy().astype(np.float64)  # (rows, N_BINS)
        # Expected attention for the pair = dot(frames_in_bin, baseline_per_bin).
        df["pair_attention_expected"] = frames_mat @ baseline
        df["pair_attention_baselined"] = df["pair_attention"] - df["pair_attention_expected"]

        # Drop the bookkeeping columns from the published parquet — keep only
        # what's useful downstream.
        keep = [
            "game_id", "team_id",
            "player_p", "name_p",
            "player_q", "name_q",
            "same_team",
            "pair_attention",
            "pair_attention_expected",
            "pair_attention_baselined",
        ]
        df_out = df[keep].copy()
        df_out = df_out.astype({
            "game_id": "int64", "team_id": "string",
            "player_p": "int64", "name_p": "string",
            "player_q": "int64", "name_q": "string",
            "same_team": "bool",
            "pair_attention": "float64",
            "pair_attention_expected": "float64",
            "pair_attention_baselined": "float64",
        })
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df_out.to_parquet(OUT_PATH, index=False)
        print(
            f"[combine] {len(shards)} shards -> {OUT_PATH} "
            f"({len(df_out)} rows, {df_out.game_id.nunique()} matches)"
        )
        return 0

    device = pick_device()
    print(f"[init] device = {device}", flush=True)
    print(f"[init] loading frame-VAEP model from {CKPT_PATH}", flush=True)
    lit = FrameVaepLitModule.load_from_checkpoint(CKPT_PATH, map_location=device)
    lit.eval().to(device)

    lineups = pd.read_parquet(LINEUPS_PATH)
    lineup_team: dict[tuple[int, int], str] = {
        (int(r.game_id), int(r.player_id)): str(r.team_id)
        for r in lineups.itertuples(index=False)
    }

    pff_root = Path("/Users/nick/Desktop/drive-download-20260518T234612Z-3-001")
    import os
    if "PFF_ROOT" in os.environ:
        pff_root = Path(os.environ["PFF_ROOT"])
    tracking_ids = {
        p.stem.replace(".jsonl", "")
        for p in (pff_root / "Tracking Data").glob("*.jsonl.bz2")
    }
    all_matches = sorted(int(p.stem) for p in event_files() if p.stem in tracking_ids)
    end_idx = len(all_matches) if args.end_idx < 0 else args.end_idx
    matches = all_matches[args.start_idx:end_idx]
    print(
        f"[init] {len(all_matches)} PFF matches with tracking; processing "
        f"[{args.start_idx}:{end_idx}] = {len(matches)} matches",
        flush=True,
    )

    # Global bin totals are accumulated into per-match .npz files; the
    # --combine pass adds them up. Parallel workers must NOT share the
    # running parquet because they'd race on writes.
    t0 = time.time()
    for mi, match_id in enumerate(matches, 1):
        shard_path = SHARD_DIR / f"{match_id}.parquet"
        # Companion file storing per-match global contribution (so we can
        # re-aggregate global totals from scratch if needed).
        match_global_path = SHARD_DIR / f"{match_id}._globals.npz"
        if shard_path.exists() and match_global_path.exists():
            print(
                f"  [{mi}/{len(matches)}] match {match_id}: shard exists, skipping",
                flush=True,
            )
            continue
        tm0 = time.time()
        match_id_s = str(match_id)
        try:
            (
                pair_sums,
                pair_bins,
                pair_bin_frames,
                m_global_attn,
                m_global_n,
                player_info,
            ) = process_match(match_id_s, lit, device)
        except Exception as e:
            print(
                f"  [{mi}/{len(matches)}] match {match_id} FAILED: {e}",
                flush=True,
            )
            traceback.print_exc()
            continue
        if not pair_sums:
            print(f"  [{mi}/{len(matches)}] match {match_id}: no pairs?", flush=True)
            continue

        rows = _shard_to_rows(
            match_id,
            pair_sums,
            pair_bins,
            pair_bin_frames,
            player_info,
            lineup_team,
        )
        df = pd.DataFrame(rows)
        df.to_parquet(shard_path, index=False)
        np.savez(match_global_path, attn=m_global_attn, n=m_global_n)

        dt = time.time() - tm0
        print(
            f"  [{mi}/{len(matches)}] match {match_id}: {len(pair_sums)} pairs "
            f"in {dt:.1f}s -> {shard_path.name} "
            f"(elapsed {time.time()-t0:.1f}s)",
            flush=True,
        )

    print(f"[done] wrote shards to {SHARD_DIR}", flush=True)
    print(
        "[done] run with --combine to compute the per-bin baseline and emit "
        f"{OUT_PATH.name}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
