"""Per-player tournament form analysis: actual OI vs expected OI.

This is our proxy for the user's "club vs national" framing. We can't see
players' club seasons in this dataset, but we *can* see how each player's
per-match offensive impact (OI) drifts from their own tournament baseline.
Players whose actual OI runs persistently below their expected OI from
prior matches are candidates for chemistry-driven underperformance.

Outputs:
    site/data/player_form.json  — per-player rows + per-(player, match) detail
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    site_data = root / "site" / "data"

    exp = pd.read_parquet(data / "expected_oi.parquet")
    matches = pd.read_parquet(data / "matches.parquet")
    lineups = pd.read_parquet(data / "minutes" / "lineups.parquet")

    # Attach team / opponent context
    lineup_lookup = (
        lineups.drop_duplicates(["game_id", "player_id"])
        [["game_id", "player_id", "team_id", "team_name", "player_name", "position"]]
        .set_index(["game_id", "player_id"])
    )
    exp = exp.join(lineup_lookup, on=["game_id", "player_id"])
    exp["delta"] = exp.actual_oi - exp.expected_oi  # positive => over-performed
    exp["delta_per90"] = exp.delta * 90.0 / exp.minutes.clip(lower=1.0)

    # Most-common per-player position (PFF code like LCB, CM, CF)
    pos_mode = (
        lineups.dropna(subset=["position"]).groupby("player_id").position
        .agg(lambda s: s.value_counts().index[0]).to_dict()
    )
    exp["position"] = exp.player_id.map(pos_mode)

    # Per-player aggregates (only count matches with > 30 min)
    pp = exp[exp.minutes >= 30].copy()
    agg = (
        pp.groupby(["player_id", "player_name", "team_id", "team_name", "role", "position"],
                   as_index=False, dropna=False)
        .agg(
            n_matches=("game_id", "nunique"),
            total_minutes=("minutes", "sum"),
            actual_oi_total=("actual_oi", "sum"),
            expected_oi_total=("expected_oi", "sum"),
            mean_delta_per90=("delta_per90", "mean"),
        )
    )
    agg["delta_total"] = agg.actual_oi_total - agg.expected_oi_total
    agg["delta_per90"] = agg.delta_total * 90.0 / agg.total_minutes.clip(lower=1.0)
    agg = agg[agg.n_matches >= 2].sort_values("delta_per90", ascending=False)

    out = {
        "over_performers": agg.head(15).to_dict(orient="records"),
        "under_performers": agg.tail(15).sort_values("delta_per90").to_dict(orient="records"),
        "all_players": agg.to_dict(orient="records"),
    }
    site_data.mkdir(parents=True, exist_ok=True)
    (site_data / "player_form.json").write_text(json.dumps(out, default=float, indent=2))
    print(f"player_form.json: {len(agg)} players")
    print("\nTop 5 over-performers:")
    print(agg.head(5)[["player_name", "team_name", "n_matches", "total_minutes", "delta_per90"]].to_string(index=False))
    print("\nTop 5 under-performers:")
    print(agg.tail(5)[["player_name", "team_name", "n_matches", "total_minutes", "delta_per90"]].to_string(index=False))


if __name__ == "__main__":
    main()
