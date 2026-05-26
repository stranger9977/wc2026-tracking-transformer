"""Attention-Weighted Joint Offensive/Defensive Impact (AW-JOI / AW-JDI).

For each frame t, per same-team pair (p, q):

  c(p, q, t)  = attn_ball->p (t) * attn_ball->q (t)   (pair coupling)
  V_score(t)  = p_score(t+1) - p_score(t)             (Delta P_score)
  V_concede(t)= p_concede(t+1) - p_concede(t)         (Delta P_concede)

  AW-JOI(p, q) = Sum_t c_score(p, q, t)   * max(V_score(t),   0)
  AW-JDI(p, q) = Sum_t c_concede(p, q, t) * max(V_concede(t), 0)

Where c_score uses the score-specialist's ball->player attention and
p_score, and c_concede uses the concede-specialist's ball->player
attention and p_concede.

Per-match shards -> research/data/aw_chemistry_shards/<match>.parquet
Combined         -> research/data/aw_chemistry.parquet

Usage:
    # one worker
    PYTHONPATH=src:research/src uv run python \\
      research/scripts/extract_aw_joi.py --combine-after

    # 4 parallel workers (then combine)
    for i in 0 1 2 3; do
      PYTHONPATH=src:research/src uv run python \\
        research/scripts/extract_aw_joi.py --start-idx $((i*11)) --end-idx $(((i+1)*11)) &
    done; wait
    PYTHONPATH=src:research/src uv run python \\
      research/scripts/extract_aw_joi.py --combine
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
sys.path.insert(0, str(REPO_ROOT / "research" / "scripts"))

from extract_attention_chemistry import _stream_match_combined, NUM_PLAYER_SLOTS, BATCH_SIZE  # noqa: E402

from wc2026_tracking_transformer.model.frame_vaep_specialist import (  # noqa: E402
    FrameVaepSpecialistLitModule,
)
from chemistry.loaders.pff_paths import event_files  # noqa: E402

CACHE_DIR = REPO_ROOT / "research" / "data" / "frame_vaep_cache"
LINEUPS_PATH = REPO_ROOT / "research" / "data" / "minutes" / "lineups.parquet"
BALL_TOKEN = NUM_PLAYER_SLOTS  # index 22
EPSILON = 1e-9


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


@torch.no_grad()
def _attn_and_pred(lit: FrameVaepSpecialistLitModule, x: torch.Tensor) -> tuple[np.ndarray, np.ndarray]:
    """Return (ball_attn (B, NUM_PLAYER_SLOTS), p (B,)).

    Ball-to-player attention is taken as ``attn[b, :, :, ball, players]``
    averaged across layers and heads. We use the ball as the QUERY (row)
    so the values sum to ~1 across keys for each frame -- this matches
    the standard "what the ball attends to" reading.
    """
    enc, attn = lit.backbone.encode_with_attention(x)  # attn: (B, L, H, T, T)
    # ball-as-query row, players as keys
    ball_attn = attn[:, :, :, BALL_TOKEN, :NUM_PLAYER_SLOTS]  # (B, L, H, P)
    ball_attn = ball_attn.mean(dim=(1, 2))  # (B, P)
    logit = lit.task_head(enc)  # (B,)
    p = torch.sigmoid(logit)
    return ball_attn.cpu().numpy(), p.cpu().numpy()


def _accumulate(
    pair_sums: dict[tuple[int, int], float],
    pair_ns: dict[tuple[int, int], int],
    ball_attn: np.ndarray,    # (N, P)
    weight: np.ndarray,       # (N,) -- max(dV, 0)
    ids: np.ndarray,          # (N, P) int64
):
    """Per-frame pair accumulation: c(p,q,t) * weight(t).

    For each frame: outer product of (attn[:P]) * weight, then mask same-id /
    -1, then upper-triangular pair sums.
    """
    iu, ju = np.triu_indices(NUM_PLAYER_SLOTS, k=1)
    # c[p,q] = a_p * a_q, weighted by w (broadcast)
    # contributions per frame, only positive weights matter (others contribute 0 anyway)
    nz = weight > 0
    if not nz.any():
        return
    ball_attn_nz = ball_attn[nz]      # (M, P)
    weight_nz = weight[nz]            # (M,)
    ids_nz = ids[nz]                  # (M, P)

    # pair attn coupling: (M, P, P) outer per frame -- avoid by computing only triu
    a_i = ball_attn_nz[:, iu]   # (M, K)
    a_j = ball_attn_nz[:, ju]   # (M, K)
    c = a_i * a_j               # (M, K)
    contribs = c * weight_nz[:, None]  # (M, K)

    id_i = ids_nz[:, iu]
    id_j = ids_nz[:, ju]
    valid = (id_i >= 0) & (id_j >= 0) & (id_i != id_j)

    if not valid.any():
        return
    a_flat = np.minimum(id_i, id_j)[valid]
    b_flat = np.maximum(id_i, id_j)[valid]
    v_flat = contribs[valid]

    keys = a_flat.astype(np.int64) * (1 << 32) + b_flat.astype(np.int64)
    uniq_keys, inv = np.unique(keys, return_inverse=True)
    sum_g = np.zeros(uniq_keys.shape[0], dtype=np.float64)
    cnt_g = np.zeros(uniq_keys.shape[0], dtype=np.int64)
    # frames where c > eps -- count only those
    active = v_flat > EPSILON
    np.add.at(sum_g, inv, v_flat)
    np.add.at(cnt_g, inv[active], 1)
    uniq_a = (uniq_keys >> 32).astype(np.int64)
    uniq_b = (uniq_keys & ((1 << 32) - 1)).astype(np.int64)
    for k in range(uniq_keys.shape[0]):
        key = (int(uniq_a[k]), int(uniq_b[k]))
        pair_sums[key] += float(sum_g[k])
        pair_ns[key] += int(cnt_g[k])


def process_match(
    match_id: str,
    lit_score: FrameVaepSpecialistLitModule,
    lit_concede: FrameVaepSpecialistLitModule,
    device: torch.device,
):
    out_tensors, out_ids, player_info, _ = _stream_match_combined(match_id)
    if not out_tensors:
        return None, None, None, None

    n_frames = len(out_tensors)
    ids_arr_full = np.stack(out_ids, axis=0)  # (N, P)

    # Pass 1: score specialist -- get ball_attn and p_score per frame
    p_score = np.zeros(n_frames, dtype=np.float64)
    ball_attn_score = np.zeros((n_frames, NUM_PLAYER_SLOTS), dtype=np.float64)
    for start in range(0, n_frames, BATCH_SIZE):
        end = min(start + BATCH_SIZE, n_frames)
        x = torch.from_numpy(np.stack(out_tensors[start:end], axis=0)).to(device)
        ba, p = _attn_and_pred(lit_score, x)
        ball_attn_score[start:end] = ba
        p_score[start:end] = p

    # Pass 2: concede specialist -- get ball_attn and p_concede per frame
    p_concede = np.zeros(n_frames, dtype=np.float64)
    ball_attn_concede = np.zeros((n_frames, NUM_PLAYER_SLOTS), dtype=np.float64)
    for start in range(0, n_frames, BATCH_SIZE):
        end = min(start + BATCH_SIZE, n_frames)
        x = torch.from_numpy(np.stack(out_tensors[start:end], axis=0)).to(device)
        ba, p = _attn_and_pred(lit_concede, x)
        ball_attn_concede[start:end] = ba
        p_concede[start:end] = p

    # Forward differences -- last frame's dv = 0
    dv_score = np.zeros(n_frames, dtype=np.float64)
    dv_concede = np.zeros(n_frames, dtype=np.float64)
    dv_score[:-1] = p_score[1:] - p_score[:-1]
    dv_concede[:-1] = p_concede[1:] - p_concede[:-1]

    w_joi = np.clip(dv_score, 0.0, None)
    w_jdi = np.clip(dv_concede, 0.0, None)

    pair_joi_sum: dict[tuple[int, int], float] = defaultdict(float)
    pair_joi_n: dict[tuple[int, int], int] = defaultdict(int)
    pair_jdi_sum: dict[tuple[int, int], float] = defaultdict(float)
    pair_jdi_n: dict[tuple[int, int], int] = defaultdict(int)

    # Accumulate in chunks for memory safety
    for start in range(0, n_frames, BATCH_SIZE):
        end = min(start + BATCH_SIZE, n_frames)
        _accumulate(
            pair_joi_sum, pair_joi_n,
            ball_attn_score[start:end], w_joi[start:end], ids_arr_full[start:end],
        )
        _accumulate(
            pair_jdi_sum, pair_jdi_n,
            ball_attn_concede[start:end], w_jdi[start:end], ids_arr_full[start:end],
        )

    return pair_joi_sum, pair_joi_n, pair_jdi_sum, pair_jdi_n, player_info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score-ckpt", type=str,
                    default=str(REPO_ROOT / "output" / "transformer_score_only.ckpt"))
    ap.add_argument("--concede-ckpt", type=str,
                    default=str(REPO_ROOT / "output" / "transformer_concede_only.ckpt"))
    ap.add_argument("--start-idx", type=int, default=0)
    ap.add_argument("--end-idx", type=int, default=-1)
    ap.add_argument("--combine", action="store_true")
    ap.add_argument("--combine-after", action="store_true")
    ap.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto")
    args = ap.parse_args()

    out_path = REPO_ROOT / "research" / "data" / "aw_chemistry.parquet"
    shard_dir = REPO_ROOT / "research" / "data" / "aw_chemistry_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    def _combine() -> int:
        shards = sorted(shard_dir.glob("*.parquet"))
        if not shards:
            print(f"[combine] no shards in {shard_dir}.")
            return 1
        df = pd.concat([pd.read_parquet(p) for p in shards], ignore_index=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False)
        print(f"[combine] {len(shards)} shards -> {out_path} "
              f"({len(df)} rows, {df.game_id.nunique()} matches)")
        return 0

    if args.combine:
        return _combine()

    device = pick_device() if args.device == "auto" else torch.device(args.device)
    print(f"[init] device = {device}", flush=True)
    print(f"[init] loading score specialist from {args.score_ckpt}", flush=True)
    lit_s = FrameVaepSpecialistLitModule.load_from_checkpoint(args.score_ckpt, map_location=device)
    lit_s.eval().to(device)
    print(f"[init] loading concede specialist from {args.concede_ckpt}", flush=True)
    lit_c = FrameVaepSpecialistLitModule.load_from_checkpoint(args.concede_ckpt, map_location=device)
    lit_c.eval().to(device)

    lineups = pd.read_parquet(LINEUPS_PATH)
    lineup_team: dict[tuple[int, int], str] = {
        (int(r.game_id), int(r.player_id)): str(r.team_id)
        for r in lineups.itertuples(index=False)
    }

    import os
    pff_root = Path("/Users/nick/Desktop/drive-download-20260518T234612Z-3-001")
    if "PFF_ROOT" in os.environ:
        pff_root = Path(os.environ["PFF_ROOT"])
    tracking_ids = {p.stem.replace(".jsonl", "") for p in (pff_root / "Tracking Data").glob("*.jsonl.bz2")}
    all_matches = sorted(int(p.stem) for p in event_files() if p.stem in tracking_ids)
    end_idx = len(all_matches) if args.end_idx < 0 else args.end_idx
    matches = all_matches[args.start_idx:end_idx]
    print(f"[init] {len(all_matches)} PFF matches with tracking; processing "
          f"[{args.start_idx}:{end_idx}] = {len(matches)} matches", flush=True)

    t0 = time.time()
    for mi, match_id in enumerate(matches, 1):
        shard_path = shard_dir / f"{match_id}.parquet"
        if shard_path.exists():
            print(f"  [{mi}/{len(matches)}] match {match_id}: shard exists, skipping", flush=True)
            continue
        tm0 = time.time()
        match_id_s = str(match_id)
        try:
            result = process_match(match_id_s, lit_s, lit_c, device)
        except Exception as e:
            print(f"  [{mi}/{len(matches)}] match {match_id} FAILED: {e}", flush=True)
            traceback.print_exc()
            continue
        if result is None or result[0] is None:
            print(f"  [{mi}/{len(matches)}] match {match_id}: no frames", flush=True)
            continue
        pair_joi_sum, pair_joi_n, pair_jdi_sum, pair_jdi_n, player_info = result

        all_keys: set[tuple[int, int]] = set(pair_joi_sum.keys()) | set(pair_jdi_sum.keys())
        rows = []
        for (pi, pj) in all_keys:
            info_i = player_info.get(pi, {})
            info_j = player_info.get(pj, {})
            team_i = lineup_team.get((int(match_id), pi)) or info_i.get("team_id", "")
            team_j = lineup_team.get((int(match_id), pj)) or info_j.get("team_id", "")
            same = bool(team_i and team_j and team_i == team_j)
            n_active = max(pair_joi_n.get((pi, pj), 0), pair_jdi_n.get((pi, pj), 0))
            rows.append({
                "game_id": int(match_id),
                "team_id": team_i,
                "player_p": pi,
                "name_p": info_i.get("name", ""),
                "player_q": pj,
                "name_q": info_j.get("name", ""),
                "same_team": same,
                "aw_joi_sum": pair_joi_sum.get((pi, pj), 0.0),
                "aw_jdi_sum": pair_jdi_sum.get((pi, pj), 0.0),
                "frames_active": n_active,
            })
        df = pd.DataFrame(rows).astype({
            "game_id": "int64", "team_id": "string",
            "player_p": "int64", "name_p": "string",
            "player_q": "int64", "name_q": "string",
            "same_team": "bool",
            "aw_joi_sum": "float64", "aw_jdi_sum": "float64",
            "frames_active": "int64",
        })
        df.to_parquet(shard_path, index=False)
        joi_total = float(df.aw_joi_sum.sum())
        jdi_total = float(df.aw_jdi_sum.sum())
        dt = time.time() - tm0
        print(f"  [{mi}/{len(matches)}] match {match_id}: {len(df)} pairs, "
              f"aw_joi_total={joi_total:.4f} aw_jdi_total={jdi_total:.4f} "
              f"in {dt:.1f}s (elapsed {time.time()-t0:.1f}s)", flush=True)

    print(f"[done] wrote shards to {shard_dir}", flush=True)
    if args.combine_after:
        return _combine()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
