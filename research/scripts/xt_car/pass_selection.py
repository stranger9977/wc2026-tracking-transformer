#!/usr/bin/env python3
"""Pass Selection vs Pitch Control (friend's #1) — v6: progression + occupation, dual-zone.

TWO complementary metrics per passer, so the front end can toggle which question it asks:
  * PROGRESSION  = sum control_at_target x xT(target) x xT-ADDED, over threat-adding passes.
                   "Who THREADS the ball forward into more danger." xT(dest) suppresses own-half
                   build-up and xT-added rewards line-breaking, so creators surface, not CBs.
  * OCCUPATION   = sum control_at_target x xT(target), over EVERY completed pass (no xT-added).
                   "Who LIVES in dangerous, controlled space." Volume-weighted, so high-tempo
                   circulators who hold + recycle in good areas (Pedri, Kovacic) surface — the
                   progression metric demotes them because their passes add ~0 threat.

Each metric in two zones (front end toggles, all share the games-played denominator so per-match
is comparable across every toggle):
  * "all"  — the whole pitch.   * "f3" — only passes whose TARGET is in the attacking final third.
GKs excluded. Orient both ends to attack-+x so xT is read at the correct goal.
Per passer: total (volume x quality) + per-match, opponent-weighted + raw, team + position.

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

# Value layer: static xT (default) or the ball-conditioned paper V model (SPACE_VALUE=v),
# so the passing board can be regenerated under either value model for the site toggle.
_VALMODE = "xt"
_VMODEL = None


def _val(ball_xy, cell_xy):
    """Value of a cell given the ball — xT (ball-blind) or the paper V (ball-conditioned)."""
    if _VALMODE == "v":
        import space_value_model as svm  # noqa: E402
        return svm.value_point(ball_xy, cell_xy, _VMODEL)
    return xt(cell_xy[0], cell_xy[1])


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
        # Orient both ends to attack-+x via d so xT is read at the correct goal; control is
        # orientation-independent. We score TWO complementary metrics per pass (the board toggles):
        #   OCCUPATION  = control x xT(dest)            — did the ball land in dangerous, CONTROLLED
        #                                                 space? Volume-weighted, every completed pass.
        #                                                 Rewards circulators who LIVE in good areas
        #                                                 (Pedri/Kovacic), holding + recycling there.
        #   PROGRESSION = control x xT(dest) x xT-added — did the pass MOVE the ball to MORE danger?
        #                                                 Only threat-adding passes; rewards line-
        #                                                 breaking creators (de Paul/Messi), not CB
        #                                                 build-up volume (xT(dest)~0 in own half).
        xt_dest = _val((bx * d, by * d), (tx * d, ty * d))
        xt_gain = xt_dest - _val((bx * d, by * d), (bx * d, by * d))
        pteam = roster.get(passer, "")
        oteam = next((t for t in teams if t != pteam), "")
        w = opp.weight(oteam) if oteam else 1.0
        att_xy = [(x, y) for i, x, y, _ in att]; dfn_xy = [(x, y) for i, x, y, _ in dfn]
        c = control_at(tx, ty, att_xy, dfn_xy, bx, by)
        st = m["by_stage"][stage]
        in_f3 = tx * d > FINAL_THIRD_X
        occ = c * xt_dest                              # OCCUPATION — all passes, no xT-added gate
        st["occ_w"] += occ * w; st["occ_r"] += occ
        if in_f3:
            st["occ_w_f3"] += occ * w; st["occ_r_f3"] += occ
        if xt_gain > 0:                                # PROGRESSION — threat-adding passes only
            val = occ * xt_gain
            st["valw"] += val * w; st["valr"] += val
            if in_f3:
                st["valw_f3"] += val * w; st["valr_f3"] += val
        m["n"] += 1
        if not m["name"]:
            m["name"] = pe.get("passerPlayerName") or f"#{passer}"
            m["team"] = pteam
        if grp.get(passer):
            m["pos"][COLLAPSE.get(grp[passer], grp[passer])] += 1
        n += 1
    return n


def _new_meta():
    z = lambda: {"valw": 0.0, "valr": 0.0, "valw_f3": 0.0, "valr_f3": 0.0,
                 "occ_w": 0.0, "occ_r": 0.0, "occ_w_f3": 0.0, "occ_r_f3": 0.0, "mids": set()}
    return {"name": "", "team": "", "pos": Counter(), "n": 0,
            "by_stage": {"group": z(), "ko": z()}}


def _view(by_stage, wk, rk):
    """Remap a chosen (weighted, raw) sub-total pair into the {valw,valr,mids} shape
    per_stage_block wants. mids (games played) is shared across all views so per-match
    uses the same denominator regardless of metric/zone."""
    return {st: {"valw": d[wk], "valr": d[rk], "mids": d["mids"]}
            for st, d in by_stage.items()}


def main():
    global _VALMODE, _VMODEL
    root = Path(os.environ.get("PFF_ROOT", str(Path.home() / "pff_wc22_local")))
    ap = argparse.ArgumentParser(); ap.add_argument("--matches", default="")
    ap.add_argument("--min-n", type=int, default=40)
    a = ap.parse_args()
    out_path = OUT
    if os.environ.get("SPACE_VALUE") == "v":
        import space_value_model as svm  # noqa: E402
        _VALMODE, _VMODEL = "v", svm.load_model()
        out_path = OUT.with_name("pass_selection_v.json")
        print("[value] SPACE_VALUE=v — passing scored with the Fernández–Bornn pitch-value model", flush=True)
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
             "stages": per_stage_block(_view(m["by_stage"], "valw", "valr")),
             "stages_f3": per_stage_block(_view(m["by_stage"], "valw_f3", "valr_f3")),
             "stages_occ": per_stage_block(_view(m["by_stage"], "occ_w", "occ_r")),
             "stages_occ_f3": per_stage_block(_view(m["by_stage"], "occ_w_f3", "occ_r_f3")),
             "n_passes": m["n"]}
            for m in meta.values() if m["n"] >= a.min_n]
    rows.sort(key=lambda r: -r["stages"]["all"]["total"])
    out_path.write_text(json.dumps({"metric": "Pass selection: progression (control x xT(dest) x xT-added) + occupation (control x xT(dest))",
                               "unit": "sum over a player's passes, opponent-strength weighted; progression=threat added, occupation=lands in dangerous controlled space",
                               "stages": ["all", "group", "ko"], "zones": ["all", "f3"],
                               "metrics": ["progression", "occupation"],
                               "opponent_weighted": True,
                               "n_passes": tot, "players": rows}, indent=1))
    print(f"[pass-selection v6] {tot} passes, {len(rows)} passers (progression + occupation)", flush=True)
    for metric, key in (("PROGRESSION", "stages"), ("OCCUPATION", "stages_occ")):
        top = sorted(rows, key=lambda r: -r[key]["all"]["total"])
        pedri = next(((i + 1, r) for i, r in enumerate(top) if "Pedri" in r["name"]), None)
        print(f"  --- {metric} (all, total) — Pedri rank: "
              f"{pedri[0] if pedri else '—'} ---", flush=True)
        for r in top[:6]:
            print(f"    {r[key]['all']['total']:.3f}  {r['name']:<22} {r['team']:<12} {r['pos']}", flush=True)


if __name__ == "__main__":
    main()
