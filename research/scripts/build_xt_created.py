#!/usr/bin/env python3
"""xT-created leaderboards: who moves the ball into more dangerous space.

For every completed open-play pass in the StatsBomb WC2022 data, look up the xT of
the start cell and the end cell on the same Karun Singh grid the page already shows
(research/site/data/surfaces/xt_reference.json), and credit the passer with the
xT gained (end - start). Sum per team (per match) and per player (total + per-90-ish
by matches). Output research/site/data/xt_created.json for the xT act.
"""
import glob
import json
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "research" / "site" / "data"
EVENTS = ROOT / "research" / "data" / "raw_statsbomb" / "events"

# xT grid (actual values = normalized * max_xt)
xt = json.load(open(SITE / "surfaces" / "xt_reference.json"))
SURF = xt["surface_norm"]
MAXXT = xt["max_xt"]
NY = len(SURF)
NX = len(SURF[0])


def xt_at(x, y):
    """StatsBomb location (0-120, 0-80; team attacks toward x=120) -> xT value."""
    c = min(NX - 1, max(0, int(x / 120.0 * NX)))
    r = min(NY - 1, max(0, int(y / 80.0 * NY)))
    return SURF[r][c] * MAXXT


def _wc2022_ids():
    """The 64 WC2022 SB match ids — the events/ dir also holds club leagues, so filter."""
    import pandas as pd
    m = pd.read_parquet(ROOT / "research" / "data" / "statsbomb" / "matches_wc_2022_sb.parquet")
    return set(m["match_id"].astype(str))


def main():
    WC = _wc2022_ids()
    team_xt = defaultdict(float)
    team_matches = defaultdict(set)
    player_xt = defaultdict(float)
    player_team = {}
    player_matches = defaultdict(set)
    n_files = 0
    for f in glob.glob(str(EVENTS / "*.json")):
        mid = Path(f).stem
        if mid not in WC:                     # WC2022 only (skip club-league files)
            continue
        try:
            ev = json.load(open(f))
        except Exception:
            continue
        n_files += 1
        for e in ev:
            if e.get("type", {}).get("name") != "Pass":
                continue
            p = e.get("pass", {})
            if p.get("outcome"):            # only completed passes (no outcome = complete)
                continue
            if p.get("type", {}).get("name") in ("Corner", "Free Kick", "Throw-in", "Kick Off", "Goal Kick"):
                continue                     # open play only
            loc = e.get("location"); end = p.get("end_location")
            if not loc or not end:
                continue
            d = xt_at(end[0], end[1]) - xt_at(loc[0], loc[1])
            if d <= 0:
                continue                     # "threat created" = positive progressions
            team = e.get("team", {}).get("name")
            pl = e.get("player", {}).get("name")
            if team:
                team_xt[team] += d; team_matches[team].add(mid)
            if pl:
                player_xt[pl] += d; player_team[pl] = team; player_matches[pl].add(mid)

    teams = sorted(
        ({"team": t, "xt_per_match": round(team_xt[t] / max(1, len(team_matches[t])), 2),
          "xt_total": round(team_xt[t], 1), "matches": len(team_matches[t])}
         for t in team_xt), key=lambda r: -r["xt_per_match"])
    players = sorted(
        ({"name": pl, "team": player_team[pl], "xt_total": round(player_xt[pl], 2),
          "xt_per_match": round(player_xt[pl] / max(1, len(player_matches[pl])), 2),
          "matches": len(player_matches[pl])}
         for pl in player_xt if len(player_matches[pl]) >= 1),
        key=lambda r: -r["xt_total"])

    out = {
        "metric": "xT created (threat added by open-play passing)",
        "definition": ("Sum of Expected Threat gained — xT(pass end) − xT(pass start), positive moves only — "
                       "over completed open-play passes. Same Karun Singh xT grid shown above; StatsBomb 2022 open data."),
        "source": "StatsBomb WC2022 open data; xT grid = research/site/data/surfaces/xt_reference.json",
        "n_matches": n_files,
        "teams": teams,
        "players": players[:14],
    }
    json.dump(out, open(SITE / "xt_created.json", "w"), indent=1)
    print(f"wrote xt_created.json from {n_files} matches")
    print("team xT/match top5:", [(t["team"], t["xt_per_match"]) for t in teams[:5]])
    print("player xT total top5:", [(p["name"], p["xt_total"], p["matches"]) for p in players[:5]])


if __name__ == "__main__":
    main()
