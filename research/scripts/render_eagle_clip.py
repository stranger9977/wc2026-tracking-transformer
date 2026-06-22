#!/usr/bin/env python3
"""Render an Eagle-derived clip into the site scrubber JSON, and "score" it with our metrics.

Pipeline:  Eagle output --(eagle_io)--> SpaceFrame stream --> de-jitter tracks -->
           per-frame pitch-control / value-of-space surface (pitch_control engine) -->
           research/site/data/surfaces/eagle_live.json  (buildScrubber schema)

The same Fernandez-Bornn pitch control + Karun-Singh xT engine that scores the PFF clips
scores this one -- the only difference is the tracking came from a TV broadcast via Eagle's
CV, not from PFF. We attach a `scorecard`:
  * territorial_control_pct  -- mean share of the pitch the attacking team controls
  * dangerous_share_pct      -- control-weighted share of the reachable danger zone (xT x reach)
  * peak_value_*             -- the moment of most controlled dangerous space (m^2-xT)
  * top_occupiers            -- players owning the most dangerous space (pitch_control.player_space)
  * impact                   -- the ball's xT path over the phase (start -> peak -> added)

Run:  PYTHONPATH=src uv run python research/scripts/render_eagle_clip.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_REPO / "research" / "scripts"), str(_REPO / "src")]
import pitch_control as pc  # noqa: E402
from eagle_io import read_eagle_clip  # noqa: E402

HALF_LEN, HALF_WID = pc.HALF_LEN, pc.HALF_WID
OUT = _REPO / "research" / "site" / "data" / "surfaces" / "eagle_live.json"


def _smooth(vals, nF, mh=3, ah=2):
    """5/7-tap median (kills teleport spikes) + mean (removes stair-steps). Heavier than the
    PFF path because broadcast-only tracking jitters harder; recompute velocity downstream."""
    def win(v, i, half):
        return [v[k] for k in range(max(0, i - half), min(nF, i + half + 1)) if v[k] is not None]
    med = [(sorted(w)[len(w) // 2] if (w := win(vals, i, mh)) else None) for i in range(nF)]
    return [(sum(w) / len(w) if (w := win(med, i, ah)) else None) for i in range(nF)]


def render(out_dir, *, attack_name, defend_name, title, description,
           pre_trim=0.0, post_trim=0.0, **kw):
    fbuf = read_eagle_clip(out_dir, attack_name=attack_name, defend_name=defend_name, **kw)
    # optional trim (e.g. drop a tail that runs into a camera cut)
    if pre_trim or post_trim:
        t0, t1 = fbuf[0].timestamp_s + pre_trim, fbuf[-1].timestamp_s - post_trim
        fbuf = [fr for fr in fbuf if t0 <= fr.timestamp_s <= t1]
    nF = len(fbuf)
    times = [fr.timestamp_s for fr in fbuf]
    grid = pc.make_grid(nx=40, ny=26)
    xt_grid = pc.xt_surface(grid)

    # build per-player tracks (metres), smooth, recompute velocity from the smoothed track
    tracks: dict = {}
    for i, fr in enumerate(fbuf):
        for j, ident in enumerate(fr.identities):
            tr = tracks.setdefault(ident.name, {"x": [None] * nF, "y": [None] * nF,
                                                "vis": [None] * nF,
                                                "att": bool(fr.players[j, 4] > 0),
                                                "gk": bool(fr.players[j, 5] > 0.5)})
            tr["x"][i] = float(fr.players[j, 0] * HALF_LEN)
            tr["y"][i] = float(fr.players[j, 1] * HALF_WID)
            tr["vis"][i] = ident.visibility
    for tr in tracks.values():
        tr["xs"], tr["ys"] = _smooth(tr["x"], nF), _smooth(tr["y"], nF)
        vx, vy = [0.0] * nF, [0.0] * nF
        for i in range(nF):
            a = i - 1 if (i > 0 and tr["xs"][i - 1] is not None) else i
            b = i + 1 if (i < nF - 1 and tr["xs"][i + 1] is not None) else i
            dt = times[b] - times[a]
            if tr["xs"][i] is not None and a != b and dt > 1e-3:
                vx[i] = float(np.clip((tr["xs"][b] - tr["xs"][a]) / dt, -12, 12))
                vy[i] = float(np.clip((tr["ys"][b] - tr["ys"][a]) / dt, -12, 12))
        tr["vx"], tr["vy"] = vx, vy
    bxs = _smooth([float(fr.ball_m[0]) for fr in fbuf], nF)
    bys = _smooth([float(fr.ball_m[1]) for fr in fbuf], nF)

    # per-frame surface + markers + scorecard accumulators
    raw, terr, dshare, vof_total = [], [], [], []
    occ: dict = {}                     # name -> summed owned xT-value (dangerous space)
    for i, fr in enumerate(fbuf):
        rows, idents = [], []
        for nm, tr in tracks.items():
            if tr["xs"][i] is None:
                continue
            rows.append([tr["xs"][i] / HALF_LEN, tr["ys"][i] / HALF_WID, tr["vx"][i], tr["vy"][i],
                         1.0 if tr["att"] else -1.0, 1.0 if tr["gk"] else 0.0, 0.0])
            idents.append((nm, tr["att"], tr["gk"], tr["vis"][i]))
        bx, by = float(bxs[i]), float(bys[i])
        ctrl = pc.control_surface(np.array(rows, dtype=np.float64), np.array([bx, by]),
                                  grid, include_gk=True)
        actrl = ctrl["attack_control"]
        reach = pc.reach_surface(np.array([bx, by]), grid)
        vof = actrl * xt_grid * reach          # value of space (OBSO): control x xT x reach

        terr.append(float((actrl > 0.5).mean() * 100.0))
        danger = xt_grid * reach
        tot = float(danger.sum())
        dshare.append(float((actrl * danger).sum() / tot * 100.0) if tot > 0 else 0.0)
        vof_total.append(float(vof.sum() * grid.cell_area_m2))

        # per-player owned dangerous value (attacking side), keyed back to name
        idx_name = {k: idents[k][0] for k in range(len(idents))}
        for pidx, info in pc.player_space(ctrl, grid, attacking_only=True).items():
            nm = idx_name.get(int(pidx))
            if nm:
                occ[nm] = occ.get(nm, 0.0) + info["xt_value"]

        markers = []
        for k, (nm, att, gk, vis) in enumerate(idents):
            mx, my = rows[k][0] * HALF_LEN, rows[k][1] * HALF_WID
            ci = int(np.clip((my + HALF_WID) / (2 * HALF_WID) * grid.ny, 0, grid.ny - 1))
            cj = int(np.clip((mx + HALF_LEN) / (2 * HALF_LEN) * grid.nx, 0, grid.nx - 1))
            markers.append({"x": round(mx, 1), "y": round(my, 1), "att": bool(att),
                            "gk": bool(gk), "name": nm, "vis": vis,
                            "ctrl": round(float(actrl[ci, cj]), 3)})
        raw.append({"t_s": round(times[i], 2), "ball_xy": [round(bx, 1), round(by, 1)],
                    "in_possession_team": fr.in_possession_team, "surf": vof,
                    "raw_max": float(vof.max()), "players": markers})

    gmax = max(r["raw_max"] for r in raw) or 1.0
    ball_xt = [float(pc.xt_value_m(r["ball_xy"][0], r["ball_xy"][1])) for r in raw]
    frames_out = [{"t_s": r["t_s"], "ball_xy": r["ball_xy"], "xt": round(ball_xt[i], 3),
                   "in_possession_team": r["in_possession_team"], "raw_max": round(r["raw_max"], 5),
                   "players": r["players"],
                   "surface": [[round(float(v), 4) for v in row] for row in (r["surf"] / gmax)]}
                  for i, r in enumerate(raw)]
    xt_ref = xt_grid / (xt_grid.max() or 1.0)

    peak_i = int(np.argmax(vof_total))
    top = sorted(occ.items(), key=lambda kv: -kv[1])[:4]
    occ_rows = [{"name": nm, "team": (attack_name if tracks[nm]["att"] else defend_name),
                 "xt_value": round(v / nF, 4)} for nm, v in top]
    impact = {"xt_start": round(ball_xt[0], 3), "xt_peak": round(max(ball_xt), 3),
              "xt_added": round(max(ball_xt) - ball_xt[0], 3),
              "window_s": round(raw[-1]["t_s"] - raw[0]["t_s"], 1)}
    hz = round(1.0 / float(np.median(np.diff(times))), 1) if nF > 1 else 0.0
    scorecard = {
        "attack_team": attack_name, "defend_team": defend_name,
        "territorial_control_pct": round(float(np.mean(terr)), 1),
        "dangerous_share_pct": round(float(np.mean(dshare)), 1),
        "peak_value_t_s": round(times[peak_i] - times[0], 2),
        "peak_value_m2": round(float(vof_total[peak_i]), 1),
        "top_occupiers": occ_rows, "n_frames": nF, "hz": hz,
    }
    hero = {"name": occ_rows[0]["name"] if occ_rows else "", "team": attack_name}

    payload = {
        "source": "Eagle (broadcast->tracking CV) — approximate, ~1-2 m, per-shot",
        "match": "France vs Morocco · 2022 World Cup semi-final (broadcast)",
        "period": 1, "start_s": round(raw[0]["t_s"], 1), "end_s": round(raw[-1]["t_s"], 1),
        "peak_t_s": round(times[peak_i], 2), "hz": hz, "n_frames": len(frames_out),
        "grid": {"nx": grid.nx, "ny": grid.ny, "length_m": 105.0, "width_m": 68.0},
        "global_max": round(gmax, 5),
        "xt_reference": [[round(float(v), 4) for v in row] for row in xt_ref],
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "title": title, "description": description,
        "hero": hero, "impact": impact, "scorecard": scorecard,
        "teams": {"attack": attack_name, "defend": defend_name},
        "frames": frames_out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload))
    sc = scorecard
    print(f"[eagle-clip] {nF} frames @ {hz}Hz -> {OUT.name}")
    print(f"  territorial control: {attack_name} {sc['territorial_control_pct']}%")
    print(f"  dangerous-space share: {attack_name} {sc['dangerous_share_pct']}%")
    print(f"  peak controlled danger: {sc['peak_value_m2']} m2-xT at t+{sc['peak_value_t_s']}s")
    print(f"  ball xT: {impact['xt_start']} -> {impact['xt_peak']} (+{impact['xt_added']})")
    print("  top space occupiers:")
    for r in occ_rows:
        print(f"    {r['name']:<10} {r['team']:<10} {r['xt_value']}")
    return payload


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(_REPO / "research" / "data" / "eagle" / "mbappe_usable"))
    ap.add_argument("--flip", action="store_true")
    ap.add_argument("--attack-bit", type=int, default=None)
    ap.add_argument("--pre-trim", type=float, default=0.0)
    ap.add_argument("--post-trim", type=float, default=0.0)
    a = ap.parse_args()
    render(a.dir, attack_name="France", defend_name="Morocco",
           title="From a TV broadcast to a scored space surface",
           description=("Eagle turned the France-Morocco broadcast into tracking; our pitch-control "
                        "engine scored the space. Approximate, broadcast-derived — the live-2026 path."),
           flip=a.flip, attack_bit=a.attack_bit, pre_trim=a.pre_trim, post_trim=a.post_trim)
