"""Augment existing interactive-play clip JSONs with the score-specialist's
per-frame ball→player attention.

For each clip JSON in ``research/site/data/clips/*.json`` listed in
``index.json``, this re-runs the **score specialist** checkpoint over the
same window (match_id, period, start_s, end_s) at the same stride and
appends an ``attention_score_specialist`` field to every frame. The
existing shared-model ``attention`` field is left untouched.

This is intentionally narrow — it does NOT re-render PNGs and does NOT
recompute p_score/p_concede or any other per-frame field. Only the new
attention key is added.

Usage:
    PYTHONPATH=src uv run python scripts/add_score_specialist_attention.py \
        --ckpt output/transformer_score_only.ckpt

The script aligns the freshly-loaded tracking tensor to each clip JSON's
existing frames by ``frame_id``. If lengths don't match we error loudly
rather than silently mis-aligning attention rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "research" / "scripts"))

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.pff import load_pff_match
from wc2026_tracking_transformer.model.frame_vaep_specialist import (
    FrameVaepSpecialistLitModule,
)

try:
    from extract_transformer_features import _load_match_frames_and_slots  # type: ignore
except Exception:  # pragma: no cover
    _load_match_frames_and_slots = None  # type: ignore


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _process_clip(clip_path: Path, lit: FrameVaepSpecialistLitModule,
                  device: torch.device, stride: int, smooth_alpha: float) -> None:
    payload = json.loads(clip_path.read_text())
    match_id = str(payload["match_id"])
    period = int(payload["period"])
    start_s = float(payload["start_s"])
    end_s = float(payload["end_s"])
    print(f"[{clip_path.name}] match={match_id} period={period} "
          f"{start_s}-{end_s}s n_frames(json)={payload['n_frames']}")

    if _load_match_frames_and_slots is not None:
        frames_all, _slots_all = _load_match_frames_and_slots(
            match_id, sampling_stride=stride)
    else:
        frames_all = list(load_pff_match(match_id, sampling_stride=stride))

    clip_frames = [f for f in frames_all
                   if f.period == period and start_s <= f.timestamp_ms / 1000.0 <= end_s]
    if not clip_frames:
        raise SystemExit(f"no frames in window for {clip_path.name}")
    if len(clip_frames) != payload["n_frames"]:
        raise SystemExit(
            f"frame count mismatch for {clip_path.name}: "
            f"loaded {len(clip_frames)} vs JSON {payload['n_frames']}"
        )

    # Sanity check: frame_id alignment between freshly-loaded clip and JSON.
    json_ids = [f.get("frame_id") for f in payload["frames"]]
    new_ids = [f.frame_id for f in clip_frames]
    if json_ids and json_ids[0] is not None and json_ids != new_ids:
        # Some clips may have null frame_ids; only error if explicit mismatch.
        mismatches = sum(1 for a, b in zip(json_ids, new_ids) if a != b)
        raise SystemExit(
            f"frame_id alignment mismatch for {clip_path.name}: "
            f"{mismatches} mismatched ids"
        )

    tensors = batch_frames(clip_frames)
    x = torch.from_numpy(tensors).to(device)
    with torch.no_grad():
        _enc, attn = lit.encode_with_attention(x)
        # attn: (B, layers, heads, T, T) — mean over layers + heads, then take
        # the ball-token row (slot 22) over the 22 player columns.
        attn_mean = attn.mean(dim=(1, 2)).cpu().numpy()
        attn_ball = attn_mean[:, 22, :22]
        attn_ball = attn_ball / np.maximum(attn_ball.sum(axis=1, keepdims=True), 1e-9)

    # Match the smoothing used by the original renderer so the two attention
    # signals are comparable frame-for-frame (same temporal filter).
    alpha = float(smooth_alpha)
    sm = np.zeros_like(attn_ball)
    sm[0] = attn_ball[0]
    for i in range(1, attn_ball.shape[0]):
        sm[i] = alpha * attn_ball[i] + (1 - alpha) * sm[i - 1]
    attn_ball = sm

    for i, frame in enumerate(payload["frames"]):
        frame["attention_score_specialist"] = [float(a) for a in attn_ball[i]]

    clip_path.write_text(json.dumps(payload, indent=2))
    print(f"[{clip_path.name}] wrote attention_score_specialist for "
          f"{len(payload['frames'])} frames")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="output/transformer_score_only.ckpt")
    ap.add_argument("--stride", type=int, default=6)
    ap.add_argument("--smooth-alpha", type=float, default=0.55)
    ap.add_argument(
        "--clips-dir",
        default="research/site/data/clips",
        help="Directory containing index.json + per-clip JSONs.",
    )
    args = ap.parse_args()

    device = _device()
    lit = FrameVaepSpecialistLitModule.load_from_checkpoint(
        args.ckpt, map_location=device)
    lit.eval().to(device)

    clips_dir = REPO / args.clips_dir
    index = json.loads((clips_dir / "index.json").read_text())
    for entry in index:
        clip_path = clips_dir / f"{entry['label']}.json"
        if not clip_path.exists():
            print(f"skip {clip_path} (missing)")
            continue
        _process_clip(clip_path, lit, device, args.stride, args.smooth_alpha)


if __name__ == "__main__":
    main()
