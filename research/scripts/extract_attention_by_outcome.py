"""Per-match player-pair attention chemistry, conditioned on outcome bucket.

Mirrors ``extract_attention_chemistry_frame_vaep.py`` but accumulates
attention into THREE bucket arrays per pair, keyed by the y_score /
y_concede labels in the frame-VAEP npz cache:

- score:    y_score == 1 frames (team in possession scores within 10 s)
- concede:  y_concede == 1 frames (team in possession concedes within 10 s)
- neutral:  both labels == 0

Per (game_id, team_id, player_p, player_q) we emit:
    attn_score_sum, attn_score_n
    attn_concede_sum, attn_concede_n
    attn_neutral_sum, attn_neutral_n
where ``*_n`` counts frames where the pair is co-active.

Reuses ``_stream_match_combined`` from the existing extractor to get
per-slot player IDs, and reads ``research/data/frame_vaep_cache/<m>.npz``
for labels. The two should align exactly (same stride, same ball-present
filter) — we sanity-check tensor shape per match.

Per-match shards land in ``research/data/attention_by_outcome_shards/``;
``--combine`` concatenates to ``research/data/attention_by_outcome.parquet``.
"""
from __future__ import annotations

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

# Reuse the streaming logic + constants from the xT script.
from extract_attention_chemistry import _stream_match_combined, NUM_PLAYER_SLOTS, BATCH_SIZE  # noqa: E402

from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule  # noqa: E402
from chemistry.loaders.pff_paths import event_files  # noqa: E402

CACHE_DIR = REPO_ROOT / "research" / "data" / "frame_vaep_cache"
OUT_PATH = REPO_ROOT / "research" / "data" / "attention_by_outcome.parquet"
SHARD_DIR = REPO_ROOT / "research" / "data" / "attention_by_outcome_shards"
CKPT_PATH = REPO_ROOT / "output" / "transformer_frame_vaep.ckpt"
LINEUPS_PATH = REPO_ROOT / "research" / "data" / "minutes" / "lineups.parquet"


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def process_match(match_id: str, lit: FrameVaepLitModule, device: torch.device):
    """Return (bucket_sums, bucket_ns, player_info).

    ``bucket_sums[bucket][(pi, pj)]`` -> float, sum of symmetrized
        pair attention across all frames in that bucket where both
        players are on the pitch.
    ``bucket_ns[bucket][(pi, pj)]``   -> int, count of those frames.
    Buckets are "score", "concede", "neutral".
    """
    out_tensors, out_ids, player_info, _ = _stream_match_combined(match_id)
    if not out_tensors:
        return None, None, None

    # Load labels from the cached npz. The cache is built by
    # scripts/precache_pff_tensors.py from the same loader + stride, so the
    # frame counts and ordering should match exactly. Verify shape.
    npz_path = CACHE_DIR / f"{match_id}.npz"
    if not npz_path.exists():
        raise FileNotFoundError(f"npz cache missing: {npz_path}")
    npz = np.load(npz_path)
    y_score = npz["y_score"].astype(np.int8)
    y_concede = npz["y_concede"].astype(np.int8)
    n_stream = len(out_tensors)
    n_cache = y_score.shape[0]
    if n_stream != n_cache:
        # Length mismatch is rare but possible; truncate to min to stay safe.
        # (precache uses min(tensors, labels), so a 1-2 frame delta is OK.)
        n = min(n_stream, n_cache)
        print(f"  [warn] {match_id}: stream={n_stream}, cache={n_cache}, truncating to {n}", flush=True)
        out_tensors = out_tensors[:n]
        out_ids = out_ids[:n]
        y_score = y_score[:n]
        y_concede = y_concede[:n]
    # Frame-level bucket index: 0=neutral, 1=score, 2=concede.
    # "score" takes priority if both heads fire (rare).
    buckets = np.zeros(len(out_tensors), dtype=np.int8)
    buckets[y_concede == 1] = 2
    buckets[y_score == 1] = 1  # score wins ties

    # Per-bucket dicts.
    BUCKET_NAMES = ("neutral", "score", "concede")
    pair_sums: dict[str, dict[tuple[int, int], float]] = {
        b: defaultdict(float) for b in BUCKET_NAMES
    }
    pair_ns: dict[str, dict[tuple[int, int], int]] = {
        b: defaultdict(int) for b in BUCKET_NAMES
    }

    n_frames = len(out_tensors)
    iu, ju = np.triu_indices(NUM_PLAYER_SLOTS, k=1)

    for start in range(0, n_frames, BATCH_SIZE):
        end = min(start + BATCH_SIZE, n_frames)
        tensors_np = np.stack(out_tensors[start:end], axis=0)
        x = torch.from_numpy(tensors_np).to(device)
        with torch.no_grad():
            _, attn = lit.backbone.encode_with_attention(x)
        # mean over (layers, heads) -> (B, T, T)
        pair_attn = attn.mean(dim=(1, 2)).cpu().numpy()
        # Symmetrize and drop ball token.
        pair_attn = pair_attn + np.transpose(pair_attn, (0, 2, 1))
        pair_attn = pair_attn[:, :NUM_PLAYER_SLOTS, :NUM_PLAYER_SLOTS]

        batch_vals = pair_attn[:, iu, ju]               # (B, n_pairs)
        ids_arr = np.stack(out_ids[start:end], axis=0)  # (B, 22)
        a_arr = np.minimum(ids_arr[:, iu], ids_arr[:, ju])
        b_arr = np.maximum(ids_arr[:, iu], ids_arr[:, ju])
        mask = (ids_arr[:, iu] >= 0) & (ids_arr[:, ju] >= 0) & (ids_arr[:, iu] != ids_arr[:, ju])

        bucket_slice = buckets[start:end]  # (B,)

        for bi, bname in enumerate(BUCKET_NAMES):
            # frames in this bucket
            frame_mask = (bucket_slice == bi)
            if not frame_mask.any():
                continue
            # combined mask: pair must be co-active AND frame in bucket
            m = mask & frame_mask[:, None]
            if not m.any():
                continue
            a_flat = a_arr[m]
            b_flat = b_arr[m]
            v_flat = batch_vals[m]
            keys = a_flat.astype(np.int64) * (1 << 32) + b_flat.astype(np.int64)
            uniq_keys, inv = np.unique(keys, return_inverse=True)
            sum_grouped = np.zeros(uniq_keys.shape[0], dtype=np.float64)
            cnt_grouped = np.zeros(uniq_keys.shape[0], dtype=np.int64)
            np.add.at(sum_grouped, inv, v_flat)
            np.add.at(cnt_grouped, inv, 1)
            uniq_a = (uniq_keys >> 32).astype(np.int64)
            uniq_b = (uniq_keys & ((1 << 32) - 1)).astype(np.int64)
            sums_d = pair_sums[bname]
            ns_d = pair_ns[bname]
            for k in range(uniq_keys.shape[0]):
                key = (int(uniq_a[k]), int(uniq_b[k]))
                sums_d[key] += float(sum_grouped[k])
                ns_d[key] += int(cnt_grouped[k])

    return pair_sums, pair_ns, player_info


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-idx", type=int, default=0,
                    help="Inclusive start index into the sorted match list.")
    ap.add_argument("--end-idx", type=int, default=-1,
                    help="Exclusive end index; -1 means all remaining.")
    ap.add_argument("--combine", action="store_true",
                    help="Concatenate per-match shards into the final parquet and exit.")
    args = ap.parse_args()

    SHARD_DIR.mkdir(parents=True, exist_ok=True)

    if args.combine:
        shards = sorted(SHARD_DIR.glob("*.parquet"))
        if not shards:
            print("[combine] no shards present.")
            return 1
        df = pd.concat([pd.read_parquet(p) for p in shards], ignore_index=True)
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUT_PATH, index=False)
        print(f"[combine] {len(shards)} shards -> {OUT_PATH} "
              f"({len(df)} rows, {df.game_id.nunique()} matches)")
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
        shard_path = SHARD_DIR / f"{match_id}.parquet"
        if shard_path.exists():
            print(f"  [{mi}/{len(matches)}] match {match_id}: shard exists, skipping", flush=True)
            continue
        tm0 = time.time()
        match_id_s = str(match_id)
        try:
            pair_sums, pair_ns, player_info = process_match(match_id_s, lit, device)
        except Exception as e:
            print(f"  [{mi}/{len(matches)}] match {match_id} FAILED: {e}", flush=True)
            traceback.print_exc()
            continue
        if pair_sums is None:
            print(f"  [{mi}/{len(matches)}] match {match_id}: no frames", flush=True)
            continue

        # Build a row per unique pair, with three buckets side-by-side.
        all_keys: set[tuple[int, int]] = set()
        for b in pair_sums:
            all_keys.update(pair_sums[b].keys())
        rows = []
        for (pi, pj) in all_keys:
            info_i = player_info.get(pi, {})
            info_j = player_info.get(pj, {})
            team_i = lineup_team.get((int(match_id), pi)) or info_i.get("team_id", "")
            team_j = lineup_team.get((int(match_id), pj)) or info_j.get("team_id", "")
            same = bool(team_i and team_j and team_i == team_j)
            rows.append({
                "game_id": int(match_id),
                "team_id": team_i,
                "player_p": pi,
                "name_p": info_i.get("name", ""),
                "player_q": pj,
                "name_q": info_j.get("name", ""),
                "same_team": same,
                "attn_score_sum": pair_sums["score"].get((pi, pj), 0.0),
                "attn_score_n": pair_ns["score"].get((pi, pj), 0),
                "attn_concede_sum": pair_sums["concede"].get((pi, pj), 0.0),
                "attn_concede_n": pair_ns["concede"].get((pi, pj), 0),
                "attn_neutral_sum": pair_sums["neutral"].get((pi, pj), 0.0),
                "attn_neutral_n": pair_ns["neutral"].get((pi, pj), 0),
            })
        df = pd.DataFrame(rows).astype({
            "game_id": "int64", "team_id": "string",
            "player_p": "int64", "name_p": "string",
            "player_q": "int64", "name_q": "string",
            "same_team": "bool",
            "attn_score_sum": "float64", "attn_score_n": "int64",
            "attn_concede_sum": "float64", "attn_concede_n": "int64",
            "attn_neutral_sum": "float64", "attn_neutral_n": "int64",
        })
        df.to_parquet(shard_path, index=False)
        n_score = int(df["attn_score_n"].sum())
        n_concede = int(df["attn_concede_n"].sum())
        n_neutral = int(df["attn_neutral_n"].sum())
        dt = time.time() - tm0
        print(f"  [{mi}/{len(matches)}] match {match_id}: {len(df)} pairs, "
              f"frame-pair counts score={n_score} concede={n_concede} neutral={n_neutral} "
              f"in {dt:.1f}s (elapsed {time.time()-t0:.1f}s)", flush=True)
    print(f"[done] wrote shards to {SHARD_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
