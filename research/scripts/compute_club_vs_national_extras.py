"""Compute extras for the Club vs National page.

Produces `research/site/data/club_vs_national_extras.json` with:

1. `per_stage_attack_defence` — per-WC22-stage league-average P_score and
   P_concede (does offence improve more than defence as the tournament
   progresses?).
2. `club_vs_wc22_scatter` — per-player club OI/90 vs WC22 OI/90 for every
   non-GK player with ≥120 min club minutes and ≥90 min WC22 minutes
   (regression-to-mean check).
3. `club_vs_wc22_correlation` — Pearson r and Spearman ρ of (club OI/90,
   WC22 OI/90).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "research" / "data"
SITE = REPO / "research" / "site" / "data"


STAGE_ORDER = ["Group", "R16", "QF", "SF", "Final/3rd"]


def stage_for(d: pd.Timestamp) -> str:
    """Map a WC22 match date to its knockout stage."""
    if d < pd.Timestamp("2022-12-03"):
        return "Group"
    if d < pd.Timestamp("2022-12-09"):
        return "R16"
    if d < pd.Timestamp("2022-12-13"):
        return "QF"
    if d < pd.Timestamp("2022-12-17"):
        return "SF"
    return "Final/3rd"


def main() -> None:
    matches = pd.read_parquet(DATA / "matches.parquet").copy()
    matches["date_dt"] = pd.to_datetime(matches.date)
    matches["stage"] = matches.date_dt.apply(stage_for)

    spadl = pd.read_parquet(DATA / "spadl_vaep.parquet")
    spadl = spadl.merge(matches[["game_id", "stage"]], on="game_id", how="left")

    overall = (
        spadl.groupby("stage")
        .agg(
            p_score=("p_score", "mean"),
            p_concede=("p_concede", "mean"),
            n_actions=("action_id", "count"),
            n_teams=("team_id", "nunique"),
        )
        .reindex(STAGE_ORDER)
        .reset_index()
    )

    stage_rows = [
        {
            "stage": r.stage,
            "avg_p_score": float(r.p_score),
            "avg_p_concede": float(r.p_concede),
            "n_actions": int(r.n_actions),
            "n_teams": int(r.n_teams),
        }
        for _, r in overall.iterrows()
    ]

    # ------- club vs WC22 scatter / correlation -------
    cc = pd.read_parquet(DATA / "cross_context.parquet")
    wc = (
        cc[cc.competition == "wc_2022_pff"][["pff_player_id", "oi_per90", "minutes"]]
        .rename(columns={"oi_per90": "wc22_oi_per90", "minutes": "wc22_min"})
    )
    others = cc[~cc.competition.isin(["wc_2022_pff", "wc_2022_sb"])]
    # For each player, pick the *highest-minutes* other context as their club proxy.
    others = (
        others.sort_values("minutes", ascending=False)
        .drop_duplicates("pff_player_id")[["pff_player_id", "competition", "oi_per90", "minutes"]]
    )
    both = others.merge(wc, on="pff_player_id")
    both = both[(both.minutes >= 120) & (both.wc22_min >= 90)]

    lineups = pd.read_parquet(DATA / "minutes" / "lineups.parquet")
    nm = (
        lineups.drop_duplicates("player_id")
        .set_index("player_id")[["player_name", "team_name", "position"]]
        .to_dict("index")
    )
    both["player_name"] = both.pff_player_id.map(lambda x: (nm.get(x) or {}).get("player_name"))
    both["team_name"] = both.pff_player_id.map(lambda x: (nm.get(x) or {}).get("team_name"))
    both["position"] = both.pff_player_id.map(lambda x: (nm.get(x) or {}).get("position"))
    both = both[both.position != "GK"]

    pearson = float(both.oi_per90.corr(both.wc22_oi_per90))
    spearman = float(both.oi_per90.corr(both.wc22_oi_per90, method="spearman"))

    scatter = [
        {
            "pff_player_id": int(r.pff_player_id),
            "player_name": r.player_name,
            "team_name": r.team_name,
            "position": r.position,
            "club_competition": r.competition,
            "club_oi_per90": float(r.oi_per90),
            "club_min": float(r.minutes),
            "wc22_oi_per90": float(r.wc22_oi_per90),
            "wc22_min": float(r.wc22_min),
        }
        for _, r in both.iterrows()
    ]

    out = {
        "per_stage_attack_defence": stage_rows,
        "club_vs_wc22_scatter": scatter,
        "club_vs_wc22_correlation": {
            "pearson_r": pearson,
            "spearman_rho": spearman,
            "n": len(scatter),
        },
    }
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "club_vs_national_extras.json").write_text(json.dumps(out, indent=2))
    print(f"wrote club_vs_national_extras.json (stages={len(stage_rows)}, scatter={len(scatter)}, r={pearson:.3f})")


if __name__ == "__main__":
    main()
