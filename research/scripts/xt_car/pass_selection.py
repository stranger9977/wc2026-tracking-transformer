#!/usr/bin/env python3
"""Pass Selection vs Pitch Control (friend's #1) — v3: FINAL-THIRD controllable danger.

Among passes whose TARGET is in the passer's attacking third, value =
control_at_target x xT(target) — "did the pass find controllable, dangerous space in
the final third." Isolates creative final-third passing from deep build-up. GKs excluded.
Per passer: total (volume x quality, in xT units) + per-pass. Carries team + position.

Reads ONLY PFF Event Data (+ Rosters) locally + the xT grid. Fast.
Run:  PFF_ROOT=$HOME/pff_wc22_local PYTHONPATH=src \
        uv run python research/scripts/xt_car/pass_selection.py
Output: research/site/data/pass_selection.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_REPO / "research" / "scripts"), str(_REPO / "src")]
from wc2026_tracking_transformer.baselines.xt import xt_for_ball  # noqa: E402
from opp_strength import OppStrength, stage_of, per_stage_block  # noqa: E402

R_MIN, R_MAX, BALL_SAT = 4.0, 10.0, 18.0
HALF_LEN, HALF_WID = 52.5, 34.0
BETA = 3.0
FINAL_THIRD_X = 17.5
COLLAPSE = {"RCB": "CB", "LCB": "CB", "RB": "RB", "LB": "LB", "RWB": "RB", "LWB": "LB",
            "RW": "RW", "LW": "LW", "CF": "CF", "ST": "CF", "AM": "AM", "CM": "CM",
            "DM": "DM", "GK": "GK", "RM": "RM", "LM": "LM"}
OUT = _REPO / "research" / "site" / "data" / "pass_selection.json"


def infl(px, py, bx, by, tx, ty):
    frac = min(math.hypot(px - bx, py - by) / BALL_SAT, 1.0)
    radius = R_MIN + (R_MAX - R_MIN) * frac ** 2
    return math.exp(-0.5 * (((tx - px) ** 2 + (ty - py) ** 2) / (radius ** 2)))


def control_at(tx, ty, att, dfn, bx, by):
    sa = sum(infl(x, y, bx, by, tx, ty) for x, y in att)
    sd = sum(infl(x, y, bx, by, tx, ty) for x, y in dfn)
    return 1.0 / (1.0 + math.exp(-BETA * (sa - sd)))


def xt(x, y):
    return xt_for_ball(x / HALF_LEN, y / HALF_WID)


def load_roster(root, mid):
    out = {}
    try:
        r = json.load(open(root / "Rosters" / f"{mid}.json"))
    except Exception:
        return out
    rows = r if isinstance(r, list) else r.get("rosters") or r.get("players") or []
    for p in rows:
        pid = p.get("playerId") or p.get("id") or (p.get("player") or {}).get("id")
        team = (p.get("teamName") or (p.get("team") or {}).get("name") or p.get("team"))
        if pid is not None:
            out[int(pid)] = team if isinstance(team, str) else ""
    return out


def sides(ev, passer_id):
    home = [(int(p["playerId"]), float(p["x"]), float(p["y"]), p.get("positionGroupType"))
            for p in (ev.get("homePlayers") or []) if p.get("x") is not None]
    away = [(int(p["playerId"]), float(p["x"]), float(p["y"]), p.get("positionGroupType"))
            for p in (ev.get("awayPlayers") or []) if p.get("x") is not None]
    pos = {i: (x, y) for i, x, y, _ in home + away}
    grp = {i: g for i, _, _, g in home + away}
    if passer_id in {i for i, *_ in home}:
        att, dfn = home, away
    elif passer_id in {i for i, *_ in away}:
        att, dfn = away, home
    else:
        return None, None, pos, grp, None
    gk_x = [x for i, x, y, g in att if g == "GK"]
    direction = (1.0 if gk_x[0] < 0 else -1.0) if gk_x else None
    return att, dfn, pos, grp, direction


def process_match(root, mid, meta, opp):
    try:
        ev = json.load(open(root / "Event Data" / f"{mid}.json"))
    except Exception:
        return 0
    roster = load_roster(root, mid)
    teams = sorted({t for t in roster.values() if t})
    stage = stage_of(mid)
    n = 0
    for e in ev:
        pe = e.get("possessionEvents") or {}
        if pe.get("possessionEventType") != "PA":
            continue
        passer = pe.get("passerPlayerId"); target = pe.get("targetPlayerId")
        if passer is None or target is None:
            continue
        passer, target = int(passer), int(target)
        ball = (e.get("ball") or [{}]); ball = ball[0] if ball else {}
        if ball.get("x") is None:
            continue
        bx, by = float(ball["x"]), float(ball["y"])
        att, dfn, pos, grp, d = sides(e, passer)
        if not att or target not in pos or grp.get(passer) == "GK" or d is None:
            continue
        m = meta[passer]
        # games-played denominator (per stage): any valid (non-GK) pass = the passer appeared.
        m["by_stage"][stage]["mids"].add(mid)
        tx, ty = pos[target]
        # Score every pass by control x xT-ADDED (no zone gate): the THREAT the pass
        # creates (xT at the target minus xT at the ball's origin), times how well the
        # receiving team controls the target. Build-up passes add ~0 xT so they
        # contribute ~0 with no arbitrary final-third line — and it rewards progression,
        # matching the per-pass xT-added shown on the clip. Orient both ends to attack-+x
        # via d so xT is read at the correct goal. control is orientation-independent.
        xt_dest = xt(tx * d, ty * d)
        xt_gain = xt_dest - xt(bx * d, by * d)
        if xt_gain <= 0:
            continue                                   # only threat-adding passes
        pteam = roster.get(passer, "")
        oteam = next((t for t in teams if t != pteam), "")
        w = opp.weight(oteam) if oteam else 1.0
        att_xy = [(x, y) for i, x, y, _ in att]; dfn_xy = [(x, y) for i, x, y, _ in dfn]
        # control x destination-danger x threat-added: no zone gate, but the xT(dest)
        # term continuously suppresses own-half build-up (xT~0 back there) so high
        # pass VOLUME from deep defenders cannot dominate — only progressive passes
        # INTO dangerous, controlled space score. Surfaces creators, not CBs.
        val = control_at(tx, ty, att_xy, dfn_xy, bx, by) * xt_dest * xt_gain
        m["by_stage"][stage]["valw"] += val * w   # opponent-weighted
        m["by_stage"][stage]["valr"] += val       # raw
        m["n"] += 1
        if not m["name"]:
            m["name"] = pe.get("passerPlayerName") or f"#{passer}"
            m["team"] = pteam
        if grp.get(passer):
            m["pos"][COLLAPSE.get(grp[passer], grp[passer])] += 1
        n += 1
    return n


def _new_meta():
    return {"name": "", "team": "", "pos": Counter(), "n": 0,
            "by_stage": {"group": {"valw": 0.0, "valr": 0.0, "mids": set()},
                         "ko": {"valw": 0.0, "valr": 0.0, "mids": set()}}}


def main():
    root = Path(os.environ.get("PFF_ROOT", str(Path.home() / "pff_wc22_local")))
    ap = argparse.ArgumentParser(); ap.add_argument("--matches", default="")
    ap.add_argument("--min-n", type=int, default=40)
    a = ap.parse_args()
    opp = OppStrength()
    mids = (a.matches.split(",") if a.matches
            else sorted(p.name.replace(".jsonl.bz2", "")
                        for p in (root / "Tracking Data").glob("*.jsonl.bz2")))
    meta = defaultdict(_new_meta)
    tot = 0
    for mid in mids:
        tot += process_match(root, mid, meta, opp)
    rows = [{"name": m["name"], "team": m["team"],
             "pos": (m["pos"].most_common(1)[0][0] if m["pos"] else ""),
             "stages": per_stage_block(m["by_stage"]), "n_passes": m["n"]}
            for m in meta.values() if m["n"] >= a.min_n]
    rows.sort(key=lambda r: -r["stages"]["all"]["total"])
    OUT.write_text(json.dumps({"metric": "Pass selection: controllable danger created (control x xT)",
                               "unit": "sum of pitch-control x xT over a player's passes, opponent-strength weighted",
                               "stages": ["all", "group", "ko"], "opponent_weighted": True,
                               "n_passes": tot, "players": rows}, indent=1))
    print(f"[pass-selection v4] {tot} passes, {len(rows)} passers (stage + opp-weighted)", flush=True)
    for r in rows[:15]:
        g = r["stages"]["group"]; print(f"  all {r['stages']['all']['total']:.2f}  "
              f"grp/match {g['per_match']:.3f}  {r['name']:<22} {r['team']:<12} {r['pos']}", flush=True)


if __name__ == "__main__":
    main()
