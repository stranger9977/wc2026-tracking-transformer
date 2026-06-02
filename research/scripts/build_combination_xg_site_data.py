"""Build research/site/data/combination_xg.json — GIVE-AND-GO RATE (final-third one-twos
per game) vs xG-for, a team leaderboard, and its link to squad shared history.

The offensive signal that survives the talent controls (partial +0.39 vs xG, stable across
every control spec, jackknife-robust) where four other metric families failed — and that the
next-receiver model itself recognises (it anticipates the give-back pass). Shared history is
its source: teams whose players have played together more play more give-and-gos (+0.57
controlling talent). Honest caveats in meta. See research/notes/offense_xg_search_findings.md.

    PYTHONPATH=src uv run python research/scripts/build_combination_xg_site_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LinearRegression

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))

from xg.site_data import CONTROLS, build_team_xg_table, residualize  # noqa: E402

PARQUET = REPO / "research/data/xg_grounding_team_match.parquet"
CHEM = REPO / "research/site/data/team_chemistry_vs_paper.json"
COMBO = REPO / "research/data/combo_metrics.parquet"
OUT = REPO / "research/site/data/combination_xg.json"
HIST_FIELD = "mean_prior_per_known_pair"   # avg prior minutes a pair has played together


def _partial(df, y, x, ctl):
    s = df.dropna(subset=[y, x, *ctl])
    C = s[ctl].to_numpy(float)
    ry = s[y].to_numpy(float) - LinearRegression().fit(C, s[y]).predict(C)
    rx = s[x].to_numpy(float) - LinearRegression().fit(C, s[x]).predict(C)
    return float(np.corrcoef(rx, ry)[0, 1])


def main() -> None:
    team = build_team_xg_table(str(PARQUET), str(CHEM))
    team["team_id"] = team.team_id.astype(str)
    combo = pd.read_parquet(COMBO)
    combo["team_id"] = combo.team_id.astype(str)
    team = team.merge(combo[["team_id", "n_combo_f3"]], on="team_id", how="left")
    team["ggr"] = team["n_combo_f3"] / team["games"]   # give-and-go rate (per game)

    chem = pd.DataFrame(json.loads(CHEM.read_text()))
    chem["team_id"] = chem["team_id"].astype(str)
    chem[HIST_FIELD] = pd.to_numeric(chem[HIST_FIELD], errors="coerce")
    team = team.merge(chem[["team_id", HIST_FIELD]], on="team_id", how="left")
    team["shared_history"] = team[HIST_FIELD]

    # give-and-go rate vs xG-for (added-variable, talent + schedule adjusted)
    sub = team.dropna(subset=["ggr", "xg_for_pm", *CONTROLS]).copy()
    rx = residualize(sub, "ggr", CONTROLS)
    ry = residualize(sub, "xg_for_pm", CONTROLS)
    rxv, ryv = rx.to_numpy(), ry.to_numpy()
    r = float(np.corrcoef(rxv, ryv)[0, 1])
    rng = np.random.default_rng(0)
    n = len(rxv)
    boots = [np.corrcoef(rxv[s], ryv[s])[0, 1] for s in (rng.integers(0, n, n) for _ in range(2000))]
    lo, hi = (float(v) for v in np.percentile(boots, [5, 95]))
    sub = sub.assign(_x=rxv, _y=ryv)

    # one-two rate vs shared history (raw + talent-adjusted), on the analyzed set
    hist_rho = float(spearmanr(sub["ggr"], sub["shared_history"], nan_policy="omit").correlation)
    hist_partial = _partial(sub, "ggr", "shared_history", ["overall", "mean_caps"])

    # restrict to the analyzed set (teams with talent controls) so the scatter, leaderboard
    # and history chart all use the same n=29 teams
    teams = []
    for _, row in sub.iterrows():
        teams.append({
            "team_id": row.team_id, "team_name": row.team_name,
            "is_semifinalist": bool(row.is_semifinalist),
            "ggr_per_game": round(float(row.ggr), 1),
            "n_combo_f3": int(row.n_combo_f3),
            "shared_history": (None if pd.isna(row.shared_history) else round(float(row.shared_history), 1)),
            "combo_chem_adj": round(float(row._x), 4),
            "xg_added_over_expected": round(float(row._y), 4),
        })
    leaderboard = sorted(teams, key=lambda t: -t["ggr_per_game"])

    payload = {
        "meta": {
            "n_teams": int(sub.shape[0]),
            "metric": "final-third one-twos per game",
            "partial_r": round(r, 3),
            "ci90": [round(lo, 3), round(hi, 3)],
            "family_wise_p": 0.18,
            "goals_partial": 0.02,
            "controls": "FIFA-23 Overall + mean caps + games + opponent FIFA",
            "model_giveback_acc": 0.834,
            "model_overall_acc": 0.727,
            "nearest_baseline_acc": 0.672,
            "history_rho": round(hist_rho, 3),
            "history_partial": round(hist_partial, 3),
            "history_label": "avg prior minutes a pair has played together",
        },
        "teams": teams,
        "leaderboard": leaderboard,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT}  n={payload['meta']['n_teams']}  xG partial={r:+.3f} ci=[{lo:+.2f},{hi:+.2f}]")
    print(f"shared-history: rho={hist_rho:+.2f}  partial|talent={hist_partial:+.2f}")
    print("leaderboard top6: " + ", ".join(f"{t['team_name']}({t['ggr_per_game']})" for t in leaderboard[:6]))


if __name__ == "__main__":
    main()
