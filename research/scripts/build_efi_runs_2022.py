#!/usr/bin/env python3
"""Build efi_runs_2022.json — WC2022 off-ball runs in behind, FULL per-player, from FIFA EFI PDFs.

The FIFA post-match reports have an INDIVIDUAL DATA -> "In Possession - Offers & Receptions"
table listing EVERY player's offer-movement breakdown:
  # Player | Total Offers | In Front | In Between | Out to In | In to Out | In Behind | No Movement | Offers Received
We parse the In Behind column (off-ball runs to receive behind the line) and Offers Received
for every player, aggregate across all 61 matches -> a true per-player tournament leaderboard,
directly comparable to the live-2026 EFI board. PDFs pre-downloaded + pdftotext'd to PDF_DIR.
"""
import json, re, os, glob
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = "/private/tmp/claude-501/-Users-nick/a50f1208-2a88-4014-ba3b-97a457d76d75/scratchpad/efi22"
OUT = ROOT / "site" / "data" / "efi_runs_2022.json"

# row: leading jersey, name (non-digit), then exactly 8 integers
ROW = re.compile(r"^\s*(\d{1,2})\s+([A-Za-zÀ-ÿ'’.\- ]+?)\s+(\d+(?:\s+\d+){7})\s*$")


def nice(n):
    toks = n.split()
    caps = [t for t in toks if t.isupper()]
    rest = [t for t in toks if not t.isupper()]
    if caps and rest:
        return f"{' '.join(w.title() for w in rest)} {' '.join(w.title() for w in caps)}"
    return " ".join(w.title() for w in toks)


HDR = re.compile(r"offers\s*&+\s*receptions\s+([A-Za-zÀ-ÿ' .]+?)\s*$", re.I)


def parse_offers(txt_path):
    """Yield (player_name, team, in_behind, received, total) from Offers & Receptions tables."""
    out = []
    in_section = False
    team = ""
    for ln in open(txt_path, errors="ignore"):
        low = ln.lower()
        if "offers & receptions" in low or "offers && receptions" in low:
            in_section = True
            hm = HDR.search(ln.strip())
            team = hm.group(1).strip() if hm else ""
            continue
        if in_section and ("distributions" in low or "out of possession" in low
                           or "individual data" in low or "physical" in low):
            in_section = False
        if not in_section:
            continue
        m = ROW.match(ln)
        if not m:
            continue
        name = m.group(2).strip()
        if name.lower() in ("player", "pla ye r") or len(name) < 3:
            continue
        nums = [int(x) for x in m.group(3).split()]
        total, in_front, in_between, out_in, in_out, in_behind, no_move, received = nums
        # sanity: the 6 movement types + no_move should ~= total
        if abs((in_front + in_between + out_in + in_out + in_behind + no_move) - total) > 2:
            continue
        out.append((nice(name), team, in_behind, received, total))
    return out


agg = {}
n_files = 0
per_match_peak = []
for txt in sorted(glob.glob(f"{PDF_DIR}/*.pdf.txt")):
    rows = parse_offers(txt)
    if not rows:
        continue
    n_files += 1
    seen = {}
    for nm, team, ib, rec, tot in rows:
        # within one match a player appears once; guard against dupes
        if nm in seen:
            continue
        seen[nm] = ib
        a = agg.setdefault(nm, {"in_behind": 0, "received": 0, "offers": 0, "m": 0, "peak": 0, "team": ""})
        a["in_behind"] += ib; a["received"] += rec; a["offers"] += tot; a["m"] += 1
        if team:
            a["team"] = team
        if ib > a["peak"]:
            a["peak"] = ib
        per_match_peak.append({"name": nm, "team": team, "in_behind": ib})

players = []
for nm, a in agg.items():
    if a["m"] < 1:
        continue
    players.append({
        "name": nm, "team": a["team"], "matches": a["m"],
        "in_behind": a["in_behind"], "in_behind_pm": round(a["in_behind"] / a["m"], 1),
        "received": a["received"], "offers_total": a["offers"], "peak": a["peak"],
    })
players.sort(key=lambda p: -p["in_behind"])
peak = sorted(per_match_peak, key=lambda r: -r["in_behind"])[:15]

out = {
    "metric": "Off-ball runs in behind (FIFA EFI, WC2022) — full per-player",
    "definition": ("FIFA Enhanced Football Intelligence, parsed from every WC2022 post-match report's "
                   "INDIVIDUAL DATA 'Offers & Receptions' table: each player's 'In Behind' offers — "
                   "off-ball runs made to receive the ball behind the defensive line — summed across "
                   "the tournament, with per-match average. The 2022 companion to the live-2026 board."),
    "source": "FIFA Training Centre — WC2022 post-match summary reports (PDF, INDIVIDUAL DATA)",
    "grain": "every player, every match",
    "n_match_reports": n_files,
    "players": players,
    "peak_single_match": peak,
}
json.dump(out, open(OUT, "w"), indent=1)
print(f"wrote {OUT.name}: {len(players)} players from {n_files} match reports")
print("TOP 15 total in-behind:")
for p in players[:15]:
    print(f"  {p['name']:24} {p['in_behind']:4d}  ({p['in_behind_pm']}/match, {p['matches']}m, peak {p['peak']})")
print("top single-match:", [(r['name'], r['in_behind']) for r in peak[:6]])
