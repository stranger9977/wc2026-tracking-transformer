#!/usr/bin/env python3
"""Does Messi control dangerous space while WALKING? (the 538 "Messi walks" tie-in)

For a set of matches, reuse the P-OBSO off-ball attribution (space_pobso.frame_obso)
and record, for the off-ball attacker who owns each cell's control x xT, that
player's SPEED at the frame. We can then split each player's controlled-danger
(OBSO) into speed buckets (walk/jog/run/sprint) and compute an OBSO-weighted mean
speed: "when this player owns dangerous space off the ball, how fast is he moving?"

Also an OVERALL time-by-speed profile per player (the raw "% of the match walking"
stat the 538 piece is built on), so we can show Messi both (a) walks a lot, and
(b) accrues his dangerous-space control at walking pace, unlike sprinter CFs.

Speed buckets (m/s): walk <2.0 (~<7.2 km/h), jog 2-4, run 4-7, sprint >7 (~>25 km/h).

Run (MAIN loop, LOCAL cache only):
    export PFF_ROOT="$HOME/pff_wc22_local"
    PYTHONPATH=src uv run python research/scripts/space_walk_in.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "research" / "scripts"))
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

import space_io          # noqa: E402
import pitch_control as pc  # noqa: E402
import space_pobso as sp    # noqa: E402

HALF_LEN = pc.HALF_LEN
HALF_WID = pc.HALF_WID
STRIDE = sp.SAMPLING_STRIDE   # ~2 Hz
PERIODS = (1, 2)
SECS_PER_FRAME = STRIDE / sp.RAW_HZ

# Teams whose matches we scan. Argentina => Messi/Di Maria/Alvarez; Morocco =>
# En-Nesyri (the board #1, a sprinter CF). The ARG-FRA final is inside the
# Argentina set, so it also picks up Mbappe/Giroud/Kolo Muani for comparison.
TEAMS = {"Argentina", "Morocco"}

BUCKETS = ("walk", "jog", "run", "sprint")


def bucket(spd: float) -> str:
    if spd < 2.0:
        return "walk"
    if spd < 4.0:
        return "jog"
    if spd < 7.0:
        return "run"
    return "sprint"


def pick_matches():
    root = Path(os.environ.get("PFF_ROOT", str(Path.home() / "pff_wc22_local")))
    mids = sorted(p.name.replace(".jsonl.bz2", "")
                  for p in (root / "Tracking Data").glob("*.jsonl.bz2"))
    out = []
    for mid in mids:
        meta = space_io.load_metadata(mid)
        if meta["homeTeam"]["name"] in TEAMS or meta["awayTeam"]["name"] in TEAMS:
            out.append((mid, f'{meta["homeTeam"]["name"]} v {meta["awayTeam"]["name"]}'))
    return out


def main():
    grid = pc.make_grid(nx=sp.COMPUTE_GRID[1], ny=sp.COMPUTE_GRID[0])
    xt_grid = pc.xt_surface(grid)
    matches = pick_matches()
    print(f"[walk-in] {len(matches)} matches:", flush=True)
    for mid, lab in matches:
        print(f"   {mid}  {lab}", flush=True)

    meta_pl: dict = {}
    obso_sum = defaultdict(float)            # total OBSO owned (xT-wtd m^2 . frames)
    obso_wspeed = defaultdict(float)         # sum of OBSO * speed
    obso_bkt = defaultdict(lambda: defaultdict(float))   # key -> bucket -> OBSO
    obso_frames = defaultdict(int)           # frames the player owned any OBSO
    time_bkt = defaultdict(lambda: defaultdict(int))     # overall frames-present by bucket

    t0 = time.time()
    for mi, (mid, lab) in enumerate(matches):
        n = 0
        tm = time.time()
        for fr in space_io.read_match(mid, sampling_stride=STRIDE, periods=PERIODS):
            spds = np.hypot(fr.players[:, 2], fr.players[:, 3])
            # overall time-by-speed profile (every player present this frame)
            for i, ident in enumerate(fr.identities):
                key = (ident.team_id, ident.jersey)
                if key not in meta_pl:
                    meta_pl[key] = {"name": ident.name, "team": ident.team,
                                    "is_gk": ident.is_gk}
                time_bkt[key][bucket(float(spds[i]))] += 1
            # off-ball OBSO attribution this frame
            _, _, attrib, _, _, _ = sp.frame_obso(fr, grid, xt_grid)
            for row, val in attrib.items():
                ident = fr.identities[row]
                key = (ident.team_id, ident.jersey)
                spd = float(spds[row])
                obso_sum[key] += val
                obso_wspeed[key] += val * spd
                obso_bkt[key][bucket(spd)] += val
                obso_frames[key] += 1
            n += 1
        print(f"[{mi+1}/{len(matches)}] {mid} {lab}: {n} frames "
              f"[{time.time()-tm:.1f}s, tot {time.time()-t0:.1f}s]", flush=True)

    # Build rows for players with enough off-ball danger-owning presence.
    rows = []
    for key, osum in obso_sum.items():
        nf = obso_frames[key]
        if nf < 150 or meta_pl[key]["is_gk"]:
            continue
        tb = time_bkt[key]
        tot_t = sum(tb.values()) or 1
        ob = obso_bkt[key]
        ob_tot = osum or 1e-9
        rows.append({
            "name": meta_pl[key]["name"], "team": meta_pl[key]["team"],
            "obso_per_frame": osum / nf,
            "obso_frames": nf,
            "obso_wspeed": obso_wspeed[key] / ob_tot,          # OBSO-weighted mean speed (m/s)
            "obso_walk_share": ob.get("walk", 0.0) / ob_tot,    # share of danger owned while walking
            "obso_jog_share": ob.get("jog", 0.0) / ob_tot,
            "obso_run_share": ob.get("run", 0.0) / ob_tot,
            "obso_sprint_share": ob.get("sprint", 0.0) / ob_tot,
            "time_walk_share": tb.get("walk", 0) / tot_t,       # overall % of time walking (538 stat)
            "time_sprint_share": tb.get("sprint", 0) / tot_t,
        })
    rows.sort(key=lambda r: -r["obso_per_frame"])

    print("\n" + "=" * 110)
    print(f"{'player':<22}{'team':<12}{'OBSO/fr':>8}{'wspd':>7}{'walk%OBSO':>10}"
          f"{'sprint%OBSO':>12}{'time-walk%':>11}{'time-sprint%':>13}{'fr':>7}")
    print("=" * 110)
    for r in rows[:24]:
        print(f"{r['name']:<22}{r['team']:<12}{r['obso_per_frame']:>8.2f}"
              f"{r['obso_wspeed']:>7.2f}{100*r['obso_walk_share']:>9.0f}%"
              f"{100*r['obso_sprint_share']:>11.0f}%{100*r['time_walk_share']:>10.0f}%"
              f"{100*r['time_sprint_share']:>12.0f}%{r['obso_frames']:>7}")

    # Verdict: where does Messi rank on (a) OBSO and (b) LOW weighted speed?
    by_ob = sorted(rows, key=lambda r: -r["obso_per_frame"])
    by_slow = sorted(rows, key=lambda r: r["obso_wspeed"])   # slowest first
    def rk(lst, nm):
        for i, r in enumerate(lst):
            if r["name"] == nm:
                return i + 1, len(lst)
        return None, len(lst)
    messi = next((r for r in rows if "Messi" in r["name"]), None)
    print("\n" + "-" * 60)
    if messi:
        ob_rank = rk(by_ob, messi["name"]); slow_rank = rk(by_slow, messi["name"])
        print(f"MESSI: OBSO/frame {messi['obso_per_frame']:.2f} "
              f"(rank {ob_rank[0]}/{ob_rank[1]} by danger owned)")
        print(f"       OBSO-weighted speed {messi['obso_wspeed']:.2f} m/s "
              f"(rank {slow_rank[0]}/{slow_rank[1]} SLOWEST)")
        print(f"       {100*messi['obso_walk_share']:.0f}% of his owned danger is at WALKING pace; "
              f"{100*messi['time_walk_share']:.0f}% of his match time is walking.")
    else:
        print("Messi not found in rows (check name match / minutes).")

    out = {"teams": sorted(TEAMS), "n_matches": len(matches),
           "stride": STRIDE, "secs_per_frame": SECS_PER_FRAME,
           "buckets_mps": {"walk": "<2", "jog": "2-4", "run": "4-7", "sprint": ">7"},
           "players": rows}
    op = _REPO / "research" / "data" / "space_walk_in.json"
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, indent=1))
    print(f"\n[export] {op}")
    print("EXIT_OK", flush=True)


if __name__ == "__main__":
    main()
