"""Download + convert StatsBomb open-data competitions to SPADL parquets.

Outputs:
    research/data/statsbomb/{label}.parquet
        SPADL for the whole competition (one row per action).
    research/data/statsbomb/matches_{label}.parquet
        One row per match with date, teams, score.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))

from chemistry.loaders.statsbomb import (CompetitionRequest, download_competition,
                                          fetch_matches)


TARGETS = [
    # Small first (~50 matches each) so the easy wins land quickly
    CompetitionRequest(43, 106, "wc_2022_sb"),         # WC22 cross-validation
    CompetitionRequest(55, 282, "euro_2024"),          # European WC22 → 18-month follow-up
    CompetitionRequest(223, 282, "copa_america_2024"), # S. American WC22 → 18-month follow-up
    # Big club sources last (380 matches each)
    CompetitionRequest(7, 235, "ligue1_22_23"),        # Club data spanning WC22
    CompetitionRequest(9, 281, "bundesliga_23_24"),    # Post-WC22 club data for German players
]


def main() -> None:
    out_dir = REPO / "research" / "data" / "statsbomb"
    out_dir.mkdir(parents=True, exist_ok=True)

    for req in TARGETS:
        parq = out_dir / f"{req.label}.parquet"
        meta_parq = out_dir / f"matches_{req.label}.parquet"
        if parq.exists() and meta_parq.exists():
            print(f"[skip] {req.label} already on disk")
            continue
        try:
            matches = fetch_matches(req.competition_id, req.season_id)
        except Exception as e:
            print(f"[skip] {req.label}: matches.json failed: {e}")
            continue
        pd.DataFrame([{
            "match_id": m["match_id"],
            "match_date": m.get("match_date"),
            "competition_id": req.competition_id,
            "competition_label": req.label,
            "home_team": (m.get("home_team") or {}).get("home_team_name"),
            "away_team": (m.get("away_team") or {}).get("away_team_name"),
            "home_score": m.get("home_score"),
            "away_score": m.get("away_score"),
            "match_week": m.get("match_week"),
        } for m in matches]).to_parquet(meta_parq, index=False)

        frames = download_competition(req)
        if not frames:
            print(f"[skip] {req.label}: zero converted matches")
            continue
        df = pd.concat(frames, ignore_index=True)
        df.to_parquet(parq, index=False)
        print(f"[ok] {req.label}: {len(df)} actions across {df.game_id.nunique()} matches → {parq}")


if __name__ == "__main__":
    main()
