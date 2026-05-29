"""Add per-frame player-to-player pair attention to interactive-play clip JSONs.

For each clip in ``research/site/data/clips/*.json`` listed in ``index.json``,
re-runs the **score specialist** (and optionally the concede specialist) over
the same window, extracts the 23×23 token attention from the final encoder,
drops the ball-token row/column, symmetrizes, and saves the **top-K pairs per
frame** as a compact list:

    frame["pair_attention_score_top"] = [[slot_i, slot_j, weight], ...]   # K=15
    frame["pair_attention_concede_top"] = [...]   # if --include-concede

The full 22×22 matrix would be ~200 KB JSON per clip; top-K stays under 50 KB
and is what the frontend actually renders.

Usage:
    PYTHONPATH=src uv run python scripts/add_pair_attention.py \\
        --score-ckpt output/transformer_score_only.ckpt \\
        --concede-ckpt output/transformer_concede_only.ckpt \\
        --label morocco-portugal-en-nesyri      # one clip
    # omit --label to process every clip in index.json.
"""
from __future__ import annotations

import argparse
import json
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
except Exception:
    _load_match_frames_and_slots = None


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _extract_pair_top(lit: FrameVaepSpecialistLitModule, x: torch.Tensor,
                      top_k: int, smooth_alpha: float,
                      gk_slots: list[set[int]] | None = None) -> list[list[list]]:
    """Returns one list-of-pairs per frame: [[i, j, w], ...] length top_k.

    Pipeline:
      • model returns ``attn`` of shape (B, layers, heads, T=23, T=23)
      • mean over layers + heads → (B, 23, 23)
      • drop ball token (slot 22): take [:, :22, :22]
      • symmetrize: M = (M + M.T) / 2 — pair chemistry is undirected
      • temporal EMA across frames (matches the ball-attention smoothing)
      • per-frame: pick top-K pairs from the upper triangle
    """
    with torch.no_grad():
        _enc, attn = lit.encode_with_attention(x)
        m = attn.mean(dim=(1, 2)).cpu().numpy()  # (B, 23, 23)
    pair = m[:, :22, :22]
    pair = 0.5 * (pair + pair.transpose(0, 2, 1))
    # Temporal smoothing (causal EMA) so per-frame top-K is stable instead of
    # snapping to a different pair every 200 ms.
    sm = np.zeros_like(pair)
    sm[0] = pair[0]
    for i in range(1, pair.shape[0]):
        sm[i] = smooth_alpha * pair[i] + (1.0 - smooth_alpha) * sm[i - 1]
    pair = sm
    # Zero the diagonal (self-attention is huge and uninteresting for pairs).
    diag = np.arange(22)
    pair[:, diag, diag] = 0.0
    # Zero pairs that include either goalkeeper — they otherwise dominate
    # every defensive-third pair just by being on/near the ball constantly,
    # which is exactly why CLAUDE.md excludes them from chemistry rankings.
    # We use the per-frame GK set when available so a sub at GK is handled.
    if gk_slots is not None:
        for fi, gks in enumerate(gk_slots):
            for g in gks:
                pair[fi, g, :] = 0.0
                pair[fi, :, g] = 0.0
    # Per-frame top-K from upper triangle.
    iu, ju = np.triu_indices(22, k=1)  # 231 pairs
    out: list[list[list]] = []
    for fi in range(pair.shape[0]):
        w = pair[fi][iu, ju]
        # argpartition is faster than sort for top-K.
        if w.size <= top_k:
            order = np.argsort(w)[::-1]
        else:
            part = np.argpartition(-w, top_k)[:top_k]
            order = part[np.argsort(-w[part])]
        rows = [[int(iu[k]), int(ju[k]), float(w[k])] for k in order]
        out.append(rows)
    return out


def _process_clip(clip_path: Path, score_lit, concede_lit, device, stride: int,
                  top_k: int, smooth_alpha: float, include_concede: bool) -> None:
    payload = json.loads(clip_path.read_text())
    match_id = str(payload["match_id"])
    period = int(payload["period"])
    start_s = float(payload["start_s"])
    end_s = float(payload["end_s"])
    print(f"[{clip_path.name}] match={match_id} period={period} "
          f"{start_s}-{end_s}s n_frames(json)={payload['n_frames']}")

    if _load_match_frames_and_slots is not None:
        frames_all, _slots = _load_match_frames_and_slots(
            match_id, sampling_stride=stride)
    else:
        frames_all = list(load_pff_match(match_id, sampling_stride=stride))

    clip_frames = [f for f in frames_all
                   if f.period == period and start_s <= f.timestamp_ms / 1000.0 <= end_s]
    if not clip_frames:
        raise SystemExit(f"no frames in window for {clip_path.name}")
    # Some clips have a synthetic tail appended (ball going into net past the
    # data end). Process only the real-frame prefix; carry the last real
    # frame's pair-top into the synthetic frames after we're done.
    n_real_in_json = sum(1 for f in payload["frames"] if not f.get("is_synthetic"))
    if n_real_in_json != payload["n_frames"]:
        print(f"  ({clip_path.name}: {payload['n_frames'] - n_real_in_json} "
              f"synthetic tail frames will reuse last real pair-top)")
    if len(clip_frames) != n_real_in_json:
        raise SystemExit(
            f"frame count mismatch for {clip_path.name}: "
            f"loaded {len(clip_frames)} real vs JSON {n_real_in_json}"
        )
    json_ids = [f.get("frame_id") for f in payload["frames"][:n_real_in_json]]
    new_ids = [f.frame_id for f in clip_frames]
    if json_ids and json_ids[0] is not None and json_ids != new_ids:
        mismatches = sum(1 for a, b in zip(json_ids, new_ids) if a != b)
        raise SystemExit(
            f"frame_id alignment mismatch for {clip_path.name}: "
            f"{mismatches} mismatched ids"
        )

    tensors = batch_frames(clip_frames)
    x = torch.from_numpy(tensors).to(device)

    # Per-frame GK slot set. Read from the JSON (already correct), one set per
    # frame so a GK substitution doesn't poison the rest of the clip.
    gk_slots: list[set[int]] = []
    for f in payload["frames"]:
        gks = {p["slot"] for p in f["players"] if p.get("is_gk")}
        gk_slots.append(gks)

    # gk_slots is per-real-frame, but pair-top is also per-real-frame; pass
    # the prefix of length n_real_in_json so they align.
    real_gk_slots = gk_slots[:n_real_in_json]
    score_pairs = _extract_pair_top(score_lit, x, top_k, smooth_alpha, real_gk_slots)
    for i, frame in enumerate(payload["frames"]):
        if i < len(score_pairs):
            frame["pair_attention_score_top"] = score_pairs[i]
        else:
            # Synthetic tail: hold the last real frame's pair-top.
            frame["pair_attention_score_top"] = score_pairs[-1]

    if include_concede and concede_lit is not None:
        concede_pairs = _extract_pair_top(concede_lit, x, top_k, smooth_alpha, real_gk_slots)
        for i, frame in enumerate(payload["frames"]):
            if i < len(concede_pairs):
                frame["pair_attention_concede_top"] = concede_pairs[i]
            else:
                frame["pair_attention_concede_top"] = concede_pairs[-1]

    clip_path.write_text(json.dumps(payload, indent=2))
    print(f"[{clip_path.name}] wrote pair_attention_score_top "
          f"(K={top_k}) for {len(payload['frames'])} frames"
          + (" + concede" if include_concede else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score-ckpt", default="output/transformer_score_only.ckpt")
    ap.add_argument("--concede-ckpt", default="output/transformer_concede_only.ckpt")
    ap.add_argument("--include-concede", action="store_true",
                    help="Also emit pair_attention_concede_top from the concede specialist.")
    ap.add_argument("--stride", type=int, default=6)
    ap.add_argument("--top-k", type=int, default=15)
    ap.add_argument("--smooth-alpha", type=float, default=0.55)
    ap.add_argument("--label", default=None,
                    help="If set, only process this clip label (skip index.json).")
    ap.add_argument("--clips-dir", default="research/site/data/clips")
    args = ap.parse_args()

    device = _device()
    print(f"device: {device}")
    score_lit = FrameVaepSpecialistLitModule.load_from_checkpoint(
        args.score_ckpt, map_location=device).eval().to(device)
    concede_lit = None
    if args.include_concede:
        concede_lit = FrameVaepSpecialistLitModule.load_from_checkpoint(
            args.concede_ckpt, map_location=device).eval().to(device)

    clips_dir = REPO / args.clips_dir
    if args.label:
        clip_paths = [clips_dir / f"{args.label}.json"]
    else:
        index = json.loads((clips_dir / "index.json").read_text())
        clip_paths = [clips_dir / f"{e['label']}.json" for e in index]

    for cp in clip_paths:
        if not cp.exists():
            print(f"skip {cp} (missing)")
            continue
        _process_clip(cp, score_lit, concede_lit, device, args.stride,
                      args.top_k, args.smooth_alpha, args.include_concede)


if __name__ == "__main__":
    main()
