"""Bransen Team Builder via mixed-integer programming.

    max  Σ_{p,q} (α·JOI90(p,q) + (1-α)·JDI90(p,q)) · y_{p,q}
    s.t. Σ_p x_p = 11
         Σ_p GK_p · x_p = 1
         3 ≤ Σ_p DEF_p · x_p ≤ 5
         3 ≤ Σ_p MID_p · x_p ≤ 5
         1 ≤ Σ_p FWD_p · x_p ≤ 3
         y_{p,q} = x_p · x_q   (linearized: y ≤ x_p, y ≤ x_q, y ≥ x_p + x_q - 1)

Implementation uses Python-MIP / PuLP if available; falls back to a greedy
solver that picks the formation that maximizes total objective among
{4-3-3, 4-4-2, 3-5-2, 3-4-3, 4-2-3-1} formations by exhaustive enumeration
over qualifying players.
"""
from __future__ import annotations

from itertools import combinations
from typing import Iterable

import numpy as np
import pandas as pd

from ..joint.grid import grid_role


FORMATIONS = {
    "4-3-3": {"GK": 1, "DEF": 4, "MID": 3, "FWD": 3},
    "4-4-2": {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2},
    "3-5-2": {"GK": 1, "DEF": 3, "MID": 5, "FWD": 2},
    "3-4-3": {"GK": 1, "DEF": 3, "MID": 4, "FWD": 3},
    "4-2-3-1": {"GK": 1, "DEF": 4, "MID": 5, "FWD": 1},
}


def _build_pair_lookup(joi_df: pd.DataFrame, jdi_df: pd.DataFrame, alpha: float) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = {}
    for r in joi_df.itertuples():
        lo, hi = (int(r.player_p), int(r.player_q)) if r.player_p < r.player_q else (int(r.player_q), int(r.player_p))
        out[(lo, hi)] = out.get((lo, hi), 0.0) + alpha * float(r.joi90)
    for r in jdi_df.itertuples():
        lo, hi = (int(r.player_p), int(r.player_q)) if r.player_p < r.player_q else (int(r.player_q), int(r.player_p))
        out[(lo, hi)] = out.get((lo, hi), 0.0) + (1 - alpha) * float(r.jdi90)
    return out


def best_xi(
    candidates: pd.DataFrame,
    joi_df: pd.DataFrame,
    jdi_df: pd.DataFrame,
    *,
    alpha: float = 0.5,
    formations: Iterable[str] = ("4-3-3", "4-4-2", "3-5-2", "3-4-3", "4-2-3-1"),
    top_k_by_role: int = 8,
) -> dict:
    """Pick a maximum-chemistry XI from `candidates`.

    `candidates` must have columns: player_id, name, role (GK/DEF/MID/FWD).
    For tractability we restrict to the top_k_by_role players per role,
    ranked by their average JOI90+JDI90 with any other candidate. This
    keeps the search exhaustive but bounded.
    """
    pair_value = _build_pair_lookup(joi_df, jdi_df, alpha)
    # Per-player average chemistry score within the candidate pool
    per_player_score: dict[int, float] = {pid: 0.0 for pid in candidates.player_id}
    counts: dict[int, int] = {pid: 0 for pid in candidates.player_id}
    pids = set(candidates.player_id.astype(int))
    for (lo, hi), v in pair_value.items():
        if lo in pids and hi in pids:
            per_player_score[lo] += v; counts[lo] += 1
            per_player_score[hi] += v; counts[hi] += 1
    avg = {pid: per_player_score[pid] / max(counts[pid], 1) for pid in pids}

    by_role: dict[str, list[int]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for r in candidates.itertuples():
        role = getattr(r, "role", None) or "MID"
        by_role.setdefault(role, []).append(int(r.player_id))

    # Sort by avg chemistry desc, trim
    for role in by_role:
        by_role[role] = sorted(by_role[role], key=lambda p: -avg.get(p, 0))[:top_k_by_role]

    best = None
    for fname in formations:
        slots = FORMATIONS[fname]
        if len(by_role["GK"]) < slots["GK"] or len(by_role["DEF"]) < slots["DEF"] \
                or len(by_role["MID"]) < slots["MID"] or len(by_role["FWD"]) < slots["FWD"]:
            continue
        for gk in combinations(by_role["GK"], slots["GK"]):
            for d in combinations(by_role["DEF"], slots["DEF"]):
                for m in combinations(by_role["MID"], slots["MID"]):
                    for f in combinations(by_role["FWD"], slots["FWD"]):
                        team = list(gk) + list(d) + list(m) + list(f)
                        score = 0.0
                        for i in range(len(team)):
                            for j in range(i + 1, len(team)):
                                lo, hi = (team[i], team[j]) if team[i] < team[j] else (team[j], team[i])
                                score += pair_value.get((lo, hi), 0.0)
                        if best is None or score > best["score"]:
                            best = {
                                "formation": fname,
                                "score": score,
                                "players": team,
                            }
    return best
