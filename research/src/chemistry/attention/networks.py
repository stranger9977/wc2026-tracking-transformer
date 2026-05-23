"""Attention-based chemistry network analysis.

Takes per-(game, pair) attention totals and produces:
- Per-team aggregated pair-attention.
- Per-pair "attention chemistry" score normalized by minutes-together.
- Network plots: nodes = players (positioned by 5×5 grid), edges = top-K
  attention links.

The output is meant to sit alongside JOI / JDI on the site as a third
chemistry signal — one that incorporates off-ball positional information
because the transformer sees all 22 players.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..joint.grid import grid_cell


def aggregate_team_attention(
    attention_chemistry: pd.DataFrame,
    pair_minutes: pd.DataFrame,
    lineups: pd.DataFrame,
    *,
    min_minutes: float = 60.0,
) -> pd.DataFrame:
    """Sum across matches per pair, then normalize by minutes-together (per 90).

    Returns columns: team_id, player_p, name_p, player_q, name_q,
                     minutes_together, attention_total, attention_per90.
    """
    if attention_chemistry.empty:
        return pd.DataFrame()
    # Same-team only
    df = attention_chemistry[attention_chemistry.same_team].copy()
    df["player_lo"] = df[["player_p", "player_q"]].min(axis=1)
    df["player_hi"] = df[["player_p", "player_q"]].max(axis=1)
    agg = df.groupby(["player_lo", "player_hi"], as_index=False).agg(
        attention_total=("pair_attention", "sum"),
        team_id=("team_id", "first"),
        name_p=("name_p", "first"),
        name_q=("name_q", "first"),
    )

    pm = pair_minutes[pair_minutes.same_team].copy()
    pm["lo"] = pm[["player_p", "player_q"]].min(axis=1)
    pm["hi"] = pm[["player_p", "player_q"]].max(axis=1)
    pm_agg = pm.groupby(["lo", "hi"], as_index=False).minutes_together.sum()
    agg = agg.merge(pm_agg, left_on=["player_lo", "player_hi"], right_on=["lo", "hi"], how="left")
    agg = agg.drop(columns=["lo", "hi"]).rename(columns={"player_lo": "player_p", "player_hi": "player_q"})
    agg["minutes_together"] = agg.minutes_together.fillna(0)
    agg["attention_per90"] = agg.attention_total * 90.0 / agg.minutes_together.clip(lower=0.01)
    agg = agg[agg.minutes_together >= min_minutes].copy()
    return agg.sort_values("attention_per90", ascending=False).reset_index(drop=True)


def per_team_pair_table(agg: pd.DataFrame, lineups: pd.DataFrame,
                        team_id: str) -> pd.DataFrame:
    """Return the per-pair attention table for one team, sorted desc."""
    if agg.empty:
        return pd.DataFrame()
    team = agg[agg.team_id == team_id].copy()
    return team.sort_values("attention_per90", ascending=False).reset_index(drop=True)
