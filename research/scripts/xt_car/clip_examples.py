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
    """Ranked ground-duel (CH) candidates with a recognizable winner. The event
    snapshot's positions disagree with the 30 Hz tracking, so we do NOT trust the
    snapshot geometry here — these are validated against the TRACKING downstream
    (validate_export_duel) so the displayed contest matches the stated odds."""
    cands = []
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
            carrier = pe.get("ballCarrierPlayerId") or pe.get("carrierPlayerId")
            a = carrier or pe.get("homeDuelPlayerId")
            b = pe.get("challengerPlayerId") or pe.get("awayDuelPlayerId")
            if a is None or b is None or a == b:
                continue
            a, b, win = int(a), int(b), int(win)
            if win not in (a, b):
                continue
            loser = b if win == a else a
            names = {a: pe.get("ballCarrierPlayerName") or pe.get("carrierPlayerName") or "",
                     b: pe.get("challengerPlayerName") or ""}
            wname, lname = names.get(win, ""), names.get(loser, "")
            if not wname or not lname:
                continue
            score = 10 if _is_star(wname, DUEL_STARS) else 0
            cands.append((score, mid, int(period), float(gc), win, wname, loser, lname))
    cands.sort(key=lambda c: -c[0])
    return cands


def validate_export_duel(mid, period, gc, win_id, wname, los_id, lname):
    """Read the TRACKING around the duel, find the genuine contest frame (both
    contestants closest to the ball), compute the F&B win-probability THERE, and
    export only if it's a real, in-frame 50-50 the WINNER was the underdog in —
    so the clip's geometry matches the stated odds. Returns payload or None."""
    meta = space_io.load_metadata(mid)
    ev0 = json.load(open(ROOT / "Event Data" / f"{mid}.json"))
    lock = None
    for e in ev0:
        tid = _team_id_for_player(meta, e, win_id)
        if tid:
            lock = tid; break
    if lock is None:
        return None
    t_center = gc - 2700.0 * (period - 1)
    found = []
    for fr in space_io.read_match(mid, sampling_stride=SAMPLING_STRIDE,
                                  periods=(period,), lock_attack_team_id=lock):
        if abs(fr.timestamp_s - t_center) > 3.0:
            continue
        wi = li = None
        for i, ident in enumerate(fr.identities):
            if ident.name == wname:
                wi = i
            elif ident.name == lname:
                li = i
        if wi is None or li is None:
            continue
        bx, by = float(fr.ball_m[0]), float(fr.ball_m[1])
        wx, wy = fr.players[wi, 0] * HALF_LEN, fr.players[wi, 1] * HALF_WID
        lx, ly = fr.players[li, 0] * HALF_LEN, fr.players[li, 1] * HALF_WID
        wsp = math.hypot(fr.players[wi, 2], fr.players[wi, 3])
        lsp = math.hypot(fr.players[li, 2], fr.players[li, 3])
        found.append({"t": fr.timestamp_s, "dw": math.hypot(wx - bx, wy - by),
                      "dl": math.hypot(lx - bx, ly - by), "bx": bx, "by": by,
                      "wx": wx, "wy": wy, "wsp": wsp, "lx": lx, "ly": ly, "lsp": lsp,
                      "wvis": fr.identities[wi].visibility, "lvis": fr.identities[li].visibility})
    if not found:
        return None
    c = min(found, key=lambda f: max(f["dw"], f["dl"]))   # the genuine contest moment
    # must be a real, in-frame 50-50 both players actually contest, both VISIBLE
    if c["dw"] > 3.5 or c["dl"] > 3.5 or c["wvis"] != "VISIBLE" or c["lvis"] != "VISIBLE":
        return None
    if abs(c["bx"]) > 38.0 or abs(c["by"]) > 22.0:
        return None
    iw = _duel_infl(c["wx"], c["wy"], c["wsp"], c["bx"], c["by"])
    il = _duel_infl(c["lx"], c["ly"], c["lsp"], c["bx"], c["by"])
    if iw + il < 1e-9:
        return None
    exp_win = iw / (iw + il)
    if exp_win > 0.45:                  # the WINNER must be the underdog at the contest
        return None
    hero = {"name": wname, "loser": lname, "team": _teams_block(meta, lock)["attack"],
            "expected_win": round(exp_win, 3), "expected_pct": round(exp_win * 100)}
    payload = export_window(mid, period, c["t"] + 2700.0 * (period - 1), lock, "control", hero,
                            teams=_teams_block(meta, lock), pre=3.5, post=0.8, anchor_name=wname)
    if payload:
        payload.update({
            "metric": "duel",
            "title": f"Winning the ball against the odds: {wname}",
            "match": f"{meta['homeTeam']['name']} v {meta['awayTeam']['name']}",
            "description": (f"A genuine 50-50: pitch control favoured {lname} ({round((1-exp_win)*100)}%), "
                            f"but {wname} reached it first."),
        })
    return payload


# ---------------------------------------------------------------------------
# Tracking-window export (shared) — emits the buildScrubber surface schema.
# ---------------------------------------------------------------------------
def export_window(mid, period, t_center, lock_team_id, kind, hero,
                  teams=None, pre=PAD_S, post=PAD_S, stride=SAMPLING_STRIDE, anchor_name=None):
    """Export a scrubbable surface window.

    teams       {attack, defend} team names for the on-clip legend.
    pre/post    seconds before/after the centre (asymmetric — lead in, end on the moment).
    stride      tracking sampling stride; smaller = more frames = smoother motion
                (used for fast runs so the hero doesn't jump between sparse frames).
    anchor_name if set, re-centre the window on the frame where that player is CLOSEST
                to the ball (the true contest/win moment), since the PFF event clock can
                lag the tracking — so a duel clip ends on the win, not the aftermath.
    Returns per-frame `obso_owned` for the hero (peak control×xT cell) when kind=='danger'."""
    grid = pc.make_grid(nx=40, ny=26)
    xt_grid = pc.xt_surface(grid)
    # PFF event gameClock is cumulative (period 2 starts at 2700 s); tracking
    # periodElapsedTime resets per period. Convert to period-elapsed to align.
    t_center = t_center - 2700.0 * (period - 1)
    margin = 3.0 if anchor_name else 0.0          # read wider so we can re-centre + trim
    lo, hi = max(0.0, t_center - pre - margin), t_center + post + margin
    raw = []
    for fr in space_io.read_match(mid, sampling_stride=stride,
                                  periods=(period,), lock_attack_team_id=lock_team_id):
        if fr.timestamp_s < lo or fr.timestamp_s > hi:
            continue
        ctrl = pc.control_surface(fr.players, fr.ball_m, grid, include_gk=True)
        surf = ctrl["attack_control"] * xt_grid if kind == "danger" else ctrl["attack_control"]
        bx, by = float(fr.ball_m[0]), float(fr.ball_m[1])
        d_anchor, hero_cell = None, 0.0
        markers = []
        for i, ident in enumerate(fr.identities):
            mx, my = float(fr.players[i, 0] * HALF_LEN), float(fr.players[i, 1] * HALF_WID)
            if anchor_name and ident.name == anchor_name:
                d_anchor = math.hypot(mx - bx, my - by)
            if kind == "danger" and hero and ident.name == hero.get("name"):
                ci = int(np.clip((my + HALF_WID) / (2 * HALF_WID) * grid.ny, 0, grid.ny - 1))
                cj = int(np.clip((mx + HALF_LEN) / (2 * HALF_LEN) * grid.nx, 0, grid.nx - 1))
                hero_cell = float(surf[ci, cj])
            markers.append({"x": round(mx, 1), "y": round(my, 1),
                            "att": bool(fr.players[i, 4] > 0), "gk": bool(fr.players[i, 5] > 0.5),
                            "name": ident.name, "vis": ident.visibility})
        raw.append({"t_s": round(fr.timestamp_s, 2), "ball_xy": [round(bx, 1), round(by, 1)],
                    "in_possession_team": fr.in_possession_team, "surf": surf,
                    "raw_max": float(surf.max()), "players": markers,
                    "d_anchor": d_anchor, "hero_cell": hero_cell})
    if not raw:
        return None
    # re-centre on the true contest frame, then trim to [centre-pre, centre+post]
    if anchor_name:
        anchored = [r for r in raw if r["d_anchor"] is not None]
        if anchored:
            t_center = min(anchored, key=lambda r: r["d_anchor"])["t_s"]
    sel = [r for r in raw if t_center - pre <= r["t_s"] <= t_center + post] or raw
    gmax = max(r["raw_max"] for r in sel) or 1.0
    hero_owned = max((r["hero_cell"] for r in sel), default=0.0)
    frames_out = [{"t_s": r["t_s"], "ball_xy": r["ball_xy"],
                   "in_possession_team": r["in_possession_team"],
                   "raw_max": round(r["raw_max"], 5), "players": r["players"],
                   "surface": [[round(float(v), 4) for v in row] for row in (r["surf"] / gmax)]}
                  for r in sel]
    xt_ref = xt_grid / (xt_grid.max() or 1.0)
    if kind == "danger" and hero is not None and "obso_owned" not in hero:
        hero["obso_owned"] = round(hero_owned, 4)
    # "this helped" receipt — how much THREAT (xT) the ball gained over the clip:
    # xT of the ball's spot (Karun Singh grid) at the start vs its peak in the window.
    ball_xt = [float(pc.xt_value_m(r["ball_xy"][0], r["ball_xy"][1])) for r in sel]
    impact = {"xt_start": round(ball_xt[0], 3), "xt_peak": round(max(ball_xt), 3),
              "xt_added": round(max(ball_xt) - ball_xt[0], 3),
              "window_s": round(sel[-1]["t_s"] - sel[0]["t_s"], 1)}
    payload = {
        "match_id": mid, "period": period,
        "start_s": round(sel[0]["t_s"], 1), "end_s": round(sel[-1]["t_s"], 1),
        "peak_t_s": round(t_center, 2),
        "hz": round(RAW_HZ / stride, 2), "n_frames": len(frames_out),
        "grid": {"nx": grid.nx, "ny": grid.ny, "length_m": 105.0, "width_m": 68.0},
        "global_max": round(gmax, 5),
        "xt_reference": [[round(float(v), 4) for v in row] for row in xt_ref],
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "hero": hero, "impact": impact, "frames": frames_out,
    }
    if teams:
        payload["teams"] = teams
    return payload


SHOT_LABEL = {"G": "a goal", "S": "a saved shot", "O": "a shot off target",
              "B": "a blocked shot", "C": "a charged-down shot"}
KNOCKOUT_IDS = {str(m) for m in range(10502, 10518)}   # PFF knockout match ids
DANGER_STARS = ["di maria", "di maría", "messi", "mbappe", "mbappé", "alvarez", "álvarez",
                "giroud", "gakpo", "richarlison", "neymar", "saka", "rashford", "ramos",
                "kramaric", "kramarić", "fullkrug", "füllkrug", "gnabry", "embolo", "valencia"]


def _teams_block(meta, lock_id):
    """{attack, defend} team names given the locked (attacking) team's PFF id."""
    home, away = meta["homeTeam"], meta["awayTeam"]
    if lock_id == str(home["id"]):
        return {"attack": home["name"], "defend": away["name"]}
    return {"attack": away["name"], "defend": home["name"]}


def possession_shot(ev, period, gc):
    """From the pass at (period, gc), forward-scan the same in-possession team's
    events until possession changes; return (shooter_name, outcome_label) if the
    possession produced a shot, else (None, None). gc is cumulative gameClock."""
    # locate the event index nearest (period, gc)
    idx = None
    for i, e in enumerate(ev):
        gge = e.get("gameEvents") or {}
        pe = e.get("possessionEvents") or {}
        if gge.get("period") == period and pe.get("gameClock") is not None \
                and abs(float(pe["gameClock"]) - gc) < 0.6:
            idx = i; break
    if idx is None:
        return None, None
    team = (ev[idx].get("gameEvents") or {}).get("teamName")
    for j in range(idx, min(idx + 14, len(ev))):
        gge = ev[j].get("gameEvents") or {}
        pe = ev[j].get("possessionEvents") or {}
        if gge.get("teamName") and gge.get("teamName") != team:
            break
        if gge.get("gameEventType") in ("OUT", "END") and j > idx:
            # ball out — include this event's shot if any, then stop
            if pe.get("possessionEventType") == "SH":
                return pe.get("shooterPlayerName"), SHOT_LABEL.get(pe.get("shotOutcomeType"), "a shot")
            break
        if pe.get("possessionEventType") == "SH":
            return pe.get("shooterPlayerName"), SHOT_LABEL.get(pe.get("shotOutcomeType"), "a shot")
    return None, None


def pick_dangerous_run():
    """A goal where the SHOOTER ran off the ball into dangerous space, received, and
    scored — the bloom→receive→score arc. Ranks goals by knockout/final + star, so
    Di María's run-and-finish in the final tops it. Returns the ranked candidate list."""
    cands = []
    for mid in MIDS:
        try:
            ev = json.load(open(ROOT / "Event Data" / f"{mid}.json"))
        except Exception:
            continue
        for i, e in enumerate(ev):
            pe = e.get("possessionEvents") or {}
            ge = e.get("gameEvents") or {}
            if pe.get("possessionEventType") != "SH" or pe.get("shotOutcomeType") != "G":
                continue
            if pe.get("nonEvent"):
                continue
            shooter = pe.get("shooterPlayerName"); sid = pe.get("shooterPlayerId")
            period = ge.get("period"); gc = pe.get("gameClock")
            if not shooter or sid is None or period not in (1, 2) or gc is None:
                continue
            # require the shooter RECEIVED a pass right before (an off-ball arrival, not a solo carry)
            assist = None
            for j in range(i - 1, max(i - 4, -1), -1):
                q = ev[j].get("possessionEvents") or {}
                if q.get("possessionEventType") in ("PA", "CR"):
                    tgt = q.get("targetPlayerName") or q.get("receiverPlayerName")
                    if tgt and tgt.split()[-1] == shooter.split()[-1]:
                        assist = q.get("passerPlayerName") or q.get("crosserPlayerName")
                    break
            if not assist:
                continue
            score = 0.0
            if mid == "10517":   # the final — keep the dangerous-space act in ARG v FRA
                score += 100
            elif mid in KNOCKOUT_IDS:
                score += 30
            if _is_star(shooter, DANGER_STARS):
                score += 10
            cands.append((score, mid, int(period), float(gc), int(sid), shooter, assist))
    cands.sort(key=lambda c: -c[0])
    return cands


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
        shot_shooter, shot_out = possession_shot(ev0, period, gc)
        hero = {"name": pname, "receiver": rname,
                "team": meta["homeTeam"]["name"] if lock == str(meta["homeTeam"]["id"]) else meta["awayTeam"]["name"],
                "control": ctrl, "xt": xtv, "value": round(score, 4),
                "shot_shooter": shot_shooter, "shot_outcome": shot_out}
        print(f"[passing] {pname} -> {rname} ({mid} p{period} {gc:.1f}s) "
              f"control={ctrl} xt={xtv} value={score:.4f} | possession -> "
              f"{shot_out or 'no shot'}{(' by '+shot_shooter) if shot_shooter else ''}", flush=True)
        # extend past the pass so the resulting shot is visible (Müller→Kimmich→shot lands
        # ~2-3 s later); 5 Hz so the fast shot ball doesn't teleport between frames.
        payload = export_window(mid, period, gc, lock, "danger", hero,
                                teams=_teams_block(meta, lock), pre=2.5, post=3.5, stride=6)
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

    # ---- DUEL ---- (validate each candidate against TRACKING; keep the first that's a
    # genuine, in-frame 50-50 the WINNER was the underdog in, so the clip matches the odds)
    print("[duel] scanning + tracking-validating ground-duel upsets...", flush=True)
    n_tried = 0
    for score, mid, period, gc, wid, wname, lid, lname in pick_duel():
        n_tried += 1
        if n_tried > 40:
            print("[duel] no tracking-valid 50-50 found in 40 candidates", flush=True)
            break
        payload = validate_export_duel(mid, period, gc, wid, wname, lid, lname)
        if not payload or payload["n_frames"] < 6:
            continue
        (SURF_DIR / "duel.json").write_text(json.dumps(payload))
        print(f"[duel] wrote surfaces/duel.json — {wname} beats {lname} "
              f"({payload['match']}, p{period} {gc:.0f}s), model gave winner "
              f"{payload['hero']['expected_pct']}%, {payload['n_frames']} frames "
              f"(tried {n_tried} candidates)", flush=True)
        break

    # ---- DANGEROUS SPACE (Way 3): bloom -> receive -> score ----
    print("[danger] scanning for the best run-into-space-and-score goal...", flush=True)
    ranked = pick_dangerous_run()
    for score, mid, period, gc, sid, shooter, assist in ranked[:8]:
        meta = space_io.load_metadata(mid)
        ev0 = json.load(open(ROOT / "Event Data" / f"{mid}.json"))
        lock = None
        for e in ev0:
            tid = _team_id_for_player(meta, e, sid)
            if tid:
                lock = tid; break
        if lock is None:
            continue
        hero = {"name": shooter, "team": _teams_block(meta, lock)["attack"],
                "assist": assist, "outcome": "goal"}
        # finer sampling (5 Hz) so the sprint is smooth, not jumpy; pre trimmed to ~2.8 s so
        # the clip starts on his decisive forward run (skips the occluded forward-back-forward
        # build-up that read as "jumping around"), ending just after the finish.
        payload = export_window(mid, period, gc, lock, "danger", hero,
                                teams=_teams_block(meta, lock), pre=2.4, post=1.0, stride=6)
        if not payload or payload["n_frames"] < 8:
            continue
        # validate it's a real forward off-ball arrival: shooter visible + advances toward goal
        xs = [p["x"] for f in payload["frames"] for p in f["players"] if p["name"] == shooter]
        if len(xs) < payload["n_frames"] * 0.6 or (max(xs) - xs[0]) < 3.0:
            print(f"[danger] skip {shooter} ({mid}): weak/absent run", flush=True)
            continue
        payload.update({
            "metric": "pobso",
            "title": f"P-OBSO hero: {shooter}'s run into dangerous space — and the finish",
            "description": (f"{shooter} ghosts off the ball into a high-danger pocket (attacker "
                            "pitch-control × Expected Threat), receives "
                            f"{('from '+assist+' ') if assist else ''}and scores. Watch the bright "
                            "pocket bloom AHEAD of his run, before the ball arrives."),
            "match": f"{meta['homeTeam']['name']} v {meta['awayTeam']['name']}",
        })
        (SURF_DIR / "pobso.json").write_text(json.dumps(payload))
        print(f"[danger] wrote surfaces/pobso.json — {shooter} ({meta['homeTeam']['name']} v "
              f"{meta['awayTeam']['name']}, p{period} {gc:.0f}s), assist {assist}, "
              f"{payload['n_frames']} frames, obso_owned={hero.get('obso_owned')}", flush=True)
        break

    print(f"\nEXIT_OK ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
