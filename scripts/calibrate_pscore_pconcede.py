"""Fit isotonic calibration maps for the shared P_score / P_concede heads.

The model was trained with pos_weight=80 on a ~0.5% positive base rate, so
sigmoid outputs are well-ranked (val AUC ~0.80) but not calibrated as
probabilities (val Brier ~0.19 for score). This script fits an isotonic
regression on the 8 held-out val matches and saves the calibration maps,
then applies them to every clip JSON under research/site/data/clips/.

Usage:
    PYTHONPATH=src uv run python scripts/calibrate_pscore_pconcede.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from sklearn.isotonic import IsotonicRegression

from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule

REPO = Path(__file__).resolve().parents[1]
CKPT = REPO / "output" / "transformer_frame_vaep.ckpt"
CACHE = REPO / "research" / "data" / "frame_vaep_cache"
OUT = REPO / "output" / "pscore_calibration.json"
CLIPS_DIR = REPO / "research" / "site" / "data" / "clips"
VAL_N = 8
BATCH = 4096


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_val_match_ids() -> list[str]:
    files = sorted(CACHE.glob("*.npz"), key=lambda p: p.stem)
    return [p.stem for p in files[-VAL_N:]]


def predict_match(lit: FrameVaepLitModule, device: torch.device,
                  frames: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ps_all, pc_all = [], []
    for i in range(0, frames.shape[0], BATCH):
        x = torch.from_numpy(frames[i:i + BATCH]).to(device)
        with torch.no_grad():
            enc = lit.backbone(x)
            ps = torch.sigmoid(lit.score_head(enc)).cpu().numpy()
            pc = torch.sigmoid(lit.concede_head(enc)).cpu().numpy()
        ps_all.append(ps)
        pc_all.append(pc)
    return np.concatenate(ps_all), np.concatenate(pc_all)


def main() -> None:
    device = _device()
    print(f"[1/4] Loading checkpoint on {device} …")
    lit = FrameVaepLitModule.load_from_checkpoint(CKPT, map_location=device)
    lit.eval()

    val_ids = load_val_match_ids()
    print(f"[2/4] Running model on {len(val_ids)} val matches: {val_ids}")
    ps_list, pc_list, ys_list, yc_list = [], [], [], []
    for mid in val_ids:
        d = np.load(CACHE / f"{mid}.npz", allow_pickle=False)
        frames = d["tensors"].astype(np.float32)
        y_s = d["y_score"].astype(np.float32)
        y_c = d["y_concede"].astype(np.float32)
        ps, pc = predict_match(lit, device, frames)
        ps_list.append(ps); pc_list.append(pc)
        ys_list.append(y_s); yc_list.append(y_c)
        print(f"      {mid}: {frames.shape[0]:>6d} frames | "
              f"y_s={y_s.mean()*100:.2f}% y_c={y_c.mean()*100:.2f}% | "
              f"raw ps mean={ps.mean():.3f} pc mean={pc.mean():.3f}")

    ps = np.concatenate(ps_list); pc = np.concatenate(pc_list)
    ys = np.concatenate(ys_list); yc = np.concatenate(yc_list)

    print(f"[3/4] Fitting isotonic calibration (n={len(ps):,})")
    iso_s = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(ps, ys)
    iso_c = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(pc, yc)

    def brier(p, y): return float(np.mean((p - y) ** 2))
    ps_cal = iso_s.predict(ps); pc_cal = iso_c.predict(pc)
    print(f"      score   Brier raw={brier(ps, ys):.4f} cal={brier(ps_cal, ys):.4f} "
          f"| mean raw={ps.mean():.3f} cal={ps_cal.mean():.3f} | base rate={ys.mean():.4f}")
    print(f"      concede Brier raw={brier(pc, yc):.4f} cal={brier(pc_cal, yc):.4f} "
          f"| mean raw={pc.mean():.3f} cal={pc_cal.mean():.3f} | base rate={yc.mean():.4f}")

    # Store calibration map as (sorted xs, ys) pairs we can interpolate later.
    cal = {
        "schema": "piecewise-linear-isotonic-v1",
        "val_matches": val_ids,
        "base_rate_score": float(ys.mean()),
        "base_rate_concede": float(yc.mean()),
        "brier_score_raw": brier(ps, ys),
        "brier_score_cal": brier(ps_cal, ys),
        "brier_concede_raw": brier(pc, yc),
        "brier_concede_cal": brier(pc_cal, yc),
        "score": {
            "x": iso_s.X_thresholds_.tolist(),
            "y": iso_s.y_thresholds_.tolist(),
        },
        "concede": {
            "x": iso_c.X_thresholds_.tolist(),
            "y": iso_c.y_thresholds_.tolist(),
        },
    }
    OUT.write_text(json.dumps(cal, indent=2))
    print(f"      wrote {OUT}")

    print(f"[4/4] Applying calibration to clips in {CLIPS_DIR}")
    apply_to_clips(iso_s, iso_c)
    print(f"[5/5] Applying calibration to whiteboard_moves.json")
    apply_to_whiteboard(iso_s, iso_c)


def apply_to_clips(iso_s: IsotonicRegression, iso_c: IsotonicRegression) -> None:
    n_clips = 0; n_frames = 0
    for p in sorted(CLIPS_DIR.glob("*.json")):
        if p.name == "index.json":
            continue
        data = json.loads(p.read_text())
        frames = data.get("frames") or []
        if not frames:
            continue
        # Idempotency: if this clip has been calibrated before, p_score_raw
        # holds the true raw model output — use that as input, not the
        # already-calibrated p_score field.
        has_raw = "p_score_raw" in frames[0]
        src_ps = "p_score_raw" if has_raw else "p_score"
        src_pc = "p_concede_raw" if has_raw else "p_concede"
        raw_ps = np.array([f.get(src_ps, 0.0) for f in frames], dtype=np.float64)
        raw_pc = np.array([f.get(src_pc, 0.0) for f in frames], dtype=np.float64)
        cal_ps = iso_s.predict(raw_ps)
        cal_pc = iso_c.predict(raw_pc)
        for i, f in enumerate(frames):
            f["p_score_raw"] = float(raw_ps[i])
            f["p_concede_raw"] = float(raw_pc[i])
            f["p_score"] = float(cal_ps[i])
            f["p_concede"] = float(cal_pc[i])
            f["vaep"] = float(cal_ps[i]) - float(cal_pc[i])
        data.setdefault("meta", {})["pscore_calibration"] = "isotonic-v1"
        p.write_text(json.dumps(data, indent=2))
        n_clips += 1; n_frames += len(frames)
        print(f"      {p.name}: {len(frames)} frames | "
              f"raw ps peak={raw_ps.max():.3f} cal peak={cal_ps.max():.3f}")
    print(f"      calibrated {n_clips} clips, {n_frames} frames total")


def apply_to_whiteboard(iso_s: IsotonicRegression, iso_c: IsotonicRegression) -> None:
    """Calibrate whiteboard_moves.json: baseline frames AND per-move counterfactual
    trajectories. Also recompute the per-move deltas (d_score / d_concede / d_net)
    from the calibrated values so the diff against the calibrated baseline stays
    internally consistent.
    """
    wb_path = REPO / "research" / "site" / "data" / "whiteboard_moves.json"
    if not wb_path.exists():
        print(f"      (skip) {wb_path} not found")
        return
    plays = json.loads(wb_path.read_text())
    n_plays = 0; n_moves = 0
    for play in plays:
        frames = play.get("frames") or []
        if frames:
            has_raw = "p_score_raw" in frames[0]
            src_ps = "p_score_raw" if has_raw else "p_score"
            src_pc = "p_concede_raw" if has_raw else "p_concede"
            raw_ps = np.array([f.get(src_ps, 0.0) for f in frames], dtype=np.float64)
            raw_pc = np.array([f.get(src_pc, 0.0) for f in frames], dtype=np.float64)
            cal_ps = iso_s.predict(raw_ps)
            cal_pc = iso_c.predict(raw_pc)
            for i, f in enumerate(frames):
                f["p_score_raw"] = float(raw_ps[i])
                f["p_concede_raw"] = float(raw_pc[i])
                f["p_score"] = float(cal_ps[i])
                f["p_concede"] = float(cal_pc[i])
            base_ps = cal_ps; base_pc = cal_pc
        else:
            base_ps = base_pc = None

        for move in play.get("moves") or []:
            pf = move.get("per_frame") or {}
            src_ps = "p_score_raw" if "p_score_raw" in pf else "p_score"
            src_pc = "p_concede_raw" if "p_concede_raw" in pf else "p_concede"
            raw_ps = np.array(pf.get(src_ps, []), dtype=np.float64)
            raw_pc = np.array(pf.get(src_pc, []), dtype=np.float64)
            if raw_ps.size == 0:
                continue
            cal_ps = iso_s.predict(raw_ps)
            cal_pc = iso_c.predict(raw_pc)
            pf["p_score_raw"] = raw_ps.tolist()
            pf["p_concede_raw"] = raw_pc.tolist()
            pf["p_score"] = cal_ps.tolist()
            pf["p_concede"] = cal_pc.tolist()
            if base_ps is not None and base_ps.size == cal_ps.size:
                pf["d_score"] = (cal_ps - base_ps).tolist()
                pf["d_concede"] = (cal_pc - base_pc).tolist()
                pf["d_net"] = ((cal_ps - base_ps) - (cal_pc - base_pc)).tolist()
            n_moves += 1
        n_plays += 1
        print(f"      {play.get('label')}: {len(frames)} baseline frames + "
              f"{len(play.get('moves') or [])} moves recalibrated")
    wb_path.write_text(json.dumps(plays, indent=2))
    print(f"      wrote {wb_path} ({n_plays} plays, {n_moves} moves)")


if __name__ == "__main__":
    main()
