"""Render a step-throughable interactive play clip.

Given a PFF match and a (period, start_s, end_s) window:

1. Load the tracking frames at 5 Hz inside the window.
2. Run the frame-level VAEP transformer to get per-frame
   (p_score, p_concede, ball-token attention vector).
3. Emit, per frame:
     - frame_NNN.png   — pitch snapshot with player dots + attention edges
                          (top-3 same-team, top-2 cross-team), heatmap of
                          location-derived xT for visual context.
     - data/frames.json — per-frame {p_score, p_concede, top_attended_players}
4. Bundle into research/site/assets/clips/<clip_id>/ and write
   research/site/data/clips/<clip_id>.json with metadata.

Usage:
    PYTHONPATH=src uv run python scripts/render_interactive_clip.py \
        --match 10517 --period 1 --start 2080 --end 2110 --label argentina-france-di-maria
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.pff import load_pff_match
from wc2026_tracking_transformer.data.schema import PITCH_LENGTH_M, PITCH_WIDTH_M
from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule

PITCH_COLOR = "#0d4d2c"
LINE_COLOR = "#dceadb"
HOME_COLOR = "#5eead4"
AWAY_COLOR = "#f87171"


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def draw_pitch(ax: plt.Axes) -> None:
    ax.set_facecolor(PITCH_COLOR)
    L, W = PITCH_LENGTH_M, PITCH_WIDTH_M
    HL, HW = L / 2, W / 2
    ax.set_xlim(-HL - 2, HL + 2)
    ax.set_ylim(-HW - 2, HW + 2)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.add_patch(mpatches.Rectangle((-HL, -HW), L, W, fill=False,
                                    edgecolor=LINE_COLOR, linewidth=1.4))
    ax.plot([0, 0], [-HW, HW], color=LINE_COLOR, linewidth=1.2)
    ax.add_patch(mpatches.Circle((0, 0), 9.15, fill=False, edgecolor=LINE_COLOR, linewidth=1.2))
    # penalty boxes
    pen_w, pen_d = 40.32, 16.5
    ax.add_patch(mpatches.Rectangle((-HL, -pen_w / 2), pen_d, pen_w, fill=False,
                                    edgecolor=LINE_COLOR, linewidth=1.2))
    ax.add_patch(mpatches.Rectangle((HL - pen_d, -pen_w / 2), pen_d, pen_w, fill=False,
                                    edgecolor=LINE_COLOR, linewidth=1.2))


def render_frame(
    out_path: Path,
    frame_tensor: np.ndarray,
    attn_ball: np.ndarray,
    p_score: float, p_concede: float,
    label: str,
    in_possession_team_id: str | None,
    frame_idx: int,
    n_total: int,
) -> dict:
    fig, ax = plt.subplots(figsize=(8.5, 5.5), dpi=130, facecolor="#0b1220")
    draw_pitch(ax)
    HL, HW = PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2
    xy = frame_tensor[:22, :2].copy()
    xy[:, 0] *= HL
    xy[:, 1] *= HW
    side = frame_tensor[:22, 4]  # is_attacking_side (+1 attacker, -1 defender)
    is_gk = frame_tensor[:22, 5] > 0.5
    colors = [HOME_COLOR if s > 0 else AWAY_COLOR for s in side]
    ax.scatter(xy[:, 0], xy[:, 1], c=colors, s=180, edgecolor="white",
               linewidth=1.0, zorder=3, alpha=0.95)
    if is_gk.any():
        ax.scatter(xy[is_gk, 0], xy[is_gk, 1], s=420, facecolors="none",
                   edgecolor="#00d68f", linewidth=2.0, zorder=2)
    # Ball
    bx = frame_tensor[22, 0] * HL
    by = frame_tensor[22, 1] * HW
    ax.scatter([bx], [by], c="#ffd166", s=110, edgecolor="white",
               linewidth=1.0, zorder=4)

    # Top-3 attended-by-ball players: highlight halo, draw edge ball→player
    top_idx = np.argsort(-attn_ball)[:3].tolist()
    top_players = []
    for slot in top_idx:
        px, py = xy[slot]
        ax.add_patch(mpatches.Circle((px, py), 2.6, fill=False,
                                     edgecolor="#ffd166", linewidth=2.2, zorder=5))
        ax.plot([bx, px], [by, py], color="#fde047", linewidth=2.0, alpha=0.7, zorder=4)
        top_players.append({"slot": int(slot), "attention": float(attn_ball[slot])})

    ax.text(0, HW + 1.2, label, ha="center", va="bottom", color="white",
            fontsize=13, fontweight="bold")
    ax.text(-HL, -HW - 0.6, f"frame {frame_idx+1}/{n_total}",
            ha="left", va="top", color="#9aa5b1", fontsize=10)
    # P-score / P-concede chips bottom-right
    ax.text(HL, -HW - 0.6,
            f"P(score next 10s) = {p_score:.3f}    P(concede) = {p_concede:.3f}",
            ha="right", va="top", color="#e6edf3", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, facecolor="#0b1220", bbox_inches="tight")
    plt.close(fig)
    return {"top_attended": top_players, "ball_xy": [float(bx), float(by)]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", required=True)
    ap.add_argument("--period", type=int, default=1)
    ap.add_argument("--start", type=float, required=True,
                    help="Absolute game-clock seconds at the start of the clip")
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--label", required=True, help="Slug for the clip directory")
    ap.add_argument("--title", default=None, help="Display title for the clip")
    ap.add_argument("--ckpt", default="output/transformer_frame_vaep.ckpt")
    ap.add_argument("--stride", type=int, default=6, help="PFF frame stride (6 → 5 Hz)")
    args = ap.parse_args()

    title = args.title or args.label.replace("-", " ").title()
    device = _device()
    lit = FrameVaepLitModule.load_from_checkpoint(args.ckpt, map_location=device)
    lit.eval().to(device)

    frames_all = list(load_pff_match(args.match, sampling_stride=args.stride))
    print(f"loaded {len(frames_all)} frames for match {args.match}")

    # Filter to clip window
    clip_frames = [f for f in frames_all
                   if f.period == args.period
                   and args.start <= f.timestamp_ms / 1000.0 <= args.end]
    if not clip_frames:
        raise SystemExit(f"no frames in window: period {args.period} {args.start}-{args.end}")
    print(f"clip: {len(clip_frames)} frames")

    tensors = batch_frames(clip_frames)
    x = torch.from_numpy(tensors).to(device)
    with torch.no_grad():
        encoded, attn = lit.encode_with_attention(x)
        ps = torch.sigmoid(lit.score_head(encoded)).cpu().numpy()
        pc = torch.sigmoid(lit.concede_head(encoded)).cpu().numpy()
        # attn shape (B, L, H, T, T). Mean across layers + heads, take ball row (idx 22)
        attn_mean = attn.mean(dim=(1, 2)).cpu().numpy()       # (B, T, T)
        attn_ball = attn_mean[:, 22, :22]                     # (B, 22)
        attn_ball = attn_ball / np.maximum(attn_ball.sum(axis=1, keepdims=True), 1e-9)

    # Output
    clip_dir = REPO / "research" / "site" / "assets" / "clips" / args.label
    clip_dir.mkdir(parents=True, exist_ok=True)
    site_data_dir = REPO / "research" / "site" / "data" / "clips"
    site_data_dir.mkdir(parents=True, exist_ok=True)

    per_frame: list[dict] = []
    for i, f in enumerate(clip_frames):
        png_path = clip_dir / f"frame_{i:03d}.png"
        meta = render_frame(
            png_path, tensors[i], attn_ball[i],
            float(ps[i]), float(pc[i]), title,
            f.in_possession_team_id, i, len(clip_frames),
        )
        meta.update({
            "frame_idx": i,
            "frame_id": f.frame_id,
            "period": f.period,
            "timestamp_ms": int(f.timestamp_ms),
            "in_possession_team_id": f.in_possession_team_id,
            "p_score": float(ps[i]),
            "p_concede": float(pc[i]),
            "vaep": float(ps[i]) - float(pc[i]),
        })
        per_frame.append(meta)

    out = {
        "label": args.label,
        "title": title,
        "match_id": args.match,
        "period": args.period,
        "start_s": args.start,
        "end_s": args.end,
        "n_frames": len(per_frame),
        "frames": per_frame,
        "image_pattern": f"assets/clips/{args.label}/frame_{{idx:03d}}.png",
    }
    (site_data_dir / f"{args.label}.json").write_text(json.dumps(out, indent=2))
    print(f"wrote {len(per_frame)} frame PNGs + {site_data_dir / f'{args.label}.json'}")


if __name__ == "__main__":
    main()
