"""Convert every PFF match to SPADL parquet + minutes/lineup parquets.

Usage:
    PYTHONPATH=research/src uv run python research/scripts/build_spadl.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chemistry.loaders.minutes import lineup_table, pair_minutes, pair_opponent_minutes
from chemistry.loaders.pff_paths import event_files
from chemistry.loaders.pff_spadl import events_to_spadl


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "data"
    spadl_dir = out / "spadl"
    spadl_dir.mkdir(parents=True, exist_ok=True)
    minutes_dir = out / "minutes"
    minutes_dir.mkdir(parents=True, exist_ok=True)

    all_lineups: list[pd.DataFrame] = []
    all_pair_mins: list[pd.DataFrame] = []
    all_pair_opp: list[pd.DataFrame] = []
    matches = []

    files = event_files()
    print(f"Converting {len(files)} PFF matches…")
    for fp in tqdm(files):
        mid = int(fp.stem)
        try:
            df, meta = events_to_spadl(mid)
        except Exception as e:
            print(f"[skip] {mid}: {e}")
            continue
        df.to_parquet(spadl_dir / f"{mid}.parquet", index=False)
        ln = lineup_table(mid)
        all_lineups.append(ln)
        pm = pair_minutes(mid)
        if not pm.empty:
            all_pair_mins.append(pm)
        po = pair_opponent_minutes(mid)
        if not po.empty:
            all_pair_opp.append(po)
        matches.append({
            "game_id": meta.match_id,
            "home_id": meta.home_id, "home_name": meta.home_name, "home_color": meta.home_color,
            "away_id": meta.away_id, "away_name": meta.away_name, "away_color": meta.away_color,
            "date": meta.date,
            "n_actions": len(df),
        })

    pd.DataFrame(matches).to_parquet(out / "matches.parquet", index=False)
    pd.concat(all_lineups, ignore_index=True).to_parquet(minutes_dir / "lineups.parquet", index=False)
    pd.concat(all_pair_mins, ignore_index=True).to_parquet(minutes_dir / "pair_minutes.parquet", index=False)
    pd.concat(all_pair_opp, ignore_index=True).to_parquet(minutes_dir / "pair_opponent_minutes.parquet", index=False)

    # Also concatenate all spadl into one parquet for fast downstream load
    parts = [pd.read_parquet(p) for p in sorted(spadl_dir.glob("*.parquet"))]
    pd.concat(parts, ignore_index=True).to_parquet(out / "spadl_all.parquet", index=False)
    print(f"Wrote {len(parts)} matches, total actions = {sum(len(p) for p in parts)}")


if __name__ == "__main__":
    main()
