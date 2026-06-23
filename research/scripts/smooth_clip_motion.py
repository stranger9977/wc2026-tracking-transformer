#!/usr/bin/env python3
"""Smooth the per-frame dot + ball MOTION in the danger-clip surface JSONs.

Broadcast tracking jitters several metres frame-to-frame, and at the clip's 10 Hz that noise
renders as players/ball teleporting "all over the place" (frame-to-frame speeds of 40-160 m/s,
vs a real sprint ~9-10 m/s and the chemistry clips' clean ~9 m/s player / ~18 m/s ball maxima).
The export's light in-loop smoothing isn't enough once the event-keyframe overrides and the
ball-path stitching are layered on, so we de-jitter the FINAL rendered positions here:

  per (player name) track and the ball, across frames:
    1. linear gap-fill (a player off-camera for a few frames glides instead of popping)
    2. 5-tap median  (kills isolated teleport spikes)
    3. 5-tap moving average (removes the residual stair-steps)
    4. 2D speed clamp (a hard backstop: players <=12 m/s, ball <=24 m/s so driven passes survive)

The control surface is a smooth field that the front-end already lerps between frames, so only the
dots + ball needed de-jittering. Ball xT (Karun Singh) and the impact receipt are recomputed from
the smoothed ball path. Idempotent. Run after rendering / patching a clip:

  PYTHONPATH=research/scripts:src uv run python research/scripts/smooth_clip_motion.py
"""
import json
import math
import sys
from pathlib import Path

import pitch_control as pc  # noqa: E402  (xT recompute on the smoothed ball)

ROOT = Path(__file__).resolve().parents[2]
SURF = ROOT / "research" / "site" / "data" / "surfaces"
VMAX_PLAYER = 12.0   # m/s — above a real sprint (~10.5), kills teleports
VMAX_BALL = 24.0     # m/s — allows a driven pass/cut-back, kills the occlusion jumps
DEFAULT = ["argcro", "argcro_v", "framar", "framar_v", "pobso", "pobso_v"]


def _fill_med_avg(arr, mw=5, aw=5):
    """Gap-fill Nones (linear), then median(mw) then moving-average(aw)."""
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
    avg = [sum(win(med, i, aw // 2)) / len(win(med, i, aw // 2)) for i in range(n)]
    return avg


def _clamp2d(xs, ys, dt, vmax):
    step = vmax * dt
    for i in range(1, len(xs)):
        dx, dy = xs[i] - xs[i - 1], ys[i] - ys[i - 1]
        d = math.hypot(dx, dy)
        if d > step:
            xs[i] = xs[i - 1] + dx * step / d
            ys[i] = ys[i - 1] + dy * step / d


def smooth_clip(path):
    d = json.load(open(path))
    fr = d.get("frames", [])
    n = len(fr)
    if n < 3:
        return 0
    dt = (fr[1]["t_s"] - fr[0]["t_s"]) or 0.1
    names = set(p["name"] for F in fr for p in F["players"])
    for nm in names:
        xs = [None] * n
        ys = [None] * n
        for i, F in enumerate(fr):
            for p in F["players"]:
                if p["name"] == nm:
                    xs[i], ys[i] = p["x"], p["y"]
        sx, sy = _fill_med_avg(xs), _fill_med_avg(ys)
        _clamp2d(sx, sy, dt, VMAX_PLAYER)
        for i, F in enumerate(fr):
            if xs[i] is not None:
                for p in F["players"]:
                    if p["name"] == nm:
                        p["x"], p["y"] = round(sx[i], 1), round(sy[i], 1)
    bx = _fill_med_avg([F["ball_xy"][0] for F in fr])
    by = _fill_med_avg([F["ball_xy"][1] for F in fr])
    _clamp2d(bx, by, dt, VMAX_BALL)
    for i, F in enumerate(fr):
        F["ball_xy"] = [round(bx[i], 1), round(by[i], 1)]
        F["xt"] = round(float(pc.xt_value_m(bx[i], by[i])), 3)
    xts = [F["xt"] for F in fr]
    if d.get("impact"):
        d["impact"]["xt_start"] = round(xts[0], 3)
        d["impact"]["xt_peak"] = round(max(xts), 3)
        d["impact"]["xt_added"] = round(max(xts) - xts[0], 3)
    json.dump(d, open(path, "w"))
    return n


def main():
    for name in (sys.argv[1:] or DEFAULT):
        p = SURF / f"{name}.json"
        if p.exists():
            print(f"smoothed {name}: {smooth_clip(p)} frames")
        else:
            print(f"skip {name} (missing)")


if __name__ == "__main__":
    main()
