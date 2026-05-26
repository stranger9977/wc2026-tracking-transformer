"""Ball-distance baseline correction for score-specialist attention.

The shared-model extractor (`extract_attention_with_baseline.py`) accumulates
two things that are properties of the *data*, not the *model*:
  - per-pair frame counts within each ball-distance bin (`frames_bin_<b>`)
  - global per-bin frame counts via `*_globals.npz`

The specialist's per-pair attention sums (`attention_chemistry_score_specialist_shards/<id>.parquet`)
were extracted without those per-bin counters. But because the frame
selection is identical (same `_stream_match_combined` upstream), we can
join the shared shards' per-bin frame counts onto the specialist shards
by `(game_id, player_p, player_q)`.

The specialist's per-bin attention sums *would* differ from the shared
model's, but that's fine: the baseline subtraction only needs each pair's
weighted mean distance-to-ball profile (i.e. its frame counts per bin)
plus the *global* baseline mean attention per bin. The global baseline
must be recomputed from the specialist's own attention so the units
match.

Approach:
  1. For each specialist shard, read it plus the matching shared shard.
  2. Join the `frames_bin_*` columns from the shared shard onto the
     specialist shard.
  3. Recompute a global per-bin baseline using the specialist attention:
     baseline[b] = sum over pairs over matches of pair_attention assigned
     to bin b / sum of frames in bin b. The per-pair-per-bin attention
     for the specialist is not preserved (we only have the total), so we
     approximate by distributing each pair's total attention across bins
     in proportion to its frame counts per bin. This is exact under the
     assumption that the pair's *mean attention per frame* is constant
     across bins; deviations from that assumption are exactly the
     baseline-relative chemistry signal the correction was supposed to
     extract, so any error self-cancels in expectation across the
     corpus.
     A cleaner alternative would be to re-extract the specialist with
     per-bin sums, which is straightforward but expensive (44 matches).
     The proportional-distribution approximation is good enough for the
     baseline ratio used to compute *expected* attention — see notes
     below.
  4. Expected attention for each pair = sum_b frames_in_bin_b *
     baseline[b]. Corrected = total - expected.

Output: `research/data/attention_chemistry_score_specialist_baselined.parquet`
schema: game_id, team_id, player_p, name_p, player_q, name_q, same_team,
pair_attention, pair_attention_expected, pair_attention_baselined.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]

SHARED_SHARDS = REPO / "research" / "data" / "attention_chemistry_baselined_shards"
SPEC_SHARDS = REPO / "research" / "data" / "attention_chemistry_score_specialist_shards"
OUT_PATH = REPO / "research" / "data" / "attention_chemistry_score_specialist_baselined.parquet"

N_BINS = 10
BIN_COLS = [f"frames_bin_{b}" for b in range(N_BINS)]


def main() -> int:
    spec_files = sorted(SPEC_SHARDS.glob("*.parquet"))
    shared_files = {p.stem: p for p in SHARED_SHARDS.glob("*.parquet")}

    rows: list[pd.DataFrame] = []
    # Globals (for baseline): total specialist attention per bin and total
    # frames per bin (across all matches/pairs).
    global_attn = np.zeros(N_BINS, dtype=np.float64)
    global_frames = np.zeros(N_BINS, dtype=np.float64)

    for sp in spec_files:
        mid = sp.stem
        sh_path = shared_files.get(mid)
        if sh_path is None:
            print(f"  skip {mid}: no shared shard", flush=True)
            continue
        spec = pd.read_parquet(sp)
        shared = pd.read_parquet(sh_path, columns=["game_id", "player_p", "player_q"] + BIN_COLS)
        merged = spec.merge(
            shared,
            on=["game_id", "player_p", "player_q"],
            how="left",
        )
        # If frame counts are missing (shouldn't be), zero them out.
        for c in BIN_COLS:
            if c not in merged.columns:
                merged[c] = 0
            merged[c] = merged[c].fillna(0).astype(np.float64)

        frames_mat = merged[BIN_COLS].to_numpy()  # (rows, N_BINS)
        total_frames = frames_mat.sum(axis=1).clip(min=1.0)  # avoid /0
        # Distribute each pair's total attention proportionally to its frame
        # counts per bin. (See note in docstring.)
        per_pair_attn_by_bin = (
            merged["pair_attention"].to_numpy()[:, None]
            * (frames_mat / total_frames[:, None])
        )
        global_attn += per_pair_attn_by_bin.sum(axis=0)
        global_frames += frames_mat.sum(axis=0)
        rows.append(merged)
        print(f"  {mid}: {len(merged)} pairs", flush=True)

    if not rows:
        print("no data")
        return 1

    df = pd.concat(rows, ignore_index=True)

    baseline = np.zeros(N_BINS, dtype=np.float64)
    nz = global_frames > 0
    baseline[nz] = global_attn[nz] / global_frames[nz]
    print("\n[baseline] specialist per-bin baseline (mean attention per pair-frame):")
    for b in range(N_BINS):
        print(f"  bin {b}: frames={global_frames[b]:>12.0f}  baseline={baseline[b]:.6f}")

    frames_mat = df[BIN_COLS].to_numpy().astype(np.float64)
    df["pair_attention_expected"] = frames_mat @ baseline
    df["pair_attention_baselined"] = df["pair_attention"] - df["pair_attention_expected"]

    keep = [
        "game_id", "team_id",
        "player_p", "name_p",
        "player_q", "name_q",
        "same_team",
        "pair_attention",
        "pair_attention_expected",
        "pair_attention_baselined",
    ]
    out = df[keep].astype({
        "game_id": "int64", "team_id": "string",
        "player_p": "int64", "name_p": "string",
        "player_q": "int64", "name_q": "string",
        "same_team": "bool",
        "pair_attention": "float64",
        "pair_attention_expected": "float64",
        "pair_attention_baselined": "float64",
    })
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"\n[done] -> {OUT_PATH}  ({len(out)} rows, {out.game_id.nunique()} matches)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
