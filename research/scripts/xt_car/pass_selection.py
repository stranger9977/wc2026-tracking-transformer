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


def process_match(root, mid, meta):
    try:
        ev = json.load(open(root / "Event Data" / f"{mid}.json"))
    except Exception:
        return 0
    roster = load_roster(root, mid)
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
        # games-played denominator: any valid (non-GK) pass counts the passer as
        # having appeared in this match, so per-match divides by games played, not
        # games-with-a-final-third-pass (consistent with build_xt_created.py).
        meta[passer]["mids"].add(mid)
        tx, ty = pos[target]
        if tx * d <= FINAL_THIRD_X:
            continue
        att_xy = [(x, y) for i, x, y, _ in att]; dfn_xy = [(x, y) for i, x, y, _ in dfn]
        val = control_at(tx, ty, att_xy, dfn_xy, bx, by) * xt(tx, ty)
        m = meta[passer]
        m["val"] += val; m["n"] += 1
        if not m["name"]:
            m["name"] = pe.get("passerPlayerName") or f"#{passer}"
            m["team"] = roster.get(passer, "")
        if grp.get(passer):
            m["pos"][COLLAPSE.get(grp[passer], grp[passer])] += 1
        n += 1
    return n


def main():
    root = Path(os.environ.get("PFF_ROOT", str(Path.home() / "pff_wc22_local")))
    ap = argparse.ArgumentParser(); ap.add_argument("--matches", default="")
    ap.add_argument("--min-n", type=int, default=40)
    a = ap.parse_args()
    mids = (a.matches.split(",") if a.matches
            else sorted(p.name.replace(".jsonl.bz2", "")
                        for p in (root / "Tracking Data").glob("*.jsonl.bz2")))
    meta = defaultdict(lambda: {"val": 0.0, "n": 0, "name": "", "team": "", "pos": Counter(),
                                "mids": set()})
    tot = 0
    for mid in mids:
        tot += process_match(root, mid, meta)
    rows = [{"name": m["name"], "team": m["team"],
             "pos": (m["pos"].most_common(1)[0][0] if m["pos"] else ""),
             "total": m["val"], "per_pass": m["val"] / m["n"],
             "per_match": m["val"] / max(1, len(m["mids"])),
             "matches": len(m["mids"]), "n_ft_passes": m["n"]}
            for m in meta.values() if m["n"] >= a.min_n]
    rows.sort(key=lambda r: -r["total"])
    OUT.write_text(json.dumps({"metric": "Pass selection: final-third controllable danger",
                               "unit": "sum of pitch-control x xT over final-third passes (xT units)",
                               "n_ft_passes": tot, "players": rows}, indent=1))
    print(f"[pass-selection v3] {tot} FT passes, {len(rows)} passers", flush=True)
    for r in rows[:15]:
        print(f"  {r['total']:.2f}  {r['name']:<22} {r['team']:<12} {r['pos']:<4} (n={r['n_ft_passes']})", flush=True)


if __name__ == "__main__":
    main()
