#!/usr/bin/env python3
"""Build intro_efi.json — the "what is space / what is control" precursor act.

Grounds the basic definitions of SPACE and CONTROL in FIFA's own 2026 data:
  - team SHAPE (length x width per phase) from a FIFA Post-Match Summary Report
    (shufinskiy parser) = "the pitch a team stretches open" = space, occupied.
  - off-ball "offers/movement to receive in behind / in between" = finding space.
  - 2026 EFI (Bustami) team aggregates = the same ideas, measured live, league-wide.

The 2022-vs-2026 bridge: 2022 EFI was physical-only (distance/sprints/top speed),
so "space" had to be reconstructed from tracking; 2026 FIFA publishes shape, offers,
line-breaks and threat directly. Reads only local staged copies (no network).
"""
import csv, json, os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "efi_2026_src")
OUT = os.path.join(ROOT, "site", "data", "intro_efi.json")

# ---- 1. team shape from the example PMSR (BRA v MAR, WC2026) ----
pmsr = json.load(open(os.path.join(SRC, "pmsr_bra_mor_2026.json")))
pages = pmsr["pages"]

def phase_shape(pg):
    d = pages[str(pg)]["data"]
    out = {"team": d["team"]}
    for k in ("build_up_low", "build_up_mid", "final_third_phase",
              "high_block_press", "mid_block", "low_block"):
        if k in d:
            out[k] = {"w": d[k].get("width_m"), "l": d[k].get("length_m"),
                      "d2g": d[k].get("distance_to_goal_m")}
    return out

in_poss = {phase_shape(6)["team"]: phase_shape(6), phase_shape(7)["team"]: phase_shape(7)}
def_shape = {phase_shape(27)["team"]: phase_shape(27), phase_shape(28)["team"]: phase_shape(28)}

def lb_total(pg):
    d = pages[str(pg)]["data"]
    return {"team": d["team"], "attempted": d.get("total_attempted")}
line_breaks = [lb_total(8), lb_total(9)]

def offers(pg):
    d = pages[str(pg)]["data"]
    return {"team": d["team"], "made": d.get("total_offers_made"),
            "received": d.get("total_offers_received"),
            "by_third": d.get("offers_made_by_third", {})}
offers_rep = [offers(20), offers(21)]

def movement(pg):
    d = pages[str(pg)]["data"]
    m = d.get("all_movement_types", {})
    return {"team": d["team"], "total": m.get("total"),
            "in_front": m.get("in_front"), "in_between": m.get("in_between")}
movement_rep = [movement(22), movement(23)]

ks = pages["3"]["data"]["statistics"]
key_stats = {s["stat"]: {"home": s.get("home_team"), "away": s.get("away_team")} for s in ks}

example = {
    "label": f'{pmsr["match"]["home_team_name"]} {pmsr["match"]["score"]["home"]}'
             f'–{pmsr["match"]["score"]["away"]} {pmsr["match"]["away_team_name"]}',
    "stage": pmsr["match"]["stage"], "date": pmsr["match"]["date"],
    "home": pmsr["match"]["home_team_name"], "away": pmsr["match"]["away_team_name"],
    "in_possession_shape": in_poss, "defensive_shape": def_shape,
    "line_breaks": line_breaks, "offers_to_receive": offers_rep,
    "movement_to_receive": movement_rep,
    "key_stats": {k: key_stats[k] for k in key_stats if k in
                  ("Goals", "xG (Expected Goals)", "Total Attempts", "Possession")},
}

# ---- 2. live 2026 EFI team aggregates: off-ball space-seeking ----
rows = list(csv.DictReader(open(os.path.join(SRC, "wc2026_efi.csv"))))
def fnum(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0

teams = defaultdict(lambda: defaultdict(float))
team_matches = defaultdict(set)
for r in rows:
    t = r.get("team_name") or r.get("team_id")
    if not t: continue
    team_matches[t].add(r.get("match_id"))
    for col in ("offers_to_receive_in_behind", "offers_to_receive_in_between",
                "receptions_in_behind", "receptions_between_midfield_and_defensive_line",
                "linebreaks_completed_all_lines", "threat", "total_distance"):
        teams[t][col] += fnum(r.get(col))

def board(col, n=10, rnd=1):
    arr = []
    for t, agg in teams.items():
        m = max(1, len(team_matches[t]))
        arr.append({"team": t, "per_match": round(agg[col] / m, rnd),
                    "matches": len(team_matches[t])})
    arr.sort(key=lambda x: -x["per_match"])
    return arr[:n]

efi_2026 = {
    "n_matches_played": len({r.get("match_id") for r in rows}),
    "offers_in_behind": board("offers_to_receive_in_behind"),
    "offers_in_between": board("offers_to_receive_in_between"),
    "receptions_in_behind": board("receptions_in_behind"),
    "linebreaks_completed": board("linebreaks_completed_all_lines"),
}

out = {
    "fetched": "2026-06-18",
    "sources": {
        "pmsr": "FIFA Post-Match Summary Report, parsed via shufinskiy/sport_analytics_tools (fifa_wc)",
        "pmsr_url": "https://github.com/shufinskiy/sport_analytics_tools/tree/main/fifa_wc",
        "pmsr_hub": "https://www.fifatrainingcentre.com/en/fifa-world-cup-2026/match-report-hub.php",
        "efi": "FIFA Enhanced Football Intelligence (WC2026), Bustami/efi-fifa-data-wc-2026",
        "efi_url": "https://github.com/Bustami/efi-fifa-data-wc-2026",
    },
    "note_2022_vs_2026": ("In 2022 FIFA's Enhanced Football Intelligence was physical-only "
        "(distance, sprints, top speed), so space had to be reconstructed from tracking + labels. "
        "For 2026 FIFA publishes team shape, line-breaks, offers-to-receive and a threat number "
        "directly in every Post-Match Summary Report — the same space ideas, now measured live."),
    "example_match": example,
    "efi_2026": efi_2026,
}
json.dump(out, open(OUT, "w"), indent=1)
print("wrote", OUT)
print("example:", example["label"], "|", example["stage"])
print("BRA build-up shape:", in_poss.get("Brazil", {}).get("build_up_low"))
print("MAR final-third shape:", in_poss.get("Morocco", {}).get("final_third_phase"))
print("line breaks:", line_breaks)
print("offers in behind 2026 top3:", [(b["team"], b["per_match"]) for b in efi_2026["offers_in_behind"][:3]])
print("n matches played (efi):", efi_2026["n_matches_played"])
