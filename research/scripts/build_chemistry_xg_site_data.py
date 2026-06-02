"""Build research/site/data/chemistry_xg.json — paired offense/defense added-variable
points + partial-r + bootstrap CIs grounding chemistry in expected goals over/under expected.

    PYTHONPATH=src uv run python research/scripts/build_chemistry_xg_site_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))

from xg.site_data import CONTROLS, build_team_xg_table, residualize  # noqa: E402

PARQUET = REPO / "research/data/xg_grounding_team_match.parquet"
CHEM = REPO / "research/site/data/team_chemistry_vs_paper.json"
OUT = REPO / "research/site/data/chemistry_xg.json"


def added_variable(team, chem_col, outcome_col, *, flip_outcome):
    """Residualize chem and outcome on CONTROLS; return (r, ci90, points-DataFrame)."""
    sub = team.dropna(subset=[chem_col, outcome_col, *CONTROLS]).copy()
    rx = residualize(sub, chem_col, CONTROLS)
    ry = residualize(sub, outcome_col, CONTROLS)
    if flip_outcome:
        ry = -ry
    rxv, ryv = rx.to_numpy(), ry.to_numpy()
    r = float(np.corrcoef(rxv, ryv)[0, 1])
    rng = np.random.default_rng(0)
    n = len(rxv)
    boots = [np.corrcoef(rxv[s], ryv[s])[0, 1]
             for s in (rng.integers(0, n, n) for _ in range(2000))]
    lo, hi = (float(v) for v in np.percentile(boots, [5, 95]))
    sub = sub.assign(_chem_adj=rxv, _out_adj=ryv)
    return r, [lo, hi], sub


def main() -> None:
    team = build_team_xg_table(str(PARQUET), str(CHEM))
    r_def, ci_def, dsub = added_variable(team, "n_strong_def", "xga_pm", flip_outcome=True)
    r_off, ci_off, osub = added_variable(team, "mean_aw_joi90_all", "xg_for_pm", flip_outcome=False)

    by_id: dict[str, dict] = {}
    for _, row in dsub.iterrows():
        by_id[row["team_id"]] = {
            "team_id": row["team_id"], "team_name": row["team_name"],
            "is_semifinalist": bool(row["is_semifinalist"]),
            "def_chem_adj": round(float(row["_chem_adj"]), 4),
            "xg_prevented_over_expected": round(float(row["_out_adj"]), 4),
        }
    for _, row in osub.iterrows():
        by_id.setdefault(row["team_id"], {
            "team_id": row["team_id"], "team_name": row["team_name"],
            "is_semifinalist": bool(row["is_semifinalist"])})
        by_id[row["team_id"]]["off_chem_adj"] = round(float(row["_chem_adj"]), 4)
        by_id[row["team_id"]]["xg_added_over_expected"] = round(float(row["_out_adj"]), 4)

    payload = {
        "meta": {
            "n_teams": int(len(by_id)),
            "controls": "FIFA-23 Overall + mean caps + games played + opponent FIFA",
            "defense": {"partial_r": round(r_def, 3), "ci90": [round(ci_def[0], 3), round(ci_def[1], 3)]},
            "offense": {"partial_r": round(r_off, 3), "ci90": [round(ci_off[0], 3), round(ci_off[1], 3)]},
        },
        "teams": sorted(by_id.values(), key=lambda t: t["team_name"]),
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT}  n={payload['meta']['n_teams']}  "
          f"def r={r_def:+.3f} {ci_def}  off r={r_off:+.3f} {ci_off}")


if __name__ == "__main__":
    main()
