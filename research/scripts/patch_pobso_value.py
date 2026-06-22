#!/usr/bin/env python3
"""Tag each pass in the Di María clip (pobso.json) with the paper value-model V at its TARGET.

V = f_n(ball@pass-origin, target-cell) × goal-distance — the same Fernández–Bornn pitch value
the SOG/SGG card uses (space_value_model). Lets the passes ledger show control (PC) and V side by
side: the build-up passes land in high-V space (defenders crowd it) even when xT-added ≈ 0 — the
inversion, per pass. Ball position = the pass origin (x0,y0), matching how control_at is evaluated.

Run AFTER rendering pobso.json:
  PYTHONPATH=src uv run python research/scripts/patch_pobso_value.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_REPO / "research" / "scripts"), str(_REPO / "src")]
import pitch_control as pc  # noqa: E402
import space_value_model as svm  # noqa: E402

HALF_LEN, HALF_WID = pc.HALF_LEN, pc.HALF_WID
P = _REPO / "research" / "site" / "data" / "surfaces" / "pobso.json"


def main():
    model = svm.load_model()
    d = json.load(open(P))
    for p in d.get("passes", []):
        X = np.array([[p["x0"] / HALF_LEN, p["y0"] / HALF_WID,
                       p["x1"] / HALF_LEN, p["y1"] / HALF_WID]], dtype=np.float32)
        with torch.no_grad():
            v = float(model(torch.tensor(X))[0])
        v *= max(0.0, min(1.0, (p["x1"] + HALF_LEN) / (2 * HALF_LEN)))   # goal-distance multiplier
        p["v"] = round(v, 3)
    json.dump(d, open(P, "w"))
    print(f"patched {len(d.get('passes', []))} passes in {P.name} with V:")
    for p in d["passes"]:
        print(f"  {p['receiver']:<22} V={p['v']:.3f}  ctrl={p['control']:.2f}  xT+{p['xt_added']:.2f}")


if __name__ == "__main__":
    main()
