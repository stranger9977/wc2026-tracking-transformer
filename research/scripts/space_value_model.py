#!/usr/bin/env python3
"""C · Pitch Value model (Fernandez & Bornn 2018) — trained exactly as the paper.

The paper's "only trained model." There is no labelled value-of-space data, so the target is
self-generated from a behavioural proxy: defenders position themselves to cover valuable space,
so the value of a cell is the defensive coverage there.

  TARGET (Step 1):  D(cell) = Σ_defenders I_d(ball, cell)        [= control_surface "defend_infl"]
                    V̂(cell) = min(1, D(cell))
  FIT    (Step 2):  V(cell) = f_n(p_ball, p_cell; θ),  θ* = argmin Σ (V̂ - f_n)²   (MSE)
                    -> at INFERENCE V depends only on (ball, cell); the specific defenders are
                       marginalised out, so V is the EXPECTED coverage given the ball position.
  NORM   (Step 3):  × distance-to-opponent-goal multiplier, so value accumulates upfield.

Frames are read oriented attacking-+x (space_io default: in-possession team attacks +x), so
"defenders" = the not-in-possession team and the goal multiplier points the right way. β does not
enter the target (it's a sum of influence, pre-logistic).

Train:  PFF_ROOT=$HOME/pff_wc22_local PYTHONPATH=src \
          uv run python research/scripts/space_value_model.py --matches 16 --stride 20
Saves:  output/pitch_value_nn.pt  (state_dict + arch + norm meta)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_REPO / "research" / "scripts"), str(_REPO / "src")]
import pitch_control as pc  # noqa: E402
import space_io  # noqa: E402

HALF_LEN, HALF_WID = pc.HALF_LEN, pc.HALF_WID
CKPT = _REPO / "output" / "pitch_value_nn.pt"
VALUE_GRID = (15, 21)   # (ny, nx) — the paper's ~21×15 coverage grid


class PitchValueNet(nn.Module):
    """f_n(ball_xy, cell_xy) -> value in [0,1]. Small MLP; sigmoid output matches the [0,1] target."""

    def __init__(self, hidden=64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(4, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, 1), nn.Sigmoid(),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


def _manufacture(matches, stride, root):
    """Sweep oriented frames -> (X=[bx,by,cx,cy] normalised, y=V̂) samples."""
    grid = pc.make_grid(nx=VALUE_GRID[1], ny=VALUE_GRID[0])
    cx = (grid.XX / HALF_LEN).flatten()        # (ncell,) normalised cell x
    cy = (grid.YY / HALF_WID).flatten()
    Xs, ys = [], []
    mids = sorted(p.name.replace(".jsonl.bz2", "")
                  for p in (root / "Tracking Data").glob("*.jsonl.bz2"))[:matches]
    for mi, mid in enumerate(mids):
        nframes = 0
        for fr in space_io.read_match(mid, sampling_stride=stride):
            ctrl = pc.control_surface(fr.players, fr.ball_m, grid, include_gk=True, beta=1.0)
            vhat = np.minimum(1.0, ctrl["defend_infl"]).flatten()      # V̂ = min(1, Σ defenders)
            bxn, byn = fr.ball_m[0] / HALF_LEN, fr.ball_m[1] / HALF_WID
            Xs.append(np.stack([np.full_like(cx, bxn), np.full_like(cy, byn), cx, cy], axis=1))
            ys.append(vhat)
            nframes += 1
        print(f"  [{mi + 1}/{len(mids)}] match {mid}: {nframes} frames", flush=True)
    X = np.concatenate(Xs).astype(np.float32)
    y = np.concatenate(ys).astype(np.float32)
    return X, y


def train(matches=16, stride=20, epochs=12, batch=16384, lr=2e-3, root=None):
    root = Path(root or os.environ.get("PFF_ROOT", str(Path.home() / "pff_wc22_local")))
    torch.manual_seed(0); np.random.seed(0)
    print(f"[value-model] manufacturing targets from {matches} matches @ stride {stride}…", flush=True)
    X, y = _manufacture(matches, stride, root)
    print(f"[value-model] {len(X):,} samples ({X.nbytes / 1e6:.0f} MB). training…", flush=True)
    Xt, yt = torch.tensor(X), torch.tensor(y)
    n = len(Xt); idx = torch.randperm(n)
    nval = n // 10
    vi, ti = idx[:nval], idx[nval:]
    model = PitchValueNet()
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossf = nn.MSELoss()
    for ep in range(epochs):
        model.train(); perm = ti[torch.randperm(len(ti))]
        tot = 0.0
        for b in range(0, len(perm), batch):
            bi = perm[b:b + batch]
            opt.zero_grad()
            loss = lossf(model(Xt[bi]), yt[bi])
            loss.backward(); opt.step()
            tot += loss.item() * len(bi)
        model.eval()
        with torch.no_grad():
            vloss = lossf(model(Xt[vi]), yt[vi]).item()
        print(f"  epoch {ep + 1:>2}/{epochs}  train MSE {tot / len(ti):.5f}  val MSE {vloss:.5f}", flush=True)
    CKPT.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "hidden": 64,
                "value_grid": VALUE_GRID, "matches": matches, "stride": stride,
                "n_samples": int(n), "val_mse": float(vloss)}, CKPT)
    print(f"[value-model] saved -> {CKPT}", flush=True)
    return model


# ---------------------------------------------------------------------------
# Inference helpers (used by the scorer + any board)
# ---------------------------------------------------------------------------
def load_model(path=CKPT):
    ck = torch.load(path, map_location="cpu")
    m = PitchValueNet(hidden=ck.get("hidden", 64))
    m.load_state_dict(ck["state_dict"]); m.eval()
    return m


def value_point(ball_m, cell_m, model, *, goal_mult=True):
    """V at a single (ball, cell) point — for per-pass scoring (pass_selection, bwae)."""
    X = np.array([[ball_m[0] / HALF_LEN, ball_m[1] / HALF_WID,
                   cell_m[0] / HALF_LEN, cell_m[1] / HALF_WID]], dtype=np.float32)
    with torch.no_grad():
        v = float(model(torch.tensor(X))[0])
    if goal_mult:
        v *= max(0.0, min(1.0, (cell_m[0] + HALF_LEN) / (2 * HALF_LEN)))
    return v


_VS_CACHE: dict = {}


def value_surface_cached(ball_m, grid, model, *, goal_mult=True, q=1.0):
    """value_surface, memoised on the ball position quantised to ``q`` metres. V depends only on
    (ball, cell) and the grid is fixed, so a 64-match sweep hits only a few thousand unique ball
    cells instead of one NN forward per frame — a ~100x speedup with sub-metre value error."""
    key = (round(float(ball_m[0]) / q) * q, round(float(ball_m[1]) / q) * q,
           grid.nx, grid.ny, bool(goal_mult))
    s = _VS_CACHE.get(key)
    if s is None:
        s = value_surface(np.array([key[0], key[1]]), grid, model, goal_mult=goal_mult)
        _VS_CACHE[key] = s
    return s


def value_surface(ball_m, grid, model, *, goal_mult=True):
    """Evaluate V = f_n(ball, cell) over the grid for one ball position, × goal-distance mult."""
    bxn, byn = ball_m[0] / HALF_LEN, ball_m[1] / HALF_WID
    cx = (grid.XX / HALF_LEN).flatten(); cy = (grid.YY / HALF_WID).flatten()
    X = np.stack([np.full_like(cx, bxn), np.full_like(cy, byn), cx, cy], axis=1).astype(np.float32)
    with torch.no_grad():
        v = model(torch.tensor(X)).numpy().reshape(grid.ny, grid.nx)
    if goal_mult:
        v = v * np.clip((grid.XX + HALF_LEN) / (2 * HALF_LEN), 0.0, 1.0)   # 0 own goal -> 1 opp goal
    return v


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=16)
    ap.add_argument("--stride", type=int, default=20)
    ap.add_argument("--epochs", type=int, default=12)
    a = ap.parse_args()
    train(matches=a.matches, stride=a.stride, epochs=a.epochs)
