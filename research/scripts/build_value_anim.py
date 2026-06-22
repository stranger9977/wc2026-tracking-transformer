#!/usr/bin/env python3
"""Build the 'two ways to value space' animation data: xT (static) vs V (ball-conditioned).

The V model is a NN, so it can't run in the browser. Precompute the V surface at a sequence of
ball positions along the central channel (ball travelling upfield), plus the static xT surface,
so the front end can loop the ball and watch V re-pool where defenders typically guard — next to
xT's fixed near-goal blob. Coarse grid for a light, fast client render.

Run: PYTHONPATH=src uv run python research/scripts/build_value_anim.py
Out: research/site/data/surfaces/value_anim.json
"""
import json
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_REPO / "research" / "scripts"), str(_REPO / "src")]
import pitch_control as pc  # noqa: E402
import space_value_model as svm  # noqa: E402

HALF_LEN, HALF_WID = pc.HALF_LEN, pc.HALF_WID
OUT = _REPO / "research" / "site" / "data" / "surfaces" / "value_anim.json"
NY, NX = 20, 30


def main():
    model = svm.load_model()
    grid = pc.make_grid(nx=NX, ny=NY)
    xt = pc.xt_surface(grid)
    xt_n = (xt / (xt.max() or 1.0))
    # ball travels up the central channel, own half -> opponent box
    xs = np.linspace(-42.0, 46.0, 12)
    frames = []
    for bx in xs:
        v = svm.value_surface(np.array([float(bx), 0.0]), grid, model, goal_mult=True)
        vn = v / (v.max() or 1.0)
        frames.append({"ball_x": round(float(bx), 1), "ball_y": 0.0,
                       "v": [[round(float(c), 3) for c in row] for row in vn]})
    payload = {
        "grid": {"nx": NX, "ny": NY, "length_m": 105.0, "width_m": 68.0},
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "xt": [[round(float(c), 3) for c in row] for row in xt_n],
        "frames": frames,
    }
    OUT.write_text(json.dumps(payload))
    print(f"[value-anim] {len(frames)} ball positions -> {OUT.name} "
          f"(grid {NY}x{NX})")


if __name__ == "__main__":
    main()
