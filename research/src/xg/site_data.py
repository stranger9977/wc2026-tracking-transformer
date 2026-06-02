"""Assemble the per-team xG-vs-chemistry table and residualize for the site panel."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

CONTROLS = ["overall", "mean_caps", "games", "opp_fifa"]


def residualize(frame: pd.DataFrame, col: str, controls: list[str]) -> pd.Series:
    """OLS residual of ``col`` on ``controls``, over rows where all are present.

    Returns a Series indexed by the surviving rows of ``frame``.
    """
    sub = frame.dropna(subset=[col, *controls])
    X = sub[list(controls)].to_numpy(dtype=float)
    y = sub[col].to_numpy(dtype=float)
    pred = LinearRegression().fit(X, y).predict(X)
    return pd.Series(y - pred, index=sub.index)


def build_team_xg_table(parquet_path: str, chem_json_path: str) -> pd.DataFrame:
    """One row per team: games, per-match xG-for/against, opponent FIFA, chemistry, stage."""
    df = pd.read_parquet(parquet_path)
    df["team_id"] = df["team_id"].astype(str)

    chem = pd.DataFrame(json.loads(Path(chem_json_path).read_text()))
    chem["team_id"] = chem["team_id"].astype(str)
    for c in ["overall", "mean_caps", "n_strong_def", "mean_aw_joi90_all", "stage_int"]:
        chem[c] = pd.to_numeric(chem.get(c), errors="coerce")

    fifa = chem.set_index("team_id")["overall"].to_dict()
    opp: dict[str, list] = {}
    for _, g in df.groupby("game_id"):
        ids = list(g["team_id"])
        if len(ids) == 2:
            opp.setdefault(ids[0], []).append(fifa.get(ids[1]))
            opp.setdefault(ids[1], []).append(fifa.get(ids[0]))
    opp_fifa = {t: (np.nanmean(v) if len(v) else np.nan) for t, v in opp.items()}

    team = (
        df.groupby(["team_id", "team_name"])
        .agg(games=("game_id", "nunique"),
             xg_for=("sb_xg_for", "sum"),
             xg_against=("sb_xg_against", "sum"))
        .reset_index()
    )
    team["xg_for_pm"] = team["xg_for"] / team["games"]
    team["xga_pm"] = team["xg_against"] / team["games"]
    team["opp_fifa"] = team["team_id"].map(opp_fifa)
    team = team.merge(
        chem[["team_id", "overall", "mean_caps", "n_strong_def", "mean_aw_joi90_all", "stage_int"]],
        on="team_id", how="left",
    )
    team["is_semifinalist"] = team["stage_int"] >= 6
    return team
