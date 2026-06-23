#!/usr/bin/env python3
"""Score the Di María play EXACTLY like Fernandez & Bornn — Q, SOG/SOL, SGG over time.

Pipeline (paper sections B–F), per frame of the clip:
  PC_i = σ(Σ I_att − Σ I_def), β=1                              (B, paper β)
  V    = f_n(ball, cell) × goal-mult   (trained value model)    (C, space_value_model)
  Q_i  = Σ_{cells player i owns} PC(cell) · V(cell) · cell_area  (D)
  G_i  = mean(Q_i over next w s) − Q_i(t)                        (E, "mean difference" reading*)
  SOG_i = G_i if G_i≥ε else 0 ;  SOL_i = −G_i if G_i≤−ε else 0   (E), split active/passive @1.5 m/s
  SGG: drag rule (δ=5m mark, α=3m guard) → credit receiver's G to the generator   (F)

* The printed Eq.7 is a windowed AVERAGE of Q (a level); with Q≥0 that makes SOL degenerate.
  The text calls G a "mean DIFFERENCE" of quality, so we use the delta reading (forward-mean − now)
  — the interpretation the methodology doc licenses — so SOG/SOL read as gain/loss. The plotted
  "value over time" is the level Q_i(t); SOG/SOL/SGG are derived from G.

Out: research/site/data/surfaces/dimaria_paper_score.json
Run: PFF_ROOT=$HOME/pff_wc22_local PYTHONPATH=src uv run python research/scripts/space_paper_score.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_REPO / "research" / "scripts"), str(_REPO / "src")]
import pitch_control as pc  # noqa: E402
import space_io  # noqa: E402
import space_value_model as svm  # noqa: E402

HALF_LEN, HALF_WID = pc.HALF_LEN, pc.HALF_WID
OUT = _REPO / "research" / "site" / "data" / "surfaces" / "dimaria_paper_score.json"

# --- defaults: Di María play (Argentina 3–0 France build-up); override via CLI for other clips ---
MID, PERIOD = "10517", 1
CLIP_LO, CLIP_HI = 2110.5, 2121.6           # period-elapsed seconds of the rendered clip
READ_LO, READ_HI = 2107.5, 2125.5           # pad: lead-in + forward SOG window lookahead
LOCK = "364"                                 # attacking team id (Argentina)
MATCH_LABEL = "Argentina 3–0 France · 2022 World Cup final · Di María goal build-up"
STRIDE = 3                                   # 30 Hz / 3 = 10 Hz (matches the rendered clip)
W_S = 3.0                                    # SOG/SGG window (paper)
EPS = 0.04                                   # G dead-band (m²·value units; tuned to the play)
ACTIVE_MS = 1.5                              # active/passive split (paper)
DELTA_M, ALPHA_M = 5.0, 3.0                  # SGG mark / minimum-movement (paper)


def _smooth(vals, nF, mh=2, ah=1):
    def win(v, i, half):
        return [v[k] for k in range(max(0, i - half), min(nF, i + half + 1)) if v[k] is not None]
    med = [(sorted(w)[len(w) // 2] if (w := win(vals, i, mh)) else None) for i in range(nF)]
    return [(sum(w) / len(w) if (w := win(med, i, ah)) else None) for i in range(nF)]


def _arg_team_id():
    meta = space_io.load_metadata(MID)
    for side in ("homeTeam", "awayTeam"):
        t = meta.get(side) or {}
        if "argentin" in str(t.get("name", "")).lower():
            return str(t.get("id"))
    return None


def player_q(ctrl, grid, V):
    """Q_i = Σ cells player i owns (argmax attacker influence) of attack_control · V · cell_area."""
    infl, idx = ctrl["player_influence"], ctrl["player_idx"]
    is_att = ctrl["player_is_attacking"]; actrl = ctrl["attack_control"]
    if not is_att.any():
        return {}
    sub, sub_idx = infl[is_att], idx[is_att]
    owner = np.argmax(sub, axis=0)
    out = {}
    for k, orig in enumerate(sub_idx):
        cells = owner == k
        out[int(orig)] = float((cells * actrl * V).sum() * grid.cell_area_m2)
    return out


def main():
    global MID, PERIOD, CLIP_LO, CLIP_HI, READ_LO, READ_HI, LOCK, MATCH_LABEL, OUT
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--match"); ap.add_argument("--period", type=int)
    ap.add_argument("--lo", type=float); ap.add_argument("--hi", type=float)
    ap.add_argument("--lock"); ap.add_argument("--label"); ap.add_argument("--out")
    a = ap.parse_args()
    if a.match: MID = a.match
    if a.period: PERIOD = a.period
    if a.lo is not None: CLIP_LO = a.lo
    if a.hi is not None: CLIP_HI = a.hi
    READ_LO, READ_HI = CLIP_LO - 3.0, CLIP_HI + 4.0
    if a.lock: LOCK = a.lock
    if a.label: MATCH_LABEL = a.label
    if a.out: OUT = _REPO / "research" / "site" / "data" / "surfaces" / f"{a.out}.json"
    import os
    VALUE = os.environ.get("SPACE_VALUE", "v")   # "v" = trained F&B value model; "xt" = static Karun-Singh xT
    grid = pc.make_grid(nx=40, ny=26)
    xt_grid = pc.xt_surface(grid)                 # static xT, oriented attack-+x (lock team attacks +x)
    model = svm.load_model() if VALUE != "xt" else None
    arg_id = LOCK or _arg_team_id()
    print(f"[paper-score] match {MID} P{PERIOD} {CLIP_LO}-{CLIP_HI}s, lock {arg_id} -> {OUT.name}", flush=True)

    fbuf = [fr for fr in space_io.read_match(MID, sampling_stride=STRIDE, periods=(PERIOD,),
                                             lock_attack_team_id=arg_id)
            if READ_LO <= fr.timestamp_s <= READ_HI]
    nF = len(fbuf)
    times = [fr.timestamp_s for fr in fbuf]
    print(f"[paper-score] {nF} frames {times[0]:.1f}–{times[-1]:.1f}s", flush=True)

    # ---- per-player smoothed tracks (metres) + velocity (de-jitter broadcast tracking) ----
    tracks: dict = {}
    for i, fr in enumerate(fbuf):
        for j, ident in enumerate(fr.identities):
            pad = (fr.players[j, 0] == 0 and fr.players[j, 1] == 0
                   and fr.players[j, 2] == 0 and fr.players[j, 3] == 0)
            tr = tracks.setdefault(ident.name, {"x": [None] * nF, "y": [None] * nF,
                                                "att": bool(fr.players[j, 4] > 0),
                                                "gk": bool(fr.players[j, 5] > 0.5),
                                                "team": ident.team})
            if not pad:
                tr["x"][i] = float(fr.players[j, 0] * HALF_LEN)
                tr["y"][i] = float(fr.players[j, 1] * HALF_WID)
    for tr in tracks.values():
        tr["xs"], tr["ys"] = _smooth(tr["x"], nF), _smooth(tr["y"], nF)
        spd = [0.0] * nF
        for i in range(nF):
            a = i - 1 if (i > 0 and tr["xs"][i - 1] is not None) else i
            b = i + 1 if (i < nF - 1 and tr["xs"][i + 1] is not None) else i
            dt = times[b] - times[a]
            if tr["xs"][i] is not None and a != b and dt > 1e-3:
                vx = (tr["xs"][b] - tr["xs"][a]) / dt
                vy = (tr["ys"][b] - tr["ys"][a]) / dt
                spd[i] = min(math.hypot(vx, vy), 12.0)
        tr["spd"] = spd
    bxs = _smooth([float(fr.ball_m[0]) for fr in fbuf], nF)
    bys = _smooth([float(fr.ball_m[1]) for fr in fbuf], nF)

    # ---- per-frame: control (β=1) → V (trained NN) → per-player Q ----
    q_series = {nm: [None] * nF for nm in tracks}
    for i, fr in enumerate(fbuf):
        rows, names = [], []
        for nm, tr in tracks.items():
            if tr["xs"][i] is None:
                continue
            # velocity for influence shaping (finite diff on smoothed track)
            a = i - 1 if (i > 0 and tr["xs"][i - 1] is not None) else i
            b = i + 1 if (i < nF - 1 and tr["xs"][i + 1] is not None) else i
            dt = times[b] - times[a]
            vx = (tr["xs"][b] - tr["xs"][a]) / dt if (a != b and dt > 1e-3) else 0.0
            vy = (tr["ys"][b] - tr["ys"][a]) / dt if (a != b and dt > 1e-3) else 0.0
            rows.append([tr["xs"][i] / HALF_LEN, tr["ys"][i] / HALF_WID,
                         np.clip(vx, -12, 12), np.clip(vy, -12, 12),
                         1.0 if tr["att"] else -1.0, 1.0 if tr["gk"] else 0.0, 0.0])
            names.append(nm)
        bx, by = float(bxs[i]), float(bys[i])
        ctrl = pc.control_surface(np.array(rows, dtype=np.float64), np.array([bx, by]),
                                  grid, include_gk=True, beta=1.0)               # β=1, paper
        V = xt_grid if VALUE == "xt" else svm.value_surface(np.array([bx, by]), grid, model, goal_mult=True)
        q = player_q(ctrl, grid, V)
        # map player_idx (row index) -> name
        for ridx, nm in enumerate(names):
            if ridx in q:
                q_series[nm][i] = round(q[ridx], 4)

    # ---- E · SOG/SOL from G (delta reading), split active/passive ----
    wf = max(1, int(round(W_S * (1.0 / np.median(np.diff(times))))))   # window in frames
    in_clip = [k for k in range(nF) if CLIP_LO <= times[k] <= CLIP_HI]
    players_out = []
    sog_for = {}    # name -> per-frame G (for SGG attribution)
    for nm, tr in tracks.items():
        q = q_series[nm]
        G = [None] * nF
        for k in range(nF):
            fut = [q[t] for t in range(k + 1, min(nF, k + wf + 1)) if q[t] is not None]
            if q[k] is not None and fut:
                G[k] = sum(fut) / len(fut) - q[k]      # mean(forward window) − now  (gain/loss)
        sog_for[nm] = G
        sog = sol = sog_a = sog_p = 0.0
        for k in in_clip:
            g = G[k]
            if g is None:
                continue
            if g >= EPS:
                sog += g
                if tr["spd"][k] > ACTIVE_MS:
                    sog_a += g
                else:
                    sog_p += g
            elif g <= -EPS:
                sol += -g
        players_out.append({
            "name": nm, "team": tr["team"], "att": tr["att"], "gk": tr["gk"],
            "q": [q[k] for k in in_clip],
            "spd": [round(tr["spd"][k], 2) for k in in_clip],
            "sog": round(sog, 3), "sol": round(sol, 3),
            "sog_active": round(sog_a, 3), "sog_passive": round(sog_p, 3),
        })

    # ---- F · SGG: drag detection + attribute receiver's G to the generator ----
    att_names = [nm for nm, tr in tracks.items() if tr["att"] and not tr["gk"]]
    def_names = [nm for nm, tr in tracks.items() if not tr["att"]]

    def dist(a, b, k):
        ta, tb = tracks[a], tracks[b]
        if ta["xs"][k] is None or tb["xs"][k] is None:
            return None
        return math.hypot(ta["xs"][k] - tb["xs"][k], ta["ys"][k] - tb["ys"][k])

    sgg_credits: dict = {}    # generator -> {receiver -> credit}
    sgg_events = []
    for k in in_clip:
        ke = min(nF - 1, k + wf)
        for gen in att_names:
            for rec in att_names:
                if rec == gen:
                    continue
                for j in def_names:
                    d_rj0, d_gj0 = dist(rec, j, k), dist(gen, j, k)
                    d_rje, d_gje = dist(rec, j, ke), dist(gen, j, ke)
                    if None in (d_rj0, d_gj0, d_rje, d_gje):
                        continue
                    if (d_rj0 <= DELTA_M and d_gje <= DELTA_M and d_rje > DELTA_M
                            and (d_gje - d_gj0) < ALPHA_M):
                        g = sog_for[rec][k]
                        if g is not None and g >= EPS:
                            sgg_credits.setdefault(gen, {}).setdefault(rec, 0.0)
                            sgg_credits[gen][rec] += g
                            sgg_events.append({"t_s": round(times[k] - CLIP_LO, 2),
                                               "generator": gen, "receiver": rec,
                                               "defender": j, "credit": round(g, 3)})
                        break
    sgg_out = [{"generator": g, "receiver": r, "credit": round(c, 3)}
               for g, recs in sgg_credits.items() for r, c in recs.items()]
    sgg_out.sort(key=lambda x: -x["credit"])

    # ---- normalise to interpretable SHARES (the per-frame G sums are relative, not units) ----
    # Each attacker's share of the team's total occupation gain over the play — the
    # interpretable "Di María X%, Mac Allister Y% …" read, grounded in the paper's SOG.
    tot_sog = sum(p["sog"] for p in players_out if p["att"] and not p["gk"]) or 1.0
    for p in players_out:
        p["sog_share"] = round(100.0 * p["sog"] / tot_sog, 1) if (p["att"] and not p["gk"]) else 0.0
        p["active_pct"] = round(100.0 * p["sog_active"] / p["sog"], 0) if p["sog"] > 1e-9 else 0.0
    tot_sgg = sum(s["credit"] for s in sgg_out) or 1.0
    for s in sgg_out:
        s["share"] = round(100.0 * s["credit"] / tot_sgg, 1)

    payload = {
        "match": MATCH_LABEL,
        "period": PERIOD, "hz": round(1.0 / float(np.median(np.diff(times))), 1),
        "w_s": W_S, "epsilon": EPS, "active_ms": ACTIVE_MS,
        "value_model": ("Karun-Singh Expected Threat (xT): danger by distance/angle to goal"
                        if VALUE == "xt"
                        else "Fernández–Bornn pitch value: NN f(ball,cell) trained on defensive coverage, × goal-distance"),
        "value_mode": VALUE,
        "times": [round(times[k] - CLIP_LO, 2) for k in in_clip],
        "players": sorted(players_out, key=lambda p: -(p["sog"] + 0.001 * (not p["gk"]))),
        "sgg": sgg_out, "sgg_events": sgg_events,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload))
    print(f"[paper-score] {len(in_clip)} clip frames, wf={wf} frames -> {OUT.name}", flush=True)
    print("  SOG leaders (active | passive):", flush=True)
    for p in [x for x in payload["players"] if x["att"] and not x["gk"]][:6]:
        print(f"    {p['name']:<22} SOG {p['sog']:.3f}  (act {p['sog_active']:.3f} | pas {p['sog_passive']:.3f})  SOL {p['sol']:.3f}", flush=True)
    print("  SGG (generator → receiver):", flush=True)
    for s in sgg_out[:6]:
        print(f"    {s['generator']:<20} → {s['receiver']:<20} {s['credit']:.3f}", flush=True)


if __name__ == "__main__":
    main()
