#!/usr/bin/env python3
"""Build efi_runs_2022.json — WC2022 off-ball runs in behind, from FIFA EFI post-match PDFs.

FIFA's 2022 post-match reports publish, per match, each team's TOP 'in behind' mover
(2 players/match). So this is "who led their team in runs behind the line": a summed
total across the matches they led, plus each player's single-match peak. Pairs with the
full per-player live-2026 board (efi_runs_2026.json). Source PDFs parsed from
fifatrainingcentre.com/en/fwc2022/post-match-summaries.
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSED = Path("/private/tmp/claude-501/-Users-nick/a50f1208-2a88-4014-ba3b-97a457d76d75/scratchpad/efi22/parsed.json")
OUT = ROOT / "site" / "data" / "efi_runs_2022.json"

# FIFA format is "SURNAME(S) Firstname" with surname in ALL CAPS (can be multi-word, e.g.
# "DI MARIA Angel"). Surname = leading consecutive all-caps tokens; firstname = the rest.
# If everything is all-caps (e.g. "FERAS ALBRIKAN", "GABRIEL JESUS"), just title-case it.
def nice(n):
    toks = n.split()
    caps = [t for t in toks if t.isupper()]
    rest = [t for t in toks if not t.isupper()]
    if caps and rest:
        sur = " ".join(w.title() for w in caps)
        first = " ".join(rest).title()
        return f"{first} {sur}"
    return " ".join(w.title() for w in toks)


d = json.load(open(PARSED))
recs = [r for r in d["records"] if len(r["teams"]) == 2]

# dedupe matches by team pair, keep richest record
bym = {}
for r in recs:
    k = tuple(sorted(r["teams"]))
    if k not in bym or len(r["runs"]) > len(bym[k]["runs"]):
        bym[k] = r

agg = {}
match_rows = []
for r in bym.values():
    teams = r["teams"]
    for nm, c in r["runs"]:
        disp = nice(nm)
        a = agg.setdefault(disp, {"total": 0, "led": 0, "peak": 0, "peak_match": ""})
        a["total"] += c; a["led"] += 1
        if c > a["peak"]:
            a["peak"] = c; a["peak_match"] = " v ".join(teams)
        match_rows.append({"name": disp, "in_behind": c, "match": " v ".join(teams)})

players = [{"name": k, "in_behind_total": v["total"], "matches_led": v["led"],
            "peak": v["peak"], "peak_match": v["peak_match"]} for k, v in agg.items()]
players.sort(key=lambda p: -p["in_behind_total"])
peak_rows = sorted(match_rows, key=lambda r: -r["in_behind"])

out = {
    "metric": "Off-ball runs in behind (FIFA EFI, WC2022)",
    "definition": ("FIFA Enhanced Football Intelligence post-match reports publish each team's TOP "
                   "'in behind' mover per match (the player who most often ran to receive behind the "
                   "defensive line). This board sums those per-match team-leading counts, and tracks "
                   "each player's single-match peak. It's the 2022 companion to the full per-player "
                   "live-2026 board — narrower (team leaders only) but FIFA's official figures."),
    "source": "FIFA Training Centre — WC2022 post-match summary reports (PDF)",
    "grain": "per-match team leader (2 players/match)",
    "n_matches": len(bym),
    "players": players,
    "peak_single_match": peak_rows[:15],
}
json.dump(out, open(OUT, "w"), indent=1)
print(f"wrote {OUT.name}: {len(players)} players over {len(bym)} matches")
print("top total:", [(p["name"], p["in_behind_total"], p["matches_led"]) for p in players[:6]])
print("top single-match:", [(r["name"], r["in_behind"], r["match"]) for r in peak_rows[:6]])
