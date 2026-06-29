#!/usr/bin/env python3
"""Build efi_runs_2026.json — the LIVE 2026 off-ball-runs board (FIFA EFI).

"Who makes the most runs in behind?" from FIFA's Enhanced Football Intelligence:
  offers_to_receive_in_behind   — off-ball runs offering to receive behind the line
  receptions_in_behind          — those runs that actually got the ball
  speed_runs                    — high-speed off-ball runs
Player-level, aggregated over the tournament so far. Per-90 (gated on minutes) +
total. Source CSV: Bustami/efi-fifa-data-wc-2026 (refresh wc2026_efi.csv first).
"""
import csv, json, os, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "efi_2026_src" / "wc2026_efi.csv"
OUT = ROOT / "site" / "data" / "efi_runs_2026.json"
FETCHED = "2026-06-29"
MIN_TOTAL = 180.0       # >=~2 full matches of minutes to appear on totals
MIN_P90 = 270.0         # >=~3 full matches before a per-90 rate is shown


def num(r, k):
    try:
        return float(r.get(k) or 0)
    except ValueError:
        return 0.0


rows = list(csv.DictReader(open(SRC)))
agg = collections.defaultdict(lambda: {"ib": 0.0, "rib": 0.0, "sr": 0.0, "thr": 0.0,
                                       "min": 0.0, "m": 0, "team": "", "name": "", "pos": ""})
for r in rows:
    a = agg[r["player_id"]]
    a["ib"] += num(r, "offers_to_receive_in_behind")
    a["rib"] += num(r, "receptions_in_behind")
    a["sr"] += num(r, "speed_runs")
    a["thr"] += num(r, "threat")
    a["min"] += num(r, "time_played")
    a["m"] += 1
    a["team"] = r.get("team_name", "") or a["team"]
    a["name"] = r.get("player_name", "") or a["name"]
    a["pos"] = r.get("position", "") or a["pos"]

players = []
for v in agg.values():
    if v["min"] < MIN_TOTAL:
        continue
    mins = v["min"]
    players.append({
        "name": v["name"], "team": v["team"], "pos": v["pos"], "matches": v["m"],
        "min": round(mins, 0),
        "in_behind": round(v["ib"], 0), "recv_behind": round(v["rib"], 0),
        "speed_runs": round(v["sr"], 0), "threat": round(v["thr"], 2),
        "in_behind_p90": round(v["ib"] / mins * 90, 1) if mins >= MIN_P90 else None,
        "recv_behind_p90": round(v["rib"] / mins * 90, 1) if mins >= MIN_P90 else None,
        "speed_runs_p90": round(v["sr"] / mins * 90, 1) if mins >= MIN_P90 else None,
    })
players.sort(key=lambda p: -p["in_behind"])

n_matches = len(set(r["match_id"] for r in rows))
out = {
    "metric": "Off-ball runs in behind (FIFA EFI, live WC2026)",
    "definition": ("FIFA Enhanced Football Intelligence. 'Offers to receive in behind' = off-ball "
                   "runs a player makes offering to receive the ball behind the defensive line; "
                   "'receptions in behind' = those runs that actually got the ball; 'speed runs' = "
                   "high-speed off-ball runs. Aggregated per player over the tournament so far."),
    "source": "Bustami/efi-fifa-data-wc-2026",
    "fetched": FETCHED, "n_matches": n_matches, "min_total_min": MIN_TOTAL, "min_p90_min": MIN_P90,
    "n_players": len(players), "players": players,
}
json.dump(out, open(OUT, "w"), indent=1)
print(f"wrote {OUT.name}: {len(players)} players, {n_matches} matches")
p90 = sorted([p for p in players if p["in_behind_p90"] is not None], key=lambda p: -p["in_behind_p90"])
print("top in-behind/90:", [(p["name"].split()[-1], p["in_behind_p90"]) for p in p90[:6]])
print("top total:", [(p["name"].split()[-1], p["in_behind"]) for p in players[:6]])
