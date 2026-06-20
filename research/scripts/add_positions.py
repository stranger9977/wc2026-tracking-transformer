#!/usr/bin/env python3
"""Inject player position (PFF positionGroupType) into the space leaderboard JSONs.

The leaderboards identify players by (team, name); PFF rosters carry
positionGroupType (CF, RW, AM, RCB, RB, DM, GK, ...). We build a (team, name) ->
position map from every roster on disk and stamp `position` onto each player row
in space_chase.json and space_pobso.json. Post-process only — no surface re-render.
"""
import glob
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PFF = Path(os.environ.get("PFF_ROOT", str(Path.home() / "pff_wc22_local")))
SITE = ROOT / "research" / "site" / "data"

# collapse the very granular groups to compact, readable labels
COLLAPSE = {"RCB": "CB", "LCB": "CB", "RB": "RB", "LB": "LB", "RWB": "RB",
            "LWB": "LB", "RW": "RW", "LW": "LW", "CF": "CF", "ST": "CF",
            "AM": "AM", "CM": "CM", "DM": "DM", "GK": "GK", "RM": "RM", "LM": "LM"}


def build_map():
    m = {}
    for f in glob.glob(str(PFF / "Rosters" / "*.json")):
        for e in json.load(open(f)):
            name = (e.get("player", {}).get("nickname")
                    or e.get("player", {}).get("name"))
            team = e.get("team", {}).get("name")
            pgt = e.get("positionGroupType")
            if name and team and pgt:
                m[(team, name)] = COLLAPSE.get(pgt, pgt)
    return m


def stamp(path, pos_map):
    d = json.load(open(path))
    n_set = n_miss = 0
    for p in d.get("players", []):
        pos = pos_map.get((p.get("team"), p.get("name")), "")
        p["position"] = pos
        if pos:
            n_set += 1
        else:
            n_miss += 1
    json.dump(d, open(path, "w"), indent=1)
    print(f"{Path(path).name}: position set on {n_set} players, {n_miss} unmatched")


def main():
    pos_map = build_map()
    print(f"position map: {len(pos_map)} (team,name) entries from {PFF/'Rosters'}")
    stamp(SITE / "space_chase.json", pos_map)
    stamp(SITE / "space_pobso.json", pos_map)
    stamp(SITE / "space_sgg.json", pos_map)


if __name__ == "__main__":
    main()
