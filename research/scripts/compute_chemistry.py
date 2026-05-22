"""Compute JOI / JDI / JOI90 / JDI90 for all PFF WC22 pairs and write parquet."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chemistry.joint.goals import compute_goal_pair_stats
from chemistry.joint.jdi import compute_jdi, compute_oi_per_match, compute_expected_oi
from chemistry.joint.joi import compute_joi


def main() -> None:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    spadl_vaep = pd.read_parquet(data_dir / "spadl_vaep.parquet")
    pm = pd.read_parquet(data_dir / "minutes" / "pair_minutes.parquet")
    pop = pd.read_parquet(data_dir / "minutes" / "pair_opponent_minutes.parquet")
    ln = pd.read_parquet(data_dir / "minutes" / "lineups.parquet")
    matches = pd.read_parquet(data_dir / "matches.parquet")

    print(f"Computing JOI on {len(spadl_vaep)} actions, {len(pm)} pair-match rows…")
    joi = compute_joi(spadl_vaep, pm)
    joi.to_parquet(data_dir / "joi.parquet", index=False)
    print(f"JOI rows: {len(joi)}")

    print("\nComputing JDI (slower; iterates pair × opponent)…")
    jdi = compute_jdi(spadl_vaep, pop, ln, pm, matches)
    jdi.to_parquet(data_dir / "jdi.parquet", index=False)
    print(f"JDI rows: {len(jdi)}")

    # Per-player OI / expected OI
    oi = compute_oi_per_match(spadl_vaep)
    exp_oi = compute_expected_oi(oi, ln, matches)
    oi.to_parquet(data_dir / "oi_per_match.parquet", index=False)
    exp_oi.to_parquet(data_dir / "expected_oi.parquet", index=False)

    # Goals + assists per pair
    print("\nComputing per-pair goals + assists…")
    gp = compute_goal_pair_stats(spadl_vaep)
    gp.to_parquet(data_dir / "pair_goals.parquet", index=False)
    print(f"pair_goals rows: {len(gp)}")

    print("\nTop 10 JOI90 pairs (≥ 90 minutes together):")
    print(joi[joi.minutes_together >= 90].head(10)[
        ["team_id", "name_p", "name_q", "minutes_together", "joi", "joi90"]
    ].to_string(index=False))
    print("\nTop 10 JDI90 pairs (≥ 90 minutes together):")
    print(jdi[jdi.minutes_together >= 90].head(10)[
        ["team_id", "name_p", "name_q", "minutes_together", "jdi", "jdi90"]
    ].to_string(index=False))


if __name__ == "__main__":
    main()
