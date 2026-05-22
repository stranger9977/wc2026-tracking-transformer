"""Joint Offensive Impact (JOI) per Bransen & Van Haaren 2020.

For each match m and pair (p, q) we find consecutive same-team action pairs
where one of {p, q} performed action a_i and the other performed a_{i+1},
restricted to action types {pass, cross, dribble, take_on, shot}.

    JOI_m(p, q) = Σ_k VAEP(I^m_k(p, q)) + Σ_l VAEP(I^m_l(q, p))
                = Σ over interactions of [VAEP(a_i) + VAEP(a_{i+1})]

We aggregate across matches and normalize by minutes-together (JOI90).
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from ..loaders.pff_spadl import INTERACTION_TYPES


def compute_joi(spadl_vaep: pd.DataFrame, pair_minutes_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-pair JOI (sum) and JOI90 (per 90 min together).

    Returns columns:
        team_id, player_p, name_p, player_q, name_q,
        minutes_together, n_interactions,
        joi (raw sum), joi90 (per 90), p_initiates_frac (share of p starting interactions)
    """
    # Per-match interaction sums into a dict keyed by (game_id, p, q) with p<q.
    pair_sum: dict[tuple[int, int, int], float] = defaultdict(float)
    pair_count: dict[tuple[int, int, int], int] = defaultdict(int)
    p_first: dict[tuple[int, int, int], int] = defaultdict(int)

    for game_id, df in spadl_vaep.groupby("game_id", sort=False):
        df = df.sort_values(["period_id", "time_seconds"]).reset_index(drop=True)
        types = df["type_name"].to_numpy()
        teams = df["team_id"].to_numpy()
        players = df["player_id"].to_numpy()
        vaeps = df["vaep_value"].to_numpy()
        n = len(df)
        for i in range(n - 1):
            t1, t2 = types[i], types[i + 1]
            if t1 not in INTERACTION_TYPES or t2 not in INTERACTION_TYPES:
                continue
            if teams[i] != teams[i + 1]:
                continue
            p1, p2 = players[i], players[i + 1]
            if p1 == p2:
                continue  # same player; not a pair
            v_sum = float(vaeps[i] + vaeps[i + 1])
            # Order pair canonical: lo, hi
            lo, hi = (int(p1), int(p2)) if p1 < p2 else (int(p2), int(p1))
            key = (int(game_id), lo, hi)
            pair_sum[key] += v_sum
            pair_count[key] += 1
            if p1 < p2:
                p_first[key] += 1  # canonical p initiates

    # Aggregate across matches
    agg_sum: dict[tuple[int, int], float] = defaultdict(float)
    agg_count: dict[tuple[int, int], int] = defaultdict(int)
    agg_first: dict[tuple[int, int], int] = defaultdict(int)
    for (gid, p, q), v in pair_sum.items():
        agg_sum[(p, q)] += v
        agg_count[(p, q)] += pair_count[(gid, p, q)]
        agg_first[(p, q)] += p_first[(gid, p, q)]

    # Minutes-together across matches
    mt = pair_minutes_df.copy()
    mt["player_lo"] = mt[["player_p", "player_q"]].min(axis=1)
    mt["player_hi"] = mt[["player_p", "player_q"]].max(axis=1)
    mins_agg = (
        mt[mt.same_team]
        .groupby(["player_lo", "player_hi"], as_index=False)
        .agg(minutes_together=("minutes_together", "sum"),
             team_id=("team_p", "first"),
             name_p=("name_p", "first"),
             name_q=("name_q", "first"))
    )

    rows = []
    for (lo, hi), v in agg_sum.items():
        row = {"player_p": lo, "player_q": hi, "joi": v, "n_interactions": agg_count[(lo, hi)]}
        rows.append(row)
    base = pd.DataFrame(rows)
    merged = base.merge(mins_agg, left_on=["player_p", "player_q"], right_on=["player_lo", "player_hi"], how="left")
    merged = merged.drop(columns=["player_lo", "player_hi"])
    merged["joi90"] = merged["joi"] * 90.0 / merged["minutes_together"].clip(lower=0.01)
    merged["p_initiates_frac"] = [
        agg_first[(r.player_p, r.player_q)] / max(r.n_interactions, 1)
        for r in merged.itertuples()
    ]
    merged = merged[[
        "team_id", "player_p", "name_p", "player_q", "name_q",
        "minutes_together", "n_interactions", "joi", "joi90", "p_initiates_frac",
    ]]
    return merged.sort_values("joi90", ascending=False).reset_index(drop=True)
