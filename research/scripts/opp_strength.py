#!/usr/bin/env python3
"""Shared opponent-strength weighting + stage tagging for the WC2022 player boards.

WHY: players appeared in 3-7 games against wildly different opposition, so raw totals
favour deep runs and per-match flatters teams that played fewer/weaker games. Two controls,
used by every player-board generator (pass_selection, bwae, space_pobso):

  * STAGE — split group vs knockout (PFF ids 10502-10517 are the 16 knockout games).
    Group is the level field (every team plays exactly 3). Knockout = vs elite teams.
  * OPPONENT STRENGTH — weight each game's contribution by the opponent's FIFA-index
    2022 rating (fifa_multi_year.json) relative to the field average, so racking up a
    number against minnows is discounted and doing it against giants is rewarded.
    Coverage is partial (20/32 teams rated); unrated minnows floor just below the min.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_FIFA = _REPO / "research" / "site" / "data" / "fifa_multi_year.json"

# PFF knockout match ids: R16 (8) + QF (4) + SF (2) + 3rd-place & final (2) = 16.
KNOCKOUT_IDS = {str(m) for m in range(10502, 10518)}


def stage_of(mid) -> str:
    return "ko" if str(mid) in KNOCKOUT_IDS else "group"


def _norm(s: str) -> str:
    return (unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore")
            .decode().lower().strip())


# PFF <-> fifaindex name differences
_ALIAS = {"south korea": "korea republic", "korea republic": "south korea",
          "usa": "united states", "united states": "usa",
          "iran": "ir iran", "ir iran": "iran"}


def _load_ratings() -> dict:
    try:
        rows = json.load(open(_FIFA)).get("rows", [])
    except Exception:
        return {}
    return {_norm(r["team"]): float(r["overall"]) for r in rows
            if r.get("year") == 2022 and r.get("overall") is not None}


class OppStrength:
    """Opponent-strength weights, keyed by team NAME. weight(team) ~ 1.0 average,
    >1 for strong opponents, <1 for weak. Unrated teams floor just below the minimum."""

    def __init__(self):
        self.r = _load_ratings()
        vals = list(self.r.values())
        self.ref = sum(vals) / len(vals) if vals else 78.0
        self.floor = (min(vals) - 2.0) if vals else 66.0

    def rating(self, team: str) -> float:
        n = _norm(team)
        if n in self.r:
            return self.r[n]
        if n in _ALIAS and _ALIAS[n] in self.r:
            return self.r[_ALIAS[n]]
        return self.floor

    def weight(self, team: str) -> float:
        return self.rating(team) / self.ref


def per_stage_block(by_stage: dict) -> dict:
    """Given {stage: {"valw": opp-weighted sum, "valr": raw sum, "mids": set}}, return the
    board-ready per-stage block (incl. 'all') carrying BOTH the opponent-weighted and the raw
    total + per-match, so the board can toggle weighted vs not."""
    out = {}
    g, k = by_stage.get("group", {}), by_stage.get("ko", {})
    combos = {"group": g, "ko": k,
              "all": {"valw": g.get("valw", 0.0) + k.get("valw", 0.0),
                      "valr": g.get("valr", 0.0) + k.get("valr", 0.0),
                      "mids": (g.get("mids", set()) | k.get("mids", set()))}}
    for st, d in combos.items():
        m = len(d.get("mids", ()))
        w, r = d.get("valw", 0.0), d.get("valr", 0.0)
        out[st] = {"matches": m,
                   "total": round(w, 4), "per_match": round(w / m, 4) if m else 0.0,
                   "total_raw": round(r, 4), "per_match_raw": round(r / m, 4) if m else 0.0}
    return out
