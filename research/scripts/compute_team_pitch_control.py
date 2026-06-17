#!/usr/bin/env python3
"""Team pitch control + who plays ABOVE it.

For each sampled frame, compute the Fernandez-Bornn pitch-control surface and the
in-possession team's SHARE of control in the attacking final third (x > 17.5 m) and
over the whole pitch. Average per team => "how much dangerous grass a side actually
owns when it has the ball." Then join StatsBomb 2022 xG-for/match (reused from
space_pobso.json) so we can see who OUT-PERFORMS their control (low control, high xG =
clinical/counter) vs UNDER-performs (high control, low xG = sterile possession).

Run (watchdog-safe; I run it from the main loop, not a subagent):
    export PFF_ROOT="$HOME/pff_wc22_local"
    PYTHONPATH=src uv run python research/scripts/compute_team_pitch_control.py
Output: research/site/data/space_pitch_control.json
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "research" / "scripts"))
sys.path.insert(0, str(_REPO / "src"))

import space_io  # noqa: E402
from pitch_control import make_grid, control_surface  # noqa: E402

SAMPLE_MATCHES = ["10517", "10503", "10514", "10513", "10504",
                  "10512", "10509", "10508", "10511", "10510"]
STRIDE = 15
GNX, GNY = 30, 20
OUT = _REPO / "research" / "site" / "data" / "space_pitch_control.json"
POBSO = _REPO / "research" / "site" / "data" / "space_pobso.json"


def main():
    t0 = time.time()
    root = __import__("os").environ["PFF_ROOT"]
    g = make_grid(GNX, GNY)
    xs = np.asarray(g.xs)                       # cell x centres (m), -52.5..+52.5
    f3 = xs > 17.5                              # attacking final third (opp third)
    acc = defaultdict(lambda: {"f3a": 0.0, "f3t": 0.0, "alla": 0.0, "allt": 0.0,
                               "n": 0, "matches": set()})
    for mi, mid in enumerate(SAMPLE_MATCHES):
        if not (Path(root) / "Tracking Data" / f"{mid}.jsonl.bz2").exists():
            print(f"[skip] {mid}", flush=True); continue
        n = 0
        for fr in space_io.read_match(mid, sampling_stride=STRIDE):
            ctrl = control_surface(fr.players, fr.ball_m, g, include_gk=True)
            ac, dc = ctrl["attack_control"], ctrl["defend_control"]
            tot = ac + dc
            team = fr.in_possession_team
            a = acc[team]
            a["f3a"] += float(ac[:, f3].sum()); a["f3t"] += float(tot[:, f3].sum())
            a["alla"] += float(ac.sum()); a["allt"] += float(tot.sum())
            a["n"] += 1; a["matches"].add(mid); n += 1
        print(f"[{mi+1}/{len(SAMPLE_MATCHES)}] {mid}: {n} frames "
              f"(elapsed {time.time()-t0:.1f}s)", flush=True)

    # StatsBomb xG/match per team (reuse the certified P-OBSO regulation-xG join)
    sbxg = {}
    try:
        det = json.load(open(POBSO))["xg_receipt"]["detail"]
        sbxg = {d["team"]: d["sb_xg_per_match"] for d in det}
    except Exception as e:
        print("xG join unavailable:", e, flush=True)

    rows = []
    for team, a in acc.items():
        if a["n"] < 150:                         # ~75s of possession minimum
            continue
        rows.append({
            "team": team,
            "final_third_control_pct": round(100 * a["f3a"] / max(a["f3t"], 1e-9), 1),
            "overall_control_pct": round(100 * a["alla"] / max(a["allt"], 1e-9), 1),
            "n_frames": a["n"], "n_matches": len(a["matches"]),
            "sb_xg_per_match": sbxg.get(team),
        })
    rows.sort(key=lambda r: -r["final_third_control_pct"])

    # over/under-performance: residual of xG vs final-third control (teams with xG)
    pts = [(r["final_third_control_pct"], r["sb_xg_per_match"], r) for r in rows
           if r["sb_xg_per_match"] is not None]
    if len(pts) >= 3:
        xsv = np.array([p[0] for p in pts]); ysv = np.array([p[1] for p in pts])
        b1 = np.cov(xsv, ysv, bias=True)[0, 1] / max(np.var(xsv), 1e-9)
        b0 = ysv.mean() - b1 * xsv.mean()
        for x, y, r in pts:
            r["xg_residual"] = round(float(y - (b0 + b1 * x)), 3)  # +ve = plays ABOVE control

    out = {
        "metric": "team pitch control (attacking final third) + over/under-performance vs xG",
        "definition": ("Mean share of Fernandez-Bornn pitch control the in-possession team holds in "
                       "the attacking final third (x>17.5 m). 'Plays above' = positive xG residual "
                       "(more xG than its control predicts: clinical/counter); 'below' = sterile."),
        "sample": f"{len(SAMPLE_MATCHES)} knockout matches, stride {STRIDE} (~2 Hz), grid {GNX}x{GNY}",
        "teams": rows,
    }
    json.dump(out, open(OUT, "w"), indent=1)
    print("wrote", OUT, f"({len(rows)} teams, {time.time()-t0:.1f}s)", flush=True)
    print("top final-third control:", [(r["team"], r["final_third_control_pct"]) for r in rows[:5]])
    print("plays ABOVE control (xG residual +):",
          sorted([(r["team"], r.get("xg_residual")) for r in rows if r.get("xg_residual") is not None],
                 key=lambda x: -(x[1] or -9))[:4])


if __name__ == "__main__":
    main()
