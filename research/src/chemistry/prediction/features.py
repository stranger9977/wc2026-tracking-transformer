"""Player and pair feature vectors for chemistry prediction.

Bransen used: age, position, height, weight, nationality, region/subregion,
mother tongue, physical perf indicators, 22 player-role scores. The PFF
WC22 data only gives us a subset (age, height, position group, nationality
via team_name). We work with that — enough to demonstrate the modeling
pattern; if richer player metadata is added later, it slots straight in.

Pair feature vector:
    - age_p, age_q, age_diff, age_max
    - height_p, height_q, height_diff
    - role_p_one_hot (GK/DEF/MID/FWD), role_q_one_hot
    - same_role (bool)
    - grid_distance (Bransen 5x5 grid)
    - same_team (always True for chemistry pairs; we filter)
    - same_nationality (always True for WC pairs — kept for code path parity)
    - prior_matches_together (in this dataset, before the current season)
    - minutes_together_log
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ..joint.grid import grid_cell, grid_distance, grid_role

ROLES = ["GK", "DEF", "MID", "FWD"]


def _age_years(dob: str, ref_date: str = "2022-11-20") -> float:
    try:
        d = datetime.fromisoformat(dob)
        r = datetime.fromisoformat(ref_date)
        return (r - d).days / 365.25
    except Exception:
        return float("nan")


def load_player_meta(players_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(players_csv)
    df["player_id"] = df.id.astype(int)
    df["age"] = df.dob.fillna("").map(_age_years)
    df["height_cm"] = pd.to_numeric(df.height, errors="coerce")
    df["coarse_pos"] = df.positionGroupType.fillna("M")
    df["coarse_role"] = df.coarse_pos.map({
        "GK": "GK", "D": "DEF", "M": "MID", "F": "FWD",
        "LB": "DEF", "RB": "DEF", "LCB": "DEF", "RCB": "DEF",
        "CM": "MID", "DM": "MID", "LW": "FWD", "RW": "FWD", "CF": "FWD",
    }).fillna("MID")
    # Dedupe — players.csv has duplicate entries per player
    df = df.drop_duplicates(subset=["player_id"], keep="first")
    return df[["player_id", "age", "height_cm", "coarse_pos", "coarse_role", "nickname"]]


def build_pair_features(
    joi: pd.DataFrame, jdi: pd.DataFrame,
    pair_minutes: pd.DataFrame,
    lineups: pd.DataFrame, matches: pd.DataFrame,
    players_meta: pd.DataFrame,
    min_minutes: float = 60.0,
) -> pd.DataFrame:
    """Join JOI/JDI labels with per-pair features.

    Filters to same-team pairs with >= min_minutes together.
    """
    # Determine pair team and per-match position via lineup (use *last* known position)
    pos_lookup = (
        lineups.dropna(subset=["position"])
        .sort_values("game_id")
        .groupby("player_id")
        .position.last()
        .to_dict()
    )
    # Prior matches together: count of matches both players appeared in across the dataset
    pmin = pair_minutes[pair_minutes.same_team]
    pair_match_count = (
        pmin.groupby(["player_p", "player_q"])
        .agg(matches_together=("game_id", "nunique"))
        .reset_index()
    )

    pm_team = pmin.groupby(["player_p", "player_q"], as_index=False).agg(
        minutes_together=("minutes_together", "sum"),
        team_id=("team_p", "first"),
        name_p=("name_p", "first"),
        name_q=("name_q", "first"),
    )
    # Canonicalize lo<hi
    pm_team["lo"] = pm_team[["player_p", "player_q"]].min(axis=1)
    pm_team["hi"] = pm_team[["player_p", "player_q"]].max(axis=1)
    pm_team = pm_team.drop(columns=["player_p", "player_q"]).rename(columns={"lo": "player_p", "hi": "player_q"})

    base = pm_team.merge(pair_match_count, left_on=["player_p", "player_q"], right_on=["player_p", "player_q"], how="left")
    base = base[base.minutes_together >= min_minutes].copy()

    # Attach player meta
    meta = players_meta.set_index("player_id")
    def get(pid, field, default=np.nan):
        return meta[field].get(pid, default) if pid in meta.index else default

    base["age_p"] = base.player_p.map(lambda x: get(x, "age"))
    base["age_q"] = base.player_q.map(lambda x: get(x, "age"))
    base["height_p"] = base.player_p.map(lambda x: get(x, "height_cm"))
    base["height_q"] = base.player_q.map(lambda x: get(x, "height_cm"))
    base["pos_p"] = base.player_p.map(lambda x: pos_lookup.get(x))
    base["pos_q"] = base.player_q.map(lambda x: pos_lookup.get(x))
    base["role_p"] = base.pos_p.map(grid_role)
    base["role_q"] = base.pos_q.map(grid_role)
    base["age_diff"] = (base.age_p - base.age_q).abs()
    base["age_max"] = base[["age_p", "age_q"]].max(axis=1)
    base["height_diff"] = (base.height_p - base.height_q).abs()
    base["grid_dist"] = [
        grid_distance(pp, qq) for pp, qq in zip(base.pos_p, base.pos_q)
    ]
    base["same_role"] = (base.role_p == base.role_q).astype(int)
    base["minutes_together_log"] = np.log1p(base.minutes_together)

    for r in ROLES:
        base[f"role_p_{r}"] = (base.role_p == r).astype(int)
        base[f"role_q_{r}"] = (base.role_q == r).astype(int)

    # Merge labels
    j = joi.copy()
    j["lo"] = j[["player_p", "player_q"]].min(axis=1)
    j["hi"] = j[["player_p", "player_q"]].max(axis=1)
    j_min = j[["lo", "hi", "joi", "joi90"]].rename(columns={"lo": "player_p", "hi": "player_q"})
    d = jdi.copy()
    d["lo"] = d[["player_p", "player_q"]].min(axis=1)
    d["hi"] = d[["player_p", "player_q"]].max(axis=1)
    d_min = d[["lo", "hi", "jdi", "jdi90"]].rename(columns={"lo": "player_p", "hi": "player_q"})

    out = base.merge(j_min, on=["player_p", "player_q"], how="left")
    out = out.merge(d_min, on=["player_p", "player_q"], how="left")
    out.joi = out.joi.fillna(0.0)
    out.joi90 = out.joi90.fillna(0.0)
    out.jdi = out.jdi.fillna(0.0)
    out.jdi90 = out.jdi90.fillna(0.0)
    return out


def feature_columns() -> list[str]:
    cols = [
        "age_p", "age_q", "age_diff", "age_max",
        "height_p", "height_q", "height_diff",
        "grid_dist", "same_role", "matches_together", "minutes_together_log",
    ]
    for r in ROLES:
        cols.append(f"role_p_{r}")
        cols.append(f"role_q_{r}")
    return cols
