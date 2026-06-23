#!/usr/bin/env python3
"""Turn a chemistry-pipeline clip (clean kloppy tracking, research/site/data/clips/<label>.json)
into a "space" clip the slim SVG renderer reads: de-jittered dot/ball motion + a per-frame
dangerous-space heatmap (attacker pitch-control x value x reach) computed FROM those same clean
positions, kept in the clip's real (PFF) orientation so the heat aligns with the dots.

Reuses the chemistry site's loader output (clean, named, stable slots), so the motion matches
the chemistry clips, and the heat is the only thing we add. Writes research/site/data/surfaces/
<out>.json (xT value layer) and, with SPACE_VALUE=v, <out>_v.json (the F&B value model).

  PYTHONPATH=research/scripts:src uv run python research/scripts/build_space_clip.py \
      --clip space-argcro --attack Argentina --out argcro --hero "Julian Alvarez" \
      --assist "Lionel Messi" --outcome goal
"""
import argparse
import json
import math
import os
from pathlib import Path

import numpy as np

import pitch_control as pc  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CLIPS = ROOT / "research" / "site" / "data" / "clips"
SURF = ROOT / "research" / "site" / "data" / "surfaces"
VMAX_P, VMAX_B = 12.0, 24.0

_VALUE_FN = None
if os.environ.get("SPACE_VALUE") == "v":
    import space_value_model as svm  # noqa: E402
    _model = svm.load_model()
    _VALUE_FN = lambda ball, g: svm.value_surface(ball, g, _model)  # noqa: E731


def _smooth1d(arr, mw=5, aw=5):
    n = len(arr)
    idx = [i for i in range(n) if arr[i] is not None]
    if not idx:
        return arr
    f = list(arr)
    for k in range(len(idx) - 1):
        a, b = idx[k], idx[k + 1]
        if b - a > 1:
            for j in range(a + 1, b):
                f[j] = arr[a] + (arr[b] - arr[a]) * (j - a) / (b - a)
    for j in range(idx[0]):
        f[j] = arr[idx[0]]
    for j in range(idx[-1] + 1, n):
        f[j] = arr[idx[-1]]

    def win(x, i, h):
        return x[max(0, i - h): min(n, i + h + 1)]
    med = [sorted(win(f, i, mw // 2))[len(win(f, i, mw // 2)) // 2] for i in range(n)]
    return [sum(win(med, i, aw // 2)) / len(win(med, i, aw // 2)) for i in range(n)]


def _clamp2d(xs, ys, dt, vmax):
    step = vmax * dt
    for i in range(1, len(xs)):
        dx, dy = xs[i] - xs[i - 1], ys[i] - ys[i - 1]
        d = math.hypot(dx, dy)
        if d > step:
            xs[i] = xs[i - 1] + dx * step / d
            ys[i] = ys[i - 1] + dy * step / d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True, help="kloppy clip label under data/clips/")
    ap.add_argument("--attack", required=True, help="attacking team name (matches home/away name)")
    ap.add_argument("--out", required=True, help="output basename under data/surfaces/")
    ap.add_argument("--hero", default="")
    ap.add_argument("--assist", default="")
    ap.add_argument("--outcome", default="goal")
    a = ap.parse_args()

    d = json.load(open(CLIPS / f"{a.clip}.json"))
    fr = d["frames"]
    n = len(fr)
    dt = (fr[1]["timestamp_ms"] - fr[0]["timestamp_ms"]) / 1000.0
    home, away = d["home_team"], d["away_team"]
    atk_id = str(home["id"]) if home["name"] == a.attack else str(away["id"])
    atk_name = a.attack
    def_name = away["name"] if atk_name == home["name"] else home["name"]

    # ---- de-jitter every player track (by stable slot) + the ball ----
    slots = sorted({p["slot"] for F in fr for p in F["players"]})
    track = {}
    for s in slots:
        xs = [None] * n
        ys = [None] * n
        meta = None
        for i, F in enumerate(fr):
            for p in F["players"]:
                if p["slot"] == s:
                    xs[i], ys[i] = p["x"], p["y"]
                    meta = p
        sx, sy = _smooth1d(xs), _smooth1d(ys)
        _clamp2d(sx, sy, dt, VMAX_P)
        track[s] = {"x": sx, "y": sy, "raw": xs, "name": meta.get("name") or f"#{s}",
                    "team_id": str(meta.get("team_id")), "is_gk": bool(meta.get("is_gk"))}
    bx = _smooth1d([F["ball"]["x"] for F in fr])
    by = _smooth1d([F["ball"]["y"] for F in fr])
    _clamp2d(bx, by, dt, VMAX_B)

    # ---- attack direction (so the VALUE peaks toward the attacking goal) ----
    gk = [s for s in slots if track[s]["is_gk"] and track[s]["team_id"] == atk_id]
    gk_x = np.mean([np.nanmean([v for v in track[s]["x"]]) for s in gk]) if gk else 0.0
    asign = 1.0 if gk_x < 0 else -1.0   # attack +x when own GK sits at -x
    # ORIENT everything to attack-+x (left->right) by rotating 180 deg when needed, so the
    # renderer + value layer are simple and consistent with the rest of the page.
    if asign < 0:
        for s in slots:
            track[s]["x"] = [v * -1 for v in track[s]["x"]]
            track[s]["y"] = [v * -1 for v in track[s]["y"]]
        bx = [v * -1 for v in bx]
        by = [v * -1 for v in by]

    grid = pc.make_grid(nx=40, ny=26)
    xt_grid = pc.xt_surface(grid)

    raw = []
    for i in range(n):
        rows = []
        for s in slots:
            if track[s]["raw"][i] is None:
                continue
            x, y = track[s]["x"][i], track[s]["y"][i]
            # finite-diff velocity from the smoothed track
            j0 = max(0, i - 1)
            j1 = min(n - 1, i + 1)
            vx = (track[s]["x"][j1] - track[s]["x"][j0]) / max(1e-3, (j1 - j0) * dt)
            vy = (track[s]["y"][j1] - track[s]["y"][j0]) / max(1e-3, (j1 - j0) * dt)
            att = 1.0 if track[s]["team_id"] == atk_id else -1.0
            rows.append([x / pc.HALF_LEN, y / pc.HALF_WID, vx, vy, att,
                         1.0 if track[s]["is_gk"] else 0.0, 0.0])
        ball_m = np.array([bx[i], by[i]])
        ctrl = pc.control_surface(np.array(rows, dtype=np.float64), ball_m, grid, include_gk=True)
        actrl = ctrl["attack_control"]
        val = _VALUE_FN(ball_m, grid) if _VALUE_FN is not None else xt_grid
        surf = actrl * val * pc.reach_surface(ball_m, grid)
        players = [{"x": round(track[s]["x"][i], 1), "y": round(track[s]["y"][i], 1),
                    "att": track[s]["team_id"] == atk_id, "gk": track[s]["is_gk"],
                    "name": track[s]["name"]}
                   for s in slots if track[s]["raw"][i] is not None]
        xt = float(pc.xt_value_m(bx[i], by[i]))
        raw.append({"t_s": round(fr[i]["timestamp_ms"] / 1000.0, 2),
                    "ball_xy": [round(bx[i], 1), round(by[i], 1)], "xt": round(xt, 3),
                    "players": players, "surf": surf, "raw_max": float(surf.max())})
    gmax = max(r["raw_max"] for r in raw) or 1.0
    frames_out = [{"t_s": r["t_s"], "ball_xy": r["ball_xy"], "xt": r["xt"], "players": r["players"],
                   "surface": [[round(float(v) / gmax, 4) for v in row] for row in r["surf"]]}
                  for r in raw]
    xts = [r["xt"] for r in raw]
    payload = {
        "match_id": d.get("match_id"), "period": d.get("period"),
        "start_s": frames_out[0]["t_s"], "end_s": frames_out[-1]["t_s"], "n_frames": n,
        "hz": round(1.0 / dt, 1),
        "grid": {"nx": grid.nx, "ny": grid.ny, "length_m": 105.0, "width_m": 68.0},
        "asign": asign,
        "teams": {"attack": atk_name, "defend": def_name},
        "hero": {"name": a.hero, "team": atk_name, "assist": (a.assist or None), "outcome": a.outcome},
        "impact": {"xt_start": round(xts[0], 3), "xt_peak": round(max(xts), 3),
                   "xt_added": round(max(xts) - xts[0], 3),
                   "window_s": round(frames_out[-1]["t_s"] - frames_out[0]["t_s"], 1)},
        "frames": frames_out,
    }
    out = a.out + ("_v" if _VALUE_FN is not None else "")
    (SURF / f"{out}.json").write_text(json.dumps(payload))
    print(f"wrote surfaces/{out}.json — {n} frames, attack {atk_name} asign={asign:+.0f}, "
          f"impact +{payload['impact']['xt_added']:.2f} xT")


if __name__ == "__main__":
    main()
