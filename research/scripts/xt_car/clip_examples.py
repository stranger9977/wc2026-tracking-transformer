#!/usr/bin/env python3
"""Auto-pick + export the two interactive clips for the "three ways" act.

  surfaces/passing.json — a top creator threading a pass into controllable
      dangerous final-third space. Surface = attacker pitch-control × xT (the same
      dangerous-space field). The passer is ringed; the danger pocket blooms at the
      receiver before the ball arrives.
  surfaces/duel.json    — a ground duel WON against the pitch-control expectation
      (a Balls-Won-Above-Expected upset). Surface = pitch-control locked to the
      duel winner's team; the winner reaches a ball the influence model gave the
      other player. Both contestants ringed.

Both are scrubbable surface windows in the exact schema buildScrubber reads
(matches surfaces/pobso.json). A fast Event-Data scan finds the example; then ONE
match's tracking window is exported per clip via space_io.

Run from the MAIN loop:
  PFF_ROOT=$HOME/pff_wc22_local PYTHONPATH=src \
    uv run python research/scripts/xt_car/clip_examples.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_REPO / "research" / "scripts"), str(_REPO / "src")]

import space_io  # noqa: E402
import pitch_control as pc  # noqa: E402
from wc2026_tracking_transformer.baselines.xt import xt_for_ball  # noqa: E402

HALF_LEN, HALF_WID = pc.HALF_LEN, pc.HALF_WID
FINAL_THIRD_X = 17.5
SAMPLING_STRIDE = 15
RAW_HZ = 30.0
PAD_S = 2.5

SURF_DIR = _REPO / "research" / "site" / "data" / "surfaces"
ROOT = Path(os.environ.get("PFF_ROOT", str(Path.home() / "pff_wc22_local")))
MIDS = sorted(p.name.replace(".jsonl.bz2", "")
              for p in (ROOT / "Tracking Data").glob("*.jsonl.bz2"))

# Recognizable creators / duellers (loose last-name match, accent-insensitive) so the
# auto-pick lands on a face-valid star play rather than an anonymous outlier.
PASS_STARS = ["de paul", "pedri", "messi", "kovacic", "bernardo", "musiala",
              "kramaric", "son", "de bruyne", "modric", "griezmann", "bruno",
              "gundogan", "neymar", "kane"]
DUEL_STARS = ["lozano", "sarr", "vlasic", "kane", "kramaric", "kim", "saliba",
              "romero", "gvardiol", "amrabat", "rodri", "casemiro", "tchouameni"]


# ---- event-scan influence helpers (snapshot-based, for PICKING only) ----
def _pass_infl(px, py, bx, by, tx, ty):
    frac = min(math.hypot(px - bx, py - by) / 18.0, 1.0)
    radius = 4.0 + 6.0 * frac ** 2
    return math.exp(-0.5 * (((tx - px) ** 2 + (ty - py) ** 2) / radius ** 2))


def _pass_control(tx, ty, att, dfn, bx, by):
    sa = sum(_pass_infl(x, y, bx, by, tx, ty) for x, y in att)
    sd = sum(_pass_infl(x, y, bx, by, tx, ty) for x, y in dfn)
    return 1.0 / (1.0 + math.exp(-3.0 * (sa - sd)))


def _duel_infl(px, py, speed, bx, by):
    dx0, dy0 = bx - px, by - py
    dist = math.hypot(dx0, dy0)
    if dist < 1e-6:
        return 1.0
    ux, uy = dx0 / dist, dy0 / dist
    mx, my = px + 0.5 * speed * ux, py + 0.5 * speed * uy
    frac = min(dist / 18.0, 1.0)
    radius = 4.0 + 6.0 * frac ** 2
    sr = min(speed / 13.0, 1.0)
    s_along = radius * (1.0 + sr); s_perp = max(radius * (1.0 - sr), radius * 0.30)
    ex, ey = bx - mx, by - my
    u = ex * ux + ey * uy; w = -ex * uy + ey * ux
    return math.exp(-0.5 * ((u / s_along) ** 2 + (w / s_perp) ** 2))


def _norm(s):
    return (s or "").lower().strip()


def _is_star(name, stars):
    n = _norm(name)
    return any(s in n for s in stars)


def _sides(ev, passer_id):
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
    gk_x = [x for _, x, _, g in att if g == "GK"]
    direction = (1.0 if gk_x[0] < 0 else -1.0) if gk_x else None
    return att, dfn, pos, grp, direction


def _snapshot(ev):
    pos = {}
    for side in ("homePlayers", "awayPlayers"):
        for p in ev.get(side) or []:
            pid = p.get("playerId")
            if pid is not None and p.get("x") is not None:
                pos[int(pid)] = (float(p["x"]), float(p["y"]),
                                 float(p.get("speed") or 0.0), side[:4], p.get("positionGroupType"))
    return pos


def _attack_dir(snap, carrier_id):
    if carrier_id not in snap:
        return None
    side = snap[carrier_id][3]
    gk_x = [xy[0] for pid, xy in snap.items() if xy[3] == side and xy[4] == "GK"]
    return (1.0 if gk_x[0] < 0 else -1.0) if gk_x else None


def _period_of(ev):
    return (ev.get("gameEvents") or {}).get("period")


def _team_id_for_player(meta, ev, pid):
    """Return PFF team id (str) of the side `pid` plays on, from the event snapshot."""
    for side, tkey in (("homePlayers", "homeTeam"), ("awayPlayers", "awayTeam")):
        if any(int(p["playerId"]) == pid for p in (ev.get(side) or []) if p.get("playerId") is not None):
            return str(meta[tkey]["id"])
    return None


# ---------------------------------------------------------------------------
# Pickers (Event-Data scan).
# ---------------------------------------------------------------------------
def pick_passing():
    """Highest control×xT penetrating final-third pass by a recognizable creator."""
    best = None  # (score, mid, period, gc, passer_name, recv_name, passer_id, recv_id, ctrl, xtv)
    fallback = None
    for mid in MIDS:
        try:
            ev = json.load(open(ROOT / "Event Data" / f"{mid}.json"))
        except Exception:
            continue
        for e in ev:
            pe = e.get("possessionEvents") or {}
            if pe.get("possessionEventType") != "PA":
                continue
            passer = pe.get("passerPlayerId"); target = pe.get("targetPlayerId")
            gc = pe.get("gameClock"); period = _period_of(e)
            if passer is None or target is None or gc is None or period not in (1, 2):
                continue
            passer, target = int(passer), int(target)
            ball = (e.get("ball") or [{}]); ball = ball[0] if ball else {}
            if ball.get("x") is None:
                continue
            bx, by = float(ball["x"]), float(ball["y"])
            att, dfn, pos, grp, d = _sides(e, passer)
            if not att or target not in pos or grp.get(passer) == "GK" or d is None:
                continue
            tx, ty = pos[target]
            if tx * d <= FINAL_THIRD_X:                 # target in attacking third
                continue
            px, py = pos.get(passer, (None, None))
            if px is None or math.hypot(tx - px, ty - py) < 12.0:   # penetrating only
                continue
            xtv = xt_for_ball((tx * d) / HALF_LEN, ty / HALF_WID)   # oriented to attack +x
            if xtv < 0.05:
                continue
            att_xy = [(x, y) for _, x, y, _ in att]; dfn_xy = [(x, y) for _, x, y, _ in dfn]
            ctrl = _pass_control(tx, ty, att_xy, dfn_xy, bx, by)
            if ctrl < 0.6:                              # receiver genuinely in space
                continue
            score = ctrl * xtv
            pname = pe.get("passerPlayerName") or ""
            rname = pe.get("targetPlayerName") or ""
            cand = (score, mid, int(period), float(gc), pname, rname, passer, target,
                    round(ctrl, 3), round(float(xtv), 4))
            if fallback is None or score > fallback[0]:
                fallback = cand
            if _is_star(pname, PASS_STARS) and (best is None or score > best[0]):
                best = cand
    return best or fallback


def pick_duel():
    """Biggest BWAE upset: a recognizable player wins a ground duel the influence
    model gave the OTHER player."""
    best = None  # (upset, mid, period, gc, win_name, los_name, win_id, los_id, exp_win)
    fallback = None
    for mid in MIDS:
        try:
            ev = json.load(open(ROOT / "Event Data" / f"{mid}.json"))
        except Exception:
            continue
        for e in ev:
            pe = e.get("possessionEvents") or {}
            if pe.get("possessionEventType") != "CH":
                continue
            win = pe.get("challengeWinnerPlayerId")
            gc = pe.get("gameClock"); period = _period_of(e)
            if win is None or gc is None or period not in (1, 2):
                continue
            ball = (e.get("ball") or [{}]); ball = ball[0] if ball else {}
            if ball.get("x") is None or (ball.get("z") is not None and ball["z"] >= 1.0):
                continue
            bx, by = float(ball["x"]), float(ball["y"])
            carrier = pe.get("ballCarrierPlayerId") or pe.get("carrierPlayerId")
            a = carrier or pe.get("homeDuelPlayerId")
            b = pe.get("challengerPlayerId") or pe.get("awayDuelPlayerId")
            if a is None or b is None or a == b:
                continue
            a, b, win = int(a), int(b), int(win)
            snap = _snapshot(e)
            if a not in snap or b not in snap or win not in (a, b):
                continue
            # require a REAL contest: both contestants near the ball AND near each
            # other (a genuine 50-50), not a loose ball one player ran onto from
            # distance (which scores a degenerate ~0 expected win).
            da = math.hypot(snap[a][0] - bx, snap[a][1] - by)
            db = math.hypot(snap[b][0] - bx, snap[b][1] - by)
            dab = math.hypot(snap[a][0] - snap[b][0], snap[a][1] - snap[b][1])
            if da > 5.0 or db > 5.0 or dab > 5.0:
                continue
            ia = _duel_infl(snap[a][0], snap[a][1], snap[a][2], bx, by)
            ib = _duel_infl(snap[b][0], snap[b][1], snap[b][2], bx, by)
            if ia + ib < 1e-9:
                continue
            loser = b if win == a else a
            exp_win = (ia / (ia + ib)) if win == a else (ib / (ia + ib))
            if not (0.18 <= exp_win <= 0.42):          # believable underdog, not a fluke
                continue
            names = {a: pe.get("ballCarrierPlayerName") or pe.get("carrierPlayerName") or "",
                     b: pe.get("challengerPlayerName") or ""}
            upset = 1.0 - exp_win
            cand = (upset, mid, int(period), float(gc), names.get(win, ""), names.get(loser, ""),
                    win, loser, round(exp_win, 3))
            if fallback is None or upset > fallback[0]:
                fallback = cand
            if _is_star(names.get(win, ""), DUEL_STARS) and (best is None or upset > best[0]):
                best = cand
    return best or fallback


# ---------------------------------------------------------------------------
# Tracking-window export (shared) — emits the buildScrubber surface schema.
# ---------------------------------------------------------------------------
def export_window(mid, period, t_center, lock_team_id, kind, hero):
    grid = pc.make_grid(nx=40, ny=26)
    xt_grid = pc.xt_surface(grid)
    # PFF event gameClock is cumulative (period 2 starts at 2700 s = 45:00); tracking
    # periodElapsedTime resets to 0 each period. Convert to period-elapsed to align.
    t_center = t_center - 2700.0 * (period - 1)
    start_s, end_s = max(0.0, t_center - PAD_S), t_center + PAD_S
    frames_out, raw_maxes = [], []
    for fr in space_io.read_match(mid, sampling_stride=SAMPLING_STRIDE,
                                  periods=(period,), lock_attack_team_id=lock_team_id):
        if fr.timestamp_s < start_s or fr.timestamp_s > end_s:
            continue
        ctrl = pc.control_surface(fr.players, fr.ball_m, grid, include_gk=True)
        surf = ctrl["attack_control"] * xt_grid if kind == "danger" else ctrl["attack_control"]
        rmax = float(surf.max()); raw_maxes.append(rmax)
        markers = [{
            "x": round(float(fr.players[i, 0] * HALF_LEN), 1),
            "y": round(float(fr.players[i, 1] * HALF_WID), 1),
            "att": bool(fr.players[i, 4] > 0), "gk": bool(fr.players[i, 5] > 0.5),
            "name": ident.name, "vis": ident.visibility,
        } for i, ident in enumerate(fr.identities)]
        frames_out.append({
            "t_s": round(fr.timestamp_s, 2),
            "ball_xy": [round(float(fr.ball_m[0]), 1), round(float(fr.ball_m[1]), 1)],
            "in_possession_team": fr.in_possession_team,
            "surface_raw": surf, "raw_max": round(rmax, 5), "players": markers,
        })
    if not frames_out:
        return None
    gmax = max(raw_maxes) or 1.0
    for f in frames_out:
        s = f.pop("surface_raw") / gmax
        f["surface"] = [[round(float(v), 4) for v in row] for row in s]
    xt_ref = xt_grid / (xt_grid.max() or 1.0)
    return {
        "match_id": mid, "period": period,
        "start_s": round(start_s, 1), "end_s": round(end_s, 1),
        "peak_t_s": round(t_center, 2),
        "hz": round(RAW_HZ / SAMPLING_STRIDE, 2), "n_frames": len(frames_out),
        "grid": {"nx": grid.nx, "ny": grid.ny, "length_m": 105.0, "width_m": 68.0},
        "global_max": round(gmax, 5),
        "xt_reference": [[round(float(v), 4) for v in row] for row in xt_ref],
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "hero": hero, "frames": frames_out,
    }


def main():
    SURF_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # ---- PASSING ----
    print("[passing] scanning Event Data for best penetrating final-third pass...", flush=True)
    pk = pick_passing()
    if pk is None:
        print("[passing] no candidate found", flush=True)
    else:
        score, mid, period, gc, pname, rname, pid, rid, ctrl, xtv = pk
        meta = space_io.load_metadata(mid)
        lock = _team_id_for_player(meta, json.load(open(ROOT / "Event Data" / f"{mid}.json"))[0], pid) \
            if False else None
        # team id of the passer (lock orientation to the passing team)
        ev0 = json.load(open(ROOT / "Event Data" / f"{mid}.json"))
        lock = None
        for e in ev0:
            tid = _team_id_for_player(meta, e, pid)
            if tid:
                lock = tid; break
        hero = {"name": pname, "receiver": rname,
                "team": meta["homeTeam"]["name"] if lock == str(meta["homeTeam"]["id"]) else meta["awayTeam"]["name"],
                "control": ctrl, "xt": xtv, "value": round(score, 4)}
        print(f"[passing] {pname} -> {rname} ({mid} p{period} {gc:.1f}s) "
              f"control={ctrl} xt={xtv} value={score:.4f}", flush=True)
        payload = export_window(mid, period, gc, lock, "danger", hero)
        if payload:
            payload.update({
                "metric": "passing",
                "title": f"Finding dangerous space: {pname}'s pass into the final third",
                "description": (f"{pname} threads a pass into controllable, dangerous space — "
                                "the surface is attacker pitch-control × Expected Threat, so the "
                                "bright pocket is grass the receiving team both OWNS and can score "
                                "from. Watch it bloom at the receiver before the ball arrives."),
                "match": f"{meta['homeTeam']['name']} v {meta['awayTeam']['name']}",
            })
            (SURF_DIR / "passing.json").write_text(json.dumps(payload))
            print(f"[passing] wrote surfaces/passing.json ({payload['n_frames']} frames)", flush=True)

    # ---- DUEL ----
    print("[duel] scanning Event Data for biggest BWAE upset...", flush=True)
    dk = pick_duel()
    if dk is None:
        print("[duel] no candidate found", flush=True)
    else:
        upset, mid, period, gc, wname, lname, wid, lid, exp_win = dk
        meta = space_io.load_metadata(mid)
        ev0 = json.load(open(ROOT / "Event Data" / f"{mid}.json"))
        lock = None
        for e in ev0:
            tid = _team_id_for_player(meta, e, wid)
            if tid:
                lock = tid; break
        hero = {"name": wname, "loser": lname,
                "team": meta["homeTeam"]["name"] if lock == str(meta["homeTeam"]["id"]) else meta["awayTeam"]["name"],
                "expected_win": exp_win, "expected_pct": round(exp_win * 100)}
        print(f"[duel] {wname} beat {lname} ({mid} p{period} {gc:.1f}s) "
              f"expected_win={exp_win} (upset={upset:.3f})", flush=True)
        payload = export_window(mid, period, gc, lock, "control", hero)
        if payload:
            payload.update({
                "metric": "duel",
                "title": f"Winning the ball against the odds: {wname}",
                "description": (f"Pitch control gave {lname} the edge on this ground duel "
                                f"({round(exp_win*100)}% to win it), but {wname} got there first. "
                                "The surface is pitch control locked to the winner's team — he "
                                "reaches a contested ball his positioning said he should lose."),
                "match": f"{meta['homeTeam']['name']} v {meta['awayTeam']['name']}",
            })
            (SURF_DIR / "duel.json").write_text(json.dumps(payload))
            print(f"[duel] wrote surfaces/duel.json ({payload['n_frames']} frames)", flush=True)

    print(f"\nEXIT_OK ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
