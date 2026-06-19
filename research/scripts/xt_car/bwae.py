#!/usr/bin/env python3
"""Balls Won Above Expected (BWAE) — ground duels won vs pitch-control expectation.

Two leaderboards: ALL ground duels, and FINAL-THIRD ground duels (higher-stakes
contests in the attacking third — winning a 50-50 there is worth more).

Per PFF ground challenge (CH event, ball z < GROUND_Z so headers are excluded):
  - contestants = (ballCarrier, challenger) or (home/away dueler)
  - at the ball location, each contestant's Fernandez-Bornn influence (position +
    speed pointed at the ball) -> P(A wins) = infl_A / (infl_A+infl_B)
  - actual = 1 if he is challengeWinnerPlayerId
  - BWAE(player) = mean(actual - expected) over his ground duels
Final-third = ball in the ball-carrier's attacking third (direction inferred from
that team's GK position in the per-event snapshot).

Reads ONLY PFF Event Data (+ Rosters) locally; fast.
Run:  PFF_ROOT=$HOME/pff_wc22_local PYTHONPATH=src \
        uv run python research/scripts/xt_car/bwae.py
Output: research/site/data/balls_won_above_expected.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_REPO / "research" / "scripts"), str(_REPO / "src")]
try:
    import pitch_control as _pc
    R_MIN = getattr(_pc, "INFLUENCE_R_MIN", 4.0); R_MAX = getattr(_pc, "INFLUENCE_R_MAX", 10.0)
    BALL_SAT = getattr(_pc, "BALL_DIST_SAT", 18.0); SPN = getattr(_pc, "SPEED_NORM", 13.0)
    REACT = getattr(_pc, "REACTION_S", 0.5)
except Exception:
    R_MIN, R_MAX, BALL_SAT, SPN, REACT = 4.0, 10.0, 18.0, 13.0, 0.5
try:
    from wc2026_tracking_transformer.baselines.xt import xt_for_ball
except Exception:
    xt_for_ball = None
HALF_LEN, HALF_WID = 52.5, 34.0


def xt_dir(x, y, d):
    """xT at world (x,y) seen by a team attacking direction d (+1 toward +x, -1 toward -x).
    Returns 0 when direction is unknown so a duel only earns xT weight when we can
    orient it (a CB clearing his own box gets ~0 weight; a 50-50 in the box, a lot)."""
    if xt_for_ball is None or d is None:
        return 0.0
    return float(xt_for_ball(x * d / HALF_LEN, y / HALF_WID))

GROUND_Z = 1.0
FINAL_THIRD_X = 17.5    # m past halfway = attacking third
COLLAPSE = {"RCB": "CB", "LCB": "CB", "RB": "RB", "LB": "LB", "RWB": "RB", "LWB": "LB",
            "RW": "RW", "LW": "LW", "CF": "CF", "ST": "CF", "AM": "AM", "CM": "CM",
            "DM": "DM", "GK": "GK", "RM": "RM", "LM": "LM"}
OUT = _REPO / "research" / "site" / "data" / "balls_won_above_expected.json"


def influence_at_ball(px, py, speed, bx, by):
    dx0, dy0 = bx - px, by - py
    dist = math.hypot(dx0, dy0)
    if dist < 1e-6:
        return 1.0
    ux, uy = dx0 / dist, dy0 / dist
    vx, vy = speed * ux, speed * uy
    mx, my = px + REACT * vx, py + REACT * vy
    frac = min(dist / BALL_SAT, 1.0)
    radius = R_MIN + (R_MAX - R_MIN) * frac ** 2
    sratio = min(speed / SPN, 1.0)
    s_along = radius * (1.0 + sratio); s_perp = max(radius * (1.0 - sratio), radius * 0.30)
    ex, ey = bx - mx, by - my
    u = ex * ux + ey * uy; w = -ex * uy + ey * ux
    return math.exp(-0.5 * ((u / s_along) ** 2 + (w / s_perp) ** 2))


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
            out[int(pid)] = {"team": team if isinstance(team, str) else ""}
    return out


def snapshot(ev):
    """playerId -> (x,y,speed,side,posgrp)."""
    pos = {}
    for side in ("homePlayers", "awayPlayers"):
        for p in ev.get(side) or []:
            pid = p.get("playerId")
            if pid is not None and p.get("x") is not None:
                pos[int(pid)] = (float(p["x"]), float(p["y"]), float(p.get("speed") or 0.0),
                                 side[:4], p.get("positionGroupType"))
    return pos


def attack_dir(snap, carrier_id):
    """+1 if carrier's team attacks +x, -1 if -x, None if undetermined.
    Inferred from that team's GK x (GK sits at the defensive end)."""
    if carrier_id not in snap:
        return None
    side = snap[carrier_id][3]
    gk_x = [xy[0] for pid, xy in snap.items() if xy[3] == side and xy[4] == "GK"]
    if not gk_x:
        return None
    return 1.0 if gk_x[0] < 0 else -1.0


def process_match(root, mid, acc_all, acc_f3, names, pmatches):
    try:
        ev = json.load(open(root / "Event Data" / f"{mid}.json"))
    except Exception:
        return (0, 0)
    roster = load_roster(root, mid)
    n_all = n_f3 = 0
    for e in ev:
        pe = e.get("possessionEvents") or {}
        if pe.get("possessionEventType") != "CH":
            continue
        win = pe.get("challengeWinnerPlayerId")
        if win is None:
            continue
        ball = (e.get("ball") or [{}]); ball = ball[0] if ball else {}
        if ball.get("x") is None or (ball.get("z") is not None and ball["z"] >= GROUND_Z):
            continue
        bx, by = float(ball["x"]), float(ball["y"])
        carrier = pe.get("ballCarrierPlayerId") or pe.get("carrierPlayerId")
        a = carrier or pe.get("homeDuelPlayerId")
        b = pe.get("challengerPlayerId") or pe.get("awayDuelPlayerId")
        if a is None or b is None or a == b:
            continue
        a, b, win = int(a), int(b), int(win)
        snap = snapshot(e)
        if a not in snap or b not in snap:
            continue
        ia = influence_at_ball(snap[a][0], snap[a][1], snap[a][2], bx, by)
        ib = influence_at_ball(snap[b][0], snap[b][1], snap[b][2], bx, by)
        if ia + ib < 1e-9:
            continue
        exp_a = ia / (ia + ib)
        d = attack_dir(snap, int(carrier)) if carrier else None
        in_f3 = d is not None and (bx * d) > FINAL_THIRD_X
        # xT of the contest from each contestant's OWN attacking direction (carrier a
        # attacks d, challenger b attacks -d), so a duel is weighted by how dangerous
        # winning it is FOR THE WINNER.
        wa = xt_dir(bx, by, d)
        wb = xt_dir(bx, by, (-d) if d is not None else None)
        for pid, nm, res, wt in ((a, pe.get("ballCarrierPlayerName") or pe.get("carrierPlayerName"),
                                  (1.0 if win == a else 0.0) - exp_a, wa),
                                 (b, pe.get("challengerPlayerName"),
                                  (1.0 if win == b else 0.0) - (1.0 - exp_a), wb)):
            if pid not in names:
                g = snap[pid][4]
                names[pid] = {"name": nm or f"#{pid}", "team": roster.get(pid, {}).get("team", ""),
                              "pos": (COLLAPSE.get(g, g) if g else "")}
            acc_all[pid]["res"] += res; acc_all[pid]["n"] += 1
            acc_all[pid]["xtw"] += wt * res; pmatches[pid].add(mid)
            if in_f3:
                acc_f3[pid]["res"] += res; acc_f3[pid]["n"] += 1
        n_all += 1; n_f3 += 1 if in_f3 else 0
    return (n_all, n_f3)


def board(acc, names, min_n):
    rows = [{"name": names[p]["name"], "team": names[p]["team"], "pos": names[p].get("pos", ""),
             "bwae_per_duel": acc[p]["res"] / acc[p]["n"], "n_duels": acc[p]["n"]}
            for p in acc if acc[p]["n"] >= min_n]
    rows.sort(key=lambda r: -r["bwae_per_duel"])
    return rows


def board_xt(acc, names, min_n, pmatches):
    """xT-weighted Balls Won Above Expected: sum over a player's ground duels of
    xT(contest) x (won - expected). Wins in dangerous areas above the odds dominate;
    own-half clearances barely register. Per-match = the sum / matches with a duel."""
    rows = []
    for p in acc:
        if acc[p]["n"] < min_n:
            continue
        m = len(pmatches.get(p, ()))
        rows.append({"name": names[p]["name"], "team": names[p]["team"], "pos": names[p].get("pos", ""),
                     "bwae_xt": acc[p]["xtw"], "bwae_xt_per_match": acc[p]["xtw"] / max(1, m),
                     "bwae_per_duel": acc[p]["res"] / acc[p]["n"], "n_duels": acc[p]["n"], "matches": m})
    rows.sort(key=lambda r: -r["bwae_xt"])
    return rows


def main():
    root = Path(os.environ.get("PFF_ROOT", str(Path.home() / "pff_wc22_local")))
    ap = argparse.ArgumentParser(); ap.add_argument("--matches", default="")
    ap.add_argument("--min-n", type=int, default=40); ap.add_argument("--min-n-f3", type=int, default=15)
    ap.add_argument("--min-n-xt", type=int, default=25)
    a = ap.parse_args()
    mids = (a.matches.split(",") if a.matches
            else sorted(p.name.replace(".jsonl.bz2", "")
                        for p in (root / "Tracking Data").glob("*.jsonl.bz2")))
    acc_all = defaultdict(lambda: {"res": 0.0, "n": 0, "xtw": 0.0})
    acc_f3 = defaultdict(lambda: {"res": 0.0, "n": 0}); names = {}
    pmatches = defaultdict(set)
    t_all = t_f3 = 0
    for mid in mids:
        na, nf = process_match(root, mid, acc_all, acc_f3, names, pmatches); t_all += na; t_f3 += nf
    all_b = board(acc_all, names, a.min_n); f3_b = board(acc_f3, names, a.min_n_f3)
    xt_b = board_xt(acc_all, names, a.min_n_xt, pmatches)
    OUT.write_text(json.dumps({"metric": "Balls Won Above Expected (ground duels), xT-weighted",
                               "n_ground_duels": t_all, "n_final_third": t_f3,
                               "players": xt_b, "all": all_b, "final_third": f3_b}, indent=1))
    print(f"[BWAE] {t_all} ground duels ({t_f3} in final third)", flush=True)
    print(f"\nTOP 12 — xT-WEIGHTED (sum of xT x above-expected):", flush=True)
    for r in xt_b[:12]:
        print(f"  {r['bwae_xt']:+.3f}  {r['name']:<24} {r['team']:<12} (n={r['n_duels']}, raw {r['bwae_per_duel']*100:+.0f}%)", flush=True)


if __name__ == "__main__":
    main()
