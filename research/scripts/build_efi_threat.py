#!/usr/bin/env python3
"""Build efi_2026.json — the LIVE 2026 "threat created" board (FIFA's xT-cousin).

The closing hook of the xT act: the off-ball "threat" idea our space metrics chase,
now measured in-tournament by FIFA's Enhanced Football Intelligence. Unlike 2022 EFI
(physical-only: distance, sprints, top speed), 2026 EFI publishes a per-player THREAT
number and xG directly, so we can rank teams and players by danger created — live.

Reads the staged player-level CSV (one row per player-match) at
  research/data/efi_2026_src/wc2026_efi.csv
Source: Bustami/efi-fifa-data-wc-2026 (master); team_name is already the FIFA 3-letter
code, so no mapping is needed. Values are per-match averages (fair as the field plays
different counts). Network-free: re-fetch the CSV separately, then run this.

  python3 research/scripts/build_efi_threat.py
"""
import csv
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "efi_2026_src", "wc2026_efi.csv")
OUT = os.path.join(ROOT, "site", "data", "efi_2026.json")
FETCHED = "2026-06-29"


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


rows = list(csv.DictReader(open(SRC)))
matches = {r["match_id"] for r in rows}

teams = defaultdict(lambda: {"threat": 0.0, "xg": 0.0, "dist": 0.0, "m": set()})
players = defaultdict(lambda: {"threat": 0.0, "xg": 0.0, "m": set(),
                               "team": "", "pos": "", "name": ""})
for r in rows:
    t = r["team_name"]
    tm = teams[t]
    tm["threat"] += fnum(r["threat"]); tm["xg"] += fnum(r["xg"])
    tm["dist"] += fnum(r["total_distance"]); tm["m"].add(r["match_id"])
    pid = r["player_id"]
    p = players[pid]
    p["threat"] += fnum(r["threat"]); p["xg"] += fnum(r["xg"]); p["m"].add(r["match_id"])
    p["team"] = t; p["pos"] = r["position"]; p["name"] = r["player_name"]


def team_row(t):
    d = teams[t]; m = max(1, len(d["m"]))
    return {"team": t, "threat": round(d["threat"] / m, 2), "xg": round(d["xg"] / m, 2),
            "dist_km": round(d["dist"] / m / 1000.0, 1), "matches": len(d["m"])}


team_rows = [team_row(t) for t in teams]
team_threat_leaders = sorted(team_rows, key=lambda r: -r["threat"])[:12]
team_distance_leaders = sorted(team_rows, key=lambda r: -r["dist_km"])[:12]

player_rows = []
for p in players.values():
    if p["pos"] == "Goalkeeper":
        continue
    m = max(1, len(p["m"]))
    player_rows.append({"player": p["name"], "team": p["team"],
                        "threat": round(p["threat"] / m, 2), "xg": round(p["xg"] / m, 2),
                        "matches": len(p["m"]), "pos": p["pos"]})
player_threat_leaders = sorted(player_rows, key=lambda r: -r["threat"])[:12]

out = {
    "source": "FIFA Enhanced Football Intelligence (EFI), WC2026 — Bustami/efi-fifa-data-wc-2026 (master)",
    "fetched": FETCHED,
    "note": ("2026 EFI is RICH + LIVE (threat, xg) — unlike 2022 which was physical-only "
             "(distance/sprints/top speed). This is the live closing hook: the off-ball "
             "\"threat\" idea our space metrics chase, now measured in-tournament. Values "
             "are per-match averages."),
    "n_matches": len(matches),
    "n_teams": len(teams),
    "n_player_rows": len(rows),
    "team_threat_leaders": team_threat_leaders,
    "team_distance_leaders": team_distance_leaders,
    "player_threat_leaders": player_threat_leaders,
    "space_not_distance": ("Threat and distance are NOT the same axis: the team that runs "
        "the most is rarely the team that threatens the most. That is the whole 2022 thesis "
        "— space is positional value, not kilometres covered — carried into the live 2026 numbers."),
}
json.dump(out, open(OUT, "w"), indent=1)
print("wrote", OUT)
print(f"matches={len(matches)} teams={len(teams)} player_rows={len(rows)}")
print("team threat top5:", [(r["team"], r["threat"]) for r in team_threat_leaders[:5]])
print("player threat top5:", [(r["player"], r["team"], r["threat"]) for r in player_threat_leaders[:5]])
