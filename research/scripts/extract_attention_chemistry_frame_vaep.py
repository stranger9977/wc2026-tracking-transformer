"""Per-match player-pair attention chemistry extraction (frame-VAEP variant).

Same as extract_attention_chemistry.py, but uses the trained frame-VAEP
checkpoint (P(score) / P(concede) heads) instead of the older xT-regression
checkpoint. Outputs research/data/attention_chemistry.parquet.
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

# Reuse the streaming logic from the xT script — it only depends on the loader,
# not the model architecture.
from extract_attention_chemistry import _stream_match_combined, NUM_PLAYER_SLOTS, BATCH_SIZE  # noqa: E402

from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule  # noqa: E402
from chemistry.loaders.pff_paths import event_files  # noqa: E402

OUT_PATH = REPO_ROOT / "research" / "data" / "attention_chemistry.parquet"
SHARD_DIR = REPO_ROOT / "research" / "data" / "attention_chemistry_shards"
CKPT_PATH = REPO_ROOT / "output" / "transformer_frame_vaep.ckpt"
LINEUPS_PATH = REPO_ROOT / "research" / "data" / "minutes" / "lineups.parquet"


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def process_match(match_id: str, lit: FrameVaepLitModule, device: torch.device):
    out_tensors, out_ids, player_info, _team_names = _stream_match_combined(match_id)
    if not out_tensors:
        return {}, {}

    pair_sums: dict[tuple[int, int], float] = defaultdict(float)
    n_frames = len(out_tensors)
    iu, ju = np.triu_indices(NUM_PLAYER_SLOTS, k=1)

    for start in range(0, n_frames, BATCH_SIZE):
        end = min(start + BATCH_SIZE, n_frames)
        tensors_np = np.stack(out_tensors[start:end], axis=0)
        x = torch.from_numpy(tensors_np).to(device)
        with torch.no_grad():
            _, attn = lit.backbone.encode_with_attention(x)
        pair_attn = attn.mean(dim=(1, 2)).cpu().numpy()
        pair_attn = pair_attn + np.transpose(pair_attn, (0, 2, 1))
        pair_attn = pair_attn[:, :NUM_PLAYER_SLOTS, :NUM_PLAYER_SLOTS]

        batch_vals = pair_attn[:, iu, ju]
        ids_arr = np.stack(out_ids[start:end], axis=0)
        a_arr = np.minimum(ids_arr[:, iu], ids_arr[:, ju])
        b_arr = np.maximum(ids_arr[:, iu], ids_arr[:, ju])
        mask = (ids_arr[:, iu] >= 0) & (ids_arr[:, ju] >= 0) & (ids_arr[:, iu] != ids_arr[:, ju])

        a_flat = a_arr[mask]
        b_flat = b_arr[mask]
        v_flat = batch_vals[mask]
        keys = a_flat.astype(np.int64) * (1 << 32) + b_flat.astype(np.int64)
        uniq_keys, inv = np.unique(keys, return_inverse=True)
        grouped = np.zeros(uniq_keys.shape[0], dtype=np.float64)
        np.add.at(grouped, inv, v_flat)
        uniq_a = (uniq_keys >> 32).astype(np.int64)
        uniq_b = (uniq_keys & ((1 << 32) - 1)).astype(np.int64)
        for k in range(uniq_keys.shape[0]):
            pair_sums[(int(uniq_a[k]), int(uniq_b[k]))] += float(grouped[k])

    return dict(pair_sums), player_info


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
        print(f"[combine] {len(shards)} shards -> {OUT_PATH} ({len(df)} rows, "
              f"{df.game_id.nunique()} matches)")
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

    # Filter to matches that have BOTH event data and tracking data — the PFF
    # release has more events than tracking, so don't try to process matches
    # without the .jsonl.bz2 file.
    pff_root = Path("/Users/nick/Desktop/drive-download-20260518T234612Z-3-001")
    if "PFF_ROOT" in (env_root := __import__("os").environ).keys():
        pff_root = Path(env_root["PFF_ROOT"])
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
            pair_sums, player_info = process_match(match_id_s, lit, device)
        except Exception as e:
            print(f"  [{mi}/{len(matches)}] match {match_id} FAILED: {e}", flush=True)
            traceback.print_exc()
            continue
        if not pair_sums:
            print(f"  [{mi}/{len(matches)}] match {match_id}: no pairs?", flush=True)
            continue
        rows = []
        for (pi, pj), val in pair_sums.items():
            info_i = player_info.get(pi, {})
            info_j = player_info.get(pj, {})
            team_i = lineup_team.get((match_id, pi)) or info_i.get("team_id", "")
            team_j = lineup_team.get((match_id, pj)) or info_j.get("team_id", "")
            same = bool(team_i and team_j and team_i == team_j)
            rows.append({
                "game_id": match_id,
                "team_id": team_i,
                "player_p": pi,
                "name_p": info_i.get("name", ""),
                "player_q": pj,
                "name_q": info_j.get("name", ""),
                "same_team": same,
                "pair_attention": val,
            })
        df = pd.DataFrame(rows).astype({
            "game_id": "int64", "team_id": "string",
            "player_p": "int64", "name_p": "string",
            "player_q": "int64", "name_q": "string",
            "same_team": "bool", "pair_attention": "float64",
        })
        df.to_parquet(shard_path, index=False)
        dt = time.time() - tm0
        print(f"  [{mi}/{len(matches)}] match {match_id}: {len(pair_sums)} pairs in {dt:.1f}s "
              f"-> {shard_path.name} (elapsed {time.time()-t0:.1f}s)", flush=True)
    print(f"[done] wrote shards to {SHARD_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
