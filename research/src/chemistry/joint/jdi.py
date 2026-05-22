"""Joint Defensive Impact (JDI).

Steps (Bransen):
1. Compute each player's per-match Actual Offensive Impact (OI):
       OI_m(p) = Σ VAEP(a) over offensive actions {pass, cross, dribble, take_on, shot}
2. Compute Expected OI for each player in each match using the player's
   *prior* matches in the dataset (Bayesian-shrunk to a positional prior
   when minutes played < 700).
3. For every opponent o that pair (p, q) faced, compute the responsibility
   share via the 5x5 position grid:
       RESP_m(p, o) = (1 / d_m(p, o)) normalized over each team's possible
       defenders so RESP sums to 1 across defenders of that opponent.
   RESP_m(p, q, o) = (RESP_m(p, o) + RESP_m(q, o)) / 2
4. JDI_m(p, q) = Σ_o (E[OI_o] - OI_o) * RESP_m(p, q, o) * mins(p,q,o)/90
5. JDI90 = Σ_m JDI_m * 90 / Σ_m mins_together
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from ..loaders.pff_spadl import INTERACTION_TYPES
from .grid import grid_distance, grid_role


def compute_oi_per_match(spadl_vaep: pd.DataFrame) -> pd.DataFrame:
    """Sum VAEP of offensive actions per (game, player)."""
    off = spadl_vaep[spadl_vaep.type_name.isin(INTERACTION_TYPES)]
    return (
        off.groupby(["game_id", "team_id", "team_name", "player_id", "player_name"], as_index=False)
        .agg(oi=("vaep_value", "sum"), n_actions=("vaep_value", "size"))
    )


def compute_expected_oi(
    oi_per_match: pd.DataFrame,
    lineups: pd.DataFrame,
    matches: pd.DataFrame,
    prior_minutes_floor: int = 700,
) -> pd.DataFrame:
    """For each (game, player), compute E[OI per 90] using prior matches only.

    Bayesian shrinkage with a per-position prior when minutes-played < 700.
    """
    # Sort matches chronologically
    if "date" in matches.columns:
        order = matches.sort_values("date")["game_id"].tolist()
    else:
        order = sorted(matches["game_id"].unique())
    rank = {gid: i for i, gid in enumerate(order)}
    oi = oi_per_match.copy()
    oi["order"] = oi.game_id.map(rank)
    oi = oi.sort_values(["player_id", "order"])

    ln = lineups[["game_id", "player_id", "on_seconds", "position"]].copy()
    ln["minutes"] = ln.on_seconds / 60.0
    oi = oi.merge(ln, on=["game_id", "player_id"], how="left")
    oi["minutes"] = oi.minutes.fillna(0)
    oi["oi_per90"] = oi.oi * 90.0 / oi.minutes.clip(lower=0.5)

    # Positional prior: average per90 across all matches by role
    oi["role"] = oi.position.map(grid_role)
    pos_prior = oi.groupby("role").oi_per90.mean().to_dict()

    # Compute expected OI per match using all prior matches in this dataset
    expected = []
    for pid, grp in oi.groupby("player_id", sort=False):
        grp = grp.sort_values("order").reset_index(drop=True)
        cumsum_oi = 0.0
        cumsum_min = 0.0
        for row in grp.itertuples():
            prior_per90 = (cumsum_oi * 90.0 / cumsum_min) if cumsum_min > 0 else None
            role_prior = pos_prior.get(row.role, 0.05)
            if prior_per90 is None:
                exp_per90 = role_prior
            else:
                w = min(cumsum_min / prior_minutes_floor, 1.0)
                exp_per90 = w * prior_per90 + (1 - w) * role_prior
            # Convert expected per90 to expected for this match's minutes
            exp_oi = exp_per90 * row.minutes / 90.0
            expected.append({
                "game_id": row.game_id,
                "player_id": row.player_id,
                "expected_oi": exp_oi,
                "actual_oi": row.oi,
                "minutes": row.minutes,
                "role": row.role,
            })
            cumsum_oi += row.oi
            cumsum_min += row.minutes
    return pd.DataFrame(expected)


def _mirror_position(pos: str | None) -> tuple[int, int]:
    """Map opponent position to *our* grid: mirror across the halfway line.
    Opponent's row 0 (their forwards) lines up with our row 4 (our defenders);
    columns flip too so their left wing attacks our right side.
    """
    from .grid import grid_cell
    r, c = grid_cell(pos)
    # Mirror row 0..4 to 4..0; GK row 5 → row 5 by convention (mirrored GK is GK).
    mirrored_row = (4 - r) if r <= 4 else 5
    mirrored_col = 4 - c
    return mirrored_row, mirrored_col


def _grid_distance_vs_opponent(my_pos: str | None, opp_pos: str | None) -> float:
    """Distance between *my* player position and an opponent position
    (after mirroring the opponent into our coordinate frame)."""
    import math
    from .grid import grid_cell
    a = grid_cell(my_pos)
    b = _mirror_position(opp_pos)
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _responsibility_per_opponent(
    pair_positions: dict[int, str],
    pair_team: str,
    opponent_id: int,
    opponent_pos: str,
    all_lineups_in_match: pd.DataFrame,
) -> dict[tuple[int, int], float]:
    """For an opponent o, compute the responsibility share that each
    unordered pair of pair_team players bears in stopping o."""
    team_players = all_lineups_in_match[all_lineups_in_match.team_id == pair_team]
    distances = {}
    for r in team_players.itertuples():
        d = _grid_distance_vs_opponent(r.position, opponent_pos)
        distances[r.player_id] = 1.0 / (d + 0.5)
    total = sum(distances.values()) or 1.0
    indiv = {pid: w / total for pid, w in distances.items()}
    out: dict[tuple[int, int], float] = {}
    pids = sorted(indiv.keys())
    for i, p in enumerate(pids):
        for q in pids[i + 1:]:
            out[(p, q)] = (indiv[p] + indiv[q]) / 2.0
    return out


def compute_jdi(
    spadl_vaep: pd.DataFrame,
    pair_opp_minutes: pd.DataFrame,
    lineups: pd.DataFrame,
    pair_minutes_df: pd.DataFrame,
    matches: pd.DataFrame,
) -> pd.DataFrame:
    """Compute JDI per pair (same team).

    Returns columns:
        team_id, player_p, name_p, player_q, name_q,
        minutes_together, jdi, jdi90.
    """
    oi_match = compute_oi_per_match(spadl_vaep)
    exp_oi = compute_expected_oi(oi_match, lineups, matches)
    exp_oi["delta"] = exp_oi.expected_oi - exp_oi.actual_oi  # positive => opp underperformed

    # Get player positions for grid mapping
    positions = lineups[["game_id", "player_id", "position"]].copy()
    positions = positions.dropna(subset=["position"])

    # For each match compute per-pair JDI by walking opponents
    pair_jdi: dict[tuple[int, int], float] = defaultdict(float)
    pair_mins: dict[tuple[int, int], float] = defaultdict(float)

    # Group pair_opp_minutes by game
    by_match_pairs = pair_opp_minutes.groupby("game_id")
    for gid, mdf in by_match_pairs:
        ln = lineups[lineups.game_id == gid][["player_id", "team_id", "position"]]
        ln = ln.dropna(subset=["position"])
        opp_positions = dict(zip(ln.player_id, ln.position))

        # Compute responsibility per opponent in this match
        resp_cache: dict[tuple[str, int], dict[tuple[int, int], float]] = {}
        # Pre-fetch delta_oi per opponent in this match
        delta_oi = exp_oi[exp_oi.game_id == gid].set_index("player_id")["delta"].to_dict()

        for row in mdf.itertuples():
            o = int(row.opponent)
            pair_team = row.pair_team
            opp_pos = opp_positions.get(o)
            if opp_pos is None:
                continue
            delta = delta_oi.get(o, 0.0)
            mins = float(row.minutes)
            cache_key = (pair_team, o)
            if cache_key not in resp_cache:
                resp_cache[cache_key] = _responsibility_per_opponent(
                    {}, pair_team, o, opp_pos, ln,
                )
            resp_for_opp = resp_cache[cache_key]
            p = int(row.player_p); q = int(row.player_q)
            lo, hi = (p, q) if p < q else (q, p)
            r_pq = resp_for_opp.get((lo, hi), 0.0)
            contribution = delta * r_pq * (mins / 90.0)
            pair_jdi[(lo, hi)] += contribution

    # Aggregate minutes together per pair
    mt = pair_minutes_df[pair_minutes_df.same_team].copy()
    mt["lo"] = mt[["player_p", "player_q"]].min(axis=1)
    mt["hi"] = mt[["player_p", "player_q"]].max(axis=1)
    agg = mt.groupby(["lo", "hi"], as_index=False).agg(
        minutes_together=("minutes_together", "sum"),
        team_id=("team_p", "first"),
        name_p=("name_p", "first"),
        name_q=("name_q", "first"),
    )

    rows = []
    for (lo, hi), jdi in pair_jdi.items():
        rows.append({"player_p": lo, "player_q": hi, "jdi": jdi})
    base = pd.DataFrame(rows)
    if base.empty:
        return pd.DataFrame(columns=["team_id", "player_p", "name_p", "player_q", "name_q",
                                      "minutes_together", "jdi", "jdi90"])
    merged = base.merge(agg, left_on=["player_p", "player_q"], right_on=["lo", "hi"], how="left").drop(columns=["lo", "hi"])
    merged["jdi90"] = merged.jdi * 90.0 / merged.minutes_together.clip(lower=0.01)
    merged = merged[[
        "team_id", "player_p", "name_p", "player_q", "name_q",
        "minutes_together", "jdi", "jdi90",
    ]]
    return merged.sort_values("jdi90", ascending=False).reset_index(drop=True)
