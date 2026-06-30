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


def row(r):
    return {
        "name": r["player"],
        "team": team(r),
        "diff": round(r["np_goals_vs_xg"], 2),
        "goals": r["np_goals"],
        "xg": round(r["np_xg"], 2),
        "shots": r["np_shots"],
    }


elig = [r for r in src["nonPenalty"] if (r.get("np_xg") or 0) >= MIN_XG]
elig.sort(key=lambda r: -r["np_goals_vs_xg"])
hot = [row(r) for r in elig[:TOP_HOT]]
cold = [row(r) for r in elig[-TOP_COLD:]][::-1]   # most negative first

max_apps = max((r.get("apps") or 0) for r in src["nonPenalty"])

out = {
    "metric": "Finishing: non-penalty goals minus non-penalty xG (live WC2026)",
    "definition": ("Non-penalty goals minus non-penalty expected goals — did a player score more than "
                   "his chances were worth? The same read as the 2022 board, live for World Cup 2026 from "
                   "Opta's official feed. Gated at npxG >= %.1f; a 4-game sample is who's running hot, "
                   "not a verdict on finishing skill." % MIN_XG),
    "source": "The Analyst / Opta — live FIFA World Cup 2026 stats feed",
    "last_updated": src["lastUpdated"],
    "matches_played_max": max_apps,
    "min_xg": MIN_XG,
    "n_eligible": len(elig),
    "hot": hot,
    "cold": cold,
}
json.dump(out, open(OUT, "w"), indent=1)
print(f"wrote {OUT.name}: {len(elig)} eligible (npxG>={MIN_XG}), up to {max_apps} games played")
print("HOTTEST:")
for p in hot:
    print(f"  {p['diff']:+.2f}  {p['name']:22} {p['team']:14} {p['goals']}G · {p['xg']} xG · {p['shots']} sh")
print("COLDEST:")
for p in cold:
    print(f"  {p['diff']:+.2f}  {p['name']:22} {p['team']:14} {p['goals']}G · {p['xg']} xG · {p['shots']} sh")
