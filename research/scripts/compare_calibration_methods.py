"""Compare calibration methods for the shared P_score / P_concede heads.

Motivation: the current isotonic fit has a wide FLAT segment (raw 0.874-0.937
-> 3.015%) that pins every "confident build-up" frame to one displayed value,
so the live curve looks dead-flat even as the model's raw conviction moves.
This script fits isotonic (baseline) vs Platt (logistic on logit) vs Beta
calibration on the same 8 val matches and reports, for each:

  • val Brier (lower = better calibrated)
  • monotonicity (must be non-decreasing to be a valid calibrator)
  • what the build-up band raw{0.905, 0.92, 0.938} maps to (does it SPREAD?)

Run: PYTHONPATH=src uv run python research/scripts/compare_calibration_methods.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule

REPO = Path(__file__).resolve().parents[2]
CKPT = REPO / "output" / "transformer_frame_vaep.ckpt"
CACHE = REPO / "research" / "data" / "frame_vaep_cache"
VAL_N = 8
BATCH = 4096
EPS = 1e-6


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def predict(lit, device, frames):
    ps_all, pc_all = [], []
    for i in range(0, frames.shape[0], BATCH):
        x = torch.from_numpy(frames[i:i + BATCH]).to(device)
        with torch.no_grad():
            enc = lit.backbone(x)
            ps = torch.sigmoid(lit.score_head(enc)).cpu().numpy().ravel()
            pc = torch.sigmoid(lit.concede_head(enc)).cpu().numpy().ravel()
        ps_all.append(ps); pc_all.append(pc)
    return np.concatenate(ps_all), np.concatenate(pc_all)


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def fit_isotonic(p, y):
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(p, y)
    return lambda q: iso.predict(q)


def fit_platt(p, y):
    """Platt: logistic regression on the logit of the raw probability."""
    z = np.log(np.clip(p, EPS, 1 - EPS) / (1 - np.clip(p, EPS, 1 - EPS))).reshape(-1, 1)
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(z, y)
    def f(q):
        zq = np.log(np.clip(q, EPS, 1 - EPS) / (1 - np.clip(q, EPS, 1 - EPS))).reshape(-1, 1)
        return lr.predict_proba(zq)[:, 1]
    return f


def fit_beta(p, y):
    """Beta calibration (Kull et al.): logistic on [ln p, -ln(1-p)]."""
    pc = np.clip(p, EPS, 1 - EPS)
    feats = np.column_stack([np.log(pc), -np.log(1 - pc)])
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(feats, y)
    def f(q):
        qc = np.clip(q, EPS, 1 - EPS)
        fq = np.column_stack([np.log(qc), -np.log(1 - qc)])
        return lr.predict_proba(fq)[:, 1]
    return f


def monotone(f):
    grid = np.linspace(0.001, 0.999, 999)
    out = f(grid)
    diffs = np.diff(out)
    return bool(np.all(diffs >= -1e-9)), out


def report(name_head, p, y):
    print(f"\n========== {name_head}  (n={len(p):,}, base rate={y.mean()*100:.3f}%) ==========")
    band = np.array([0.905, 0.920, 0.938])
    methods = {
        "isotonic": fit_isotonic(p, y),
        "platt":    fit_platt(p, y),
        "beta":     fit_beta(p, y),
    }
    print(f"raw Brier = {brier(p, y):.5f}")
    print(f"{'method':<10} {'Brier':>9} {'mono':>5}  band raw[0.905, 0.920, 0.938] -> cal%   spread(pp)")
    for name, f in methods.items():
        cal = f(p)
        mono, _ = monotone(f)
        bvals = f(band) * 100
        spread = bvals.max() - bvals.min()
        print(f"{name:<10} {brier(cal, y):>9.5f} {str(mono):>5}  "
              f"[{bvals[0]:5.2f}, {bvals[1]:5.2f}, {bvals[2]:5.2f}]%   {spread:5.2f}")


def main():
    device = _device()
    print(f"device: {device}")
    lit = FrameVaepLitModule.load_from_checkpoint(CKPT, map_location=device)
    lit.eval().to(device)
    val_ids = [p.stem for p in sorted(CACHE.glob("*.npz"), key=lambda p: p.stem)[-VAL_N:]]
    print(f"val matches: {val_ids}")
    ps_l, pc_l, ys_l, yc_l = [], [], [], []
    for mid in val_ids:
        d = np.load(CACHE / f"{mid}.npz", allow_pickle=False)
        ps, pc = predict(lit, device, d["tensors"].astype(np.float32))
        ps_l.append(ps); pc_l.append(pc)
        ys_l.append(d["y_score"].astype(np.float32).ravel())
        yc_l.append(d["y_concede"].astype(np.float32).ravel())
    report("SCORE", np.concatenate(ps_l), np.concatenate(ys_l))
    report("CONCEDE", np.concatenate(pc_l), np.concatenate(yc_l))


if __name__ == "__main__":
    main()


def sanity_curve():
    """Print the Beta curve shape across the full raw range for score+concede."""
    device = _device()
    lit = FrameVaepLitModule.load_from_checkpoint(CKPT, map_location=device)
    lit.eval().to(device)
    val_ids = [p.stem for p in sorted(CACHE.glob("*.npz"), key=lambda p: p.stem)[-VAL_N:]]
    for head, idx_pred in [("SCORE", 0), ("CONCEDE", 1)]:
        ps_l, ys_l = [], []
        for mid in val_ids:
            d = np.load(CACHE / f"{mid}.npz", allow_pickle=False)
            preds = predict(lit, device, d["tensors"].astype(np.float32))
            ps_l.append(preds[idx_pred])
            ys_l.append((d["y_score"] if head == "SCORE" else d["y_concede"]).astype(np.float32).ravel())
        p = np.concatenate(ps_l); y = np.concatenate(ys_l)
        fb = fit_beta(p, y)
        grid = np.array([0.001, 0.01, 0.05, 0.1, 0.3, 0.5, 0.7, 0.85, 0.9, 0.95, 0.99, 0.999])
        print(f"\n{head} Beta curve: raw -> cal%")
        for g in grid:
            print(f"  raw {g:.3f} -> {fb(np.array([g]))[0]*100:6.2f}%")
        print(f"  observed raw max = {p.max():.4f} -> {fb(np.array([p.max()]))[0]*100:.2f}%")
        print(f"  Beta cal at raw=1.0 -> {fb(np.array([0.999999]))[0]*100:.2f}%")


if __name__ == "__main__":
    import sys
    if "--sanity" in sys.argv:
        sanity_curve()
    else:
        main()
