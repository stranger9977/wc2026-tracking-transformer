#!/usr/bin/env python3
"""Build finishing_2026.json — live WC2026 finishing (npG - npxG), the 2026 companion
to our WC2022 finishing board.

Source: The Analyst / Opta live World Cup stats feed
(dataviz.theanalyst.com/project-data/soccer/<tmcl>/player-stats.json, the data the
theanalyst.com/competition/fifa-world-cup/stats page renders). We slim it to the
non-penalty finishing fields and keep a copy in research/data/analyst_src/ for repro.

Metric mirrors the 2022 board exactly: non-penalty goals minus non-penalty xG.
Penalties excluded; gated at a minimum xG so a one-shot fluke doesn't top the board.
Opta's xG model differs slightly from StatsBomb's (the 2022 board's source), so read
the two boards as the same idea across two tournaments, not as one continuous scale.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "analyst_src" / "wc2026_finishing_src.json"
OUT = ROOT / "site" / "data" / "finishing_2026.json"

MIN_XG = 0.8   # ~a goal's worth of chances; below this is noise this early in the tournament
TOP_HOT = 12
TOP_COLD = 6

src = json.load(open(SRC))


def team(r):
    return r.get("contestantName") or r.get("contestantShortName") or ""


def row(r, kg, kxg, kdiff, kshots):
    return {
        "name": r["player"],
        "team": team(r),
        "diff": round(r[kdiff], 2),
        "goals": r[kg],
        "xg": round(r[kxg], 2),
        "shots": r[kshots],
    }


def board(table, keys):
    """table = list of player rows; keys = (goals, xg, diff, shots) field names."""
    kg, kxg, kdiff, kshots = keys
    elig = [r for r in table if (r.get(kxg) or 0) >= MIN_XG]
    elig.sort(key=lambda r: -r[kdiff])
    hot = [row(r, *keys) for r in elig[:TOP_HOT]]
    cold = [row(r, *keys) for r in elig[-TOP_COLD:]][::-1]   # most negative first
    return hot, cold, len(elig)


# np = non-penalty (matches our 2022 board); all = overall incl. penalties (matches The
# Analyst's default table — e.g. Messi +3.31, where their xG counts a penalty he missed).
np_hot, np_cold, np_n = board(src["nonPenalty"], ("np_goals", "np_xg", "np_goals_vs_xg", "np_shots"))
all_hot, all_cold, all_n = board(src["overall"], ("goals", "xg", "goals_vs_xg", "shots"))

max_apps = max((r.get("apps") or 0) for r in src["nonPenalty"])

out = {
    "metric": "Finishing: goals minus xG (live WC2026)",
    "definition": ("Goals minus expected goals — did a player score more than his chances were worth? "
                   "The same read as the 2022 board, live for World Cup 2026 from Opta's official feed. "
                   "Two views: non-penalty (matches our 2022 board) and all shots incl. penalties "
                   "(matches The Analyst's default table). Gated at xG >= %.1f; a 3-4 game sample is who's "
                   "running hot, not a verdict on finishing skill." % MIN_XG),
    "source": "The Analyst / Opta — live FIFA World Cup 2026 stats feed",
    "last_updated": src["lastUpdated"],
    "matches_played_max": max_apps,
    "min_xg": MIN_XG,
    "np": {"hot": np_hot, "cold": np_cold, "n_eligible": np_n},
    "all": {"hot": all_hot, "cold": all_cold, "n_eligible": all_n},
    # legacy top-level (= non-penalty) kept for any cached reader
    "hot": np_hot,
    "cold": np_cold,
    "n_eligible": np_n,
}
json.dump(out, open(OUT, "w"), indent=1)
print(f"wrote {OUT.name}: np {np_n} / all {all_n} eligible (xG>={MIN_XG}), up to {max_apps} games played")
for label, hot, cold in [("NON-PENALTY", np_hot, np_cold), ("ALL (incl. pens)", all_hot, all_cold)]:
    print(f"\n=== {label} — HOTTEST ===")
    for p in hot:
        print(f"  {p['diff']:+.2f}  {p['name']:22} {p['team']:14} {p['goals']}G · {p['xg']} xG · {p['shots']} sh")
    print(f"--- {label} — COLDEST ---")
    for p in cold:
        print(f"  {p['diff']:+.2f}  {p['name']:22} {p['team']:14} {p['goals']}G · {p['xg']} xG · {p['shots']} sh")
