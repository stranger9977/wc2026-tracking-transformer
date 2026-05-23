"""Train the frame-level VAEP transformer on PFF WC22.

Two BCE heads (P_score, P_concede) on the shared transformer backbone.
Targets are derived from goal events with a configurable look-ahead.

Usage:
    PYTHONPATH=src uv run python scripts/train_frame_vaep.py --pff-n 60 --epochs 6
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Iterable

import lightning.pytorch as pl
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.pff import (load_pff_match,
                                                            list_pff_matches)
from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule
from wc2026_tracking_transformer.tasks.frame_vaep_labels import (build_labels,
                                                                   goals_from_pff_events)

PFF_STRIDE = 6  # 30 Hz native -> 5 Hz output
FRAME_RATE_HZ = 5.0
LOOK_AHEAD_S = 10.0


def _load_goals_for_match(match_id: str, pff_root: Path | None = None) -> list:
    """Read the PFF event JSON for `match_id` and extract goal events."""
    import json
    from wc2026_tracking_transformer.data.loaders.pff import _resolve_match_paths
    meta_path, events_path, _ = _resolve_match_paths(match_id, pff_root)
    events = json.loads(events_path.read_text())
    return goals_from_pff_events(events)


class FrameVaepDataset(Dataset):
    def __init__(self, frames: np.ndarray, y_score: np.ndarray, y_concede: np.ndarray) -> None:
        assert frames.shape[0] == y_score.shape[0] == y_concede.shape[0]
        self.frames = frames
        self.y_score = y_score
        self.y_concede = y_concede

    def __len__(self) -> int:
        return self.frames.shape[0]

    def __getitem__(self, idx: int):
        return (
            torch.from_numpy(self.frames[idx]),
            torch.tensor(self.y_score[idx], dtype=torch.float32),
            torch.tensor(self.y_concede[idx], dtype=torch.float32),
        )


def build_source(match_id: str) -> dict | None:
    """Load PFF tracking + goals + labels for one match."""
    frames = list(load_pff_match(match_id, sampling_stride=PFF_STRIDE))
    if not frames:
        return None
    goals = _load_goals_for_match(match_id)
    y_score, y_concede = build_labels(frames, goals, k_seconds=LOOK_AHEAD_S)
    tensors = batch_frames(frames)
    n = min(tensors.shape[0], y_score.shape[0])
    return {
        "match_id": match_id,
        "frames": tensors[:n],
        "y_score": y_score[:n],
        "y_concede": y_concede[:n],
        "n_goals": len(goals),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pff-n", type=int, default=64, help="Number of PFF matches to load.")
    ap.add_argument("--val-n", type=int, default=8, help="Last N matches held out as validation.")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--model-dim", type=int, default=64)
    ap.add_argument("--num-heads", type=int, default=4)
    ap.add_argument("--num-layers", type=int, default=2)
    ap.add_argument("--lr", type=float, default=3e-4)
    args = ap.parse_args()

    print(f"[1/4] Loading PFF tracking + goals for {args.pff_n} matches …")
    t0 = time.time()
    pff_matches = list_pff_matches()
    if not pff_matches:
        raise RuntimeError("No PFF matches found — set PFF_ROOT or check paths.")
    use = pff_matches[: args.pff_n]
    sources: list[dict] = []
    for i, m in enumerate(use):
        match_id = m.name
        try:
            src = build_source(match_id)
        except Exception as e:
            print(f"   skip {match_id}: {e}")
            continue
        if src is not None:
            sources.append(src)
            pos_s = int(src["y_score"].sum())
            pos_c = int(src["y_concede"].sum())
            n_frames = src["frames"].shape[0]
            print(f"   {i+1}/{len(use)} {match_id}: frames={n_frames}  goals={src['n_goals']}  "
                  f"pos_score={pos_s}  pos_concede={pos_c}")
    print(f"loaded {len(sources)} matches in {time.time() - t0:.1f}s")

    train_srcs = sources[: -args.val_n] if args.val_n > 0 else sources
    val_srcs = sources[-args.val_n:] if args.val_n > 0 else []

    def concat(src_list: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        f = np.concatenate([s["frames"] for s in src_list]) if src_list else np.empty((0, 23, 7), dtype=np.float32)
        s = np.concatenate([s["y_score"] for s in src_list]) if src_list else np.empty((0,), dtype=np.float32)
        c = np.concatenate([s["y_concede"] for s in src_list]) if src_list else np.empty((0,), dtype=np.float32)
        return f, s, c

    tr_f, tr_s, tr_c = concat(train_srcs)
    va_f, va_s, va_c = concat(val_srcs)
    print(f"train frames={tr_f.shape[0]}, val frames={va_f.shape[0]}")
    print(f"   train: score pos {tr_s.sum():.0f} ({100*tr_s.mean():.3f}%), "
          f"concede pos {tr_c.sum():.0f} ({100*tr_c.mean():.3f}%)")
    print(f"   val:   score pos {va_s.sum():.0f} ({100*va_s.mean():.3f}%), "
          f"concede pos {va_c.sum():.0f} ({100*va_c.mean():.3f}%)")

    # pos_weight scaled to the empirical class balance
    pos_w_score = max(1.0, (1.0 - tr_s.mean()) / max(tr_s.mean(), 1e-5))
    pos_w_concede = max(1.0, (1.0 - tr_c.mean()) / max(tr_c.mean(), 1e-5))
    pos_w_score = min(pos_w_score, 200.0)
    pos_w_concede = min(pos_w_concede, 200.0)
    print(f"   pos_weight: score={pos_w_score:.1f}, concede={pos_w_concede:.1f}")

    train_ds = FrameVaepDataset(tr_f, tr_s, tr_c)
    val_ds = FrameVaepDataset(va_f, va_s, va_c) if va_f.shape[0] > 0 else None
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, num_workers=0) if val_ds else None

    print(f"[2/4] Building model …")
    lit = FrameVaepLitModule(
        feature_len=7, model_dim=args.model_dim, num_heads=args.num_heads,
        num_layers=args.num_layers, dropout=0.1, head_hidden=128,
        learning_rate=args.lr,
        pos_weight_score=pos_w_score, pos_weight_concede=pos_w_concede,
    )

    print(f"[3/4] Training {args.epochs} epochs …")
    accelerator = "mps" if torch.backends.mps.is_available() else "cpu"
    trainer = pl.Trainer(
        max_epochs=args.epochs,
        accelerator=accelerator,
        devices=1,
        log_every_n_steps=50,
        enable_progress_bar=True,
    )
    trainer.fit(lit, train_loader, val_loader)

    print(f"[4/4] Saving …")
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    ckpt_path = out_dir / "transformer_frame_vaep.ckpt"
    trainer.save_checkpoint(str(ckpt_path))
    metrics = {k: float(v) for k, v in trainer.callback_metrics.items() if hasattr(v, "item")}
    (out_dir / "training_metrics_frame_vaep.json").write_text(json.dumps({
        "metrics": metrics,
        "n_train_frames": int(tr_f.shape[0]),
        "n_val_frames": int(va_f.shape[0]),
        "n_train_matches": len(train_srcs),
        "n_val_matches": len(val_srcs),
        "look_ahead_s": LOOK_AHEAD_S,
        "frame_rate_hz": FRAME_RATE_HZ,
    }, indent=2))
    print(f"  wrote {ckpt_path}")
    print(f"  val metrics: {metrics}")


if __name__ == "__main__":
    main()
