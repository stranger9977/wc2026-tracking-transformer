"""Render a PFF match GIF with WC team colors + player names.

Usage:
    uv run python scripts/render_pff_gif.py --match 10502 \
        --ckpt output/transformer_xt_regression.ckpt --window peak
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import torch

warnings.filterwarnings("ignore")

from kloppy import pff

from wc2026_tracking_transformer.baselines.xt import xt_now
from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.pff import (
    _resolve_match_paths,
    load_pff_match,
)
from wc2026_tracking_transformer.data.team_colors import team_color
from wc2026_tracking_transformer.model import XTRegressionLitModule

OUT_DIR = Path(__file__).resolve().parent.parent / "output"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="10502")
    ap.add_argument("--ckpt", default=str(OUT_DIR / "transformer_xt_regression.ckpt"))
    ap.add_argument("--stride", type=int, default=6)
    ap.add_argument("--window", choices=("peak", "all"), default="peak",
                    help="peak = 12s ending at model's max-prediction frame. "
                         "all = (not implemented; future) full match.")
    ap.add_argument("--window-frames", type=int, default=60, help="frames in the clip")
    ap.add_argument("--model-dim", type=int, default=96)
    args = ap.parse_args()

    print(f"[1/4] Loading checkpoint + match {args.match} …")
    lit = XTRegressionLitModule(
        feature_len=7, model_dim=args.model_dim, num_heads=4, num_layers=2,
    )
    lit.load_state_dict(torch.load(args.ckpt, map_location="cpu"))
    lit.eval()

    frames = list(load_pff_match(args.match, sampling_stride=args.stride))
    tensors = batch_frames(frames)
    x = torch.from_numpy(tensors)
    print(f"      {len(frames)} frames")

    with torch.no_grad():
        encoded, attn = lit.backbone.encode_with_attention(x)
        preds = lit.head(encoded).numpy()
    lookup = xt_now(tensors)

    print(f"[2/4] Loading PFF metadata for player names + teams …")
    meta_p, roster_p, tracking_p = _resolve_match_paths(args.match)
    raw = pff.load_tracking(
        meta_data=meta_p, roster_meta_data=roster_p, raw_data=tracking_p,
        only_alive=True,
    )
    team_names = {t.team_id: (t.name or t.team_id) for t in raw.metadata.teams}
    print(f"      teams: {team_names}")

    frame_meta: dict[int, tuple[list, list]] = {}
    for rf in raw.frames:
        items = list(rf.players_data.items())
        frame_meta[int(rf.frame_id)] = (
            [p.jersey_no for p, _ in items],
            [p.team.team_id for p, _ in items],
        )

    print(f"[3/4] Picking peak-prediction window …")
    W = args.window_frames
    peak = int(np.argmax(preds))
    b_s = max(0, peak - W + 1); b_e = b_s + W
    print(f"      window frames {b_s}-{b_e}, peak pred={preds[peak]:.4f}")

    ct = x[b_s:b_e]
    cattn = attn[b_s:b_e]
    cchem = cattn.mean(dim=(1, 2)).numpy()
    cps = preds[b_s:b_e]; cpg = lookup[b_s:b_e]
    cj, ct_ = [], []
    for tf in frames[b_s:b_e]:
        jerseys, teams = frame_meta.get(tf.frame_id, ([], []))
        cj.append(jerseys); ct_.append(teams)

    print(f"[4/4] Rendering GIF …")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from clip_renderer import render_clip  # type: ignore

    team_ids = list(team_names.keys())
    color_map = {tid: team_color(tid) for tid in team_ids}
    out_path = OUT_DIR / f"attention_pff_{args.match}.gif"
    team_names_str = " vs ".join(team_names.values())
    render_clip(
        out_path=out_path,
        clip_tensors=ct, clip_chem=cchem,
        clip_p_shot=cps, clip_p_goal=cpg,
        clip_jerseys=cj, clip_teams=ct_,
        top_banner=f"{team_names_str} · WC '22 · 12s peak-prediction window",
        fps=6,
        head0_label="Our predicted future-xT",
        head1_label="xT-lookup baseline",
        team_color_map=color_map,
        team_label_map=team_names,
    )
    print(f"      → {out_path.name}")


if __name__ == "__main__":
    main()
