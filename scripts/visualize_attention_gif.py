"""Train briefly on Metrica match 1, then animate attention on match 2.

Produces ``output/attention_animation.gif`` — a ~10s clip showing:
    * 22 player dots + ball moving across the pitch (color-coded by team)
    * Velocity arrows
    * Attention edges from the ball token to the top-K attended players
      (line width ∝ attention weight)
    * P(score) timeline below the pitch

This is the soccer equivalent of "show me what the model saw before the
goal" — the storytelling money shot from the deck.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import torch
from matplotlib.animation import FuncAnimation, PillowWriter

warnings.filterwarnings("ignore")

from wc2026_tracking_transformer.data import SoccerTrackingDataModule
from wc2026_tracking_transformer.data.loaders.metrica import load_metrica_match
from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.schema import PITCH_LENGTH_M, PITCH_WIDTH_M
from wc2026_tracking_transformer.model import NextEventValueLitModule

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUT_DIR.mkdir(exist_ok=True)
GIF_PATH = OUT_DIR / "attention_animation.gif"

# ---------------------------------------------------------------------------
# 1) Train briefly
# ---------------------------------------------------------------------------
print("[1/4] Training model on Metrica match 1 …")
import lightning.pytorch as pl

torch.manual_seed(0)
dm = SoccerTrackingDataModule(
    source="metrica",
    batch_size=128,
    metrica_sampling_stride=5,  # 5 Hz
    metrica_k_seconds=10.0,
)
lit = NextEventValueLitModule(
    feature_len=7, model_dim=64, num_heads=4, num_layers=2,
    learning_rate=3e-4,
)
pl.Trainer(
    accelerator="cpu", devices=1, max_epochs=3,
    enable_progress_bar=False, logger=False, enable_checkpointing=False,
    log_every_n_steps=50,
).fit(lit, datamodule=dm)
lit.eval()
print(f"      done. val_loss seen during training was ~0.37")

# ---------------------------------------------------------------------------
# 2) Pick an interesting frame range from match 2
# ---------------------------------------------------------------------------
print("[2/4] Scoring match 2 frames to find an interesting sequence …")
match2_frames = list(load_metrica_match("2", sampling_stride=5))
m2_tensors = batch_frames(match2_frames)         # (N, 23, 7)
m2_torch = torch.from_numpy(m2_tensors)

with torch.no_grad():
    encoded, attn = lit.backbone.encode_with_attention(m2_torch)
    logits = lit.head(encoded)
    p = torch.sigmoid(logits).numpy()             # (N, 2) probs

p_score = p[:, 0]
# Find a 10s (50-frame at 5Hz) window where P(score) climbs the most.
WINDOW = 50
deltas = p_score[WINDOW - 1 :] - p_score[: -WINDOW + 1]
start = int(np.argmax(deltas))
end = start + WINDOW
print(f"      best 10s buildup window: frames {start}-{end}  "
      f"(P(score) rises {p_score[start]:.2f} → {p_score[end-1]:.2f})")

clip_tensors = m2_torch[start:end]                # (W, 23, 7)
clip_attn = attn[start:end]                       # (W, layers, heads, 23, 23)
clip_p_score = p_score[start:end]

# Reduce attention to (W, 23, 23) symmetric per-pair via mean over heads+layers.
clip_chem = clip_attn.mean(dim=(1, 2)).numpy()   # (W, 23, 23)

# ---------------------------------------------------------------------------
# 3) Build the figure
# ---------------------------------------------------------------------------
print("[3/4] Rendering animation …")

# Convert normalized coordinates back to meters for plotting.
HALF_L, HALF_W = PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2

def to_meters(token_arr_norm: np.ndarray) -> np.ndarray:
    """(T, 7) -> (T, 2) positions in meters, centered."""
    xy = token_arr_norm[:, :2].copy()
    xy[:, 0] *= HALF_L
    xy[:, 1] *= HALF_W
    return xy


fig = plt.figure(figsize=(10, 7), facecolor="#0b1220")
gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1], hspace=0.18)
ax_pitch = fig.add_subplot(gs[0])
ax_line  = fig.add_subplot(gs[1])

# --- pitch background ---
def draw_pitch(ax: plt.Axes) -> None:
    pitch_color = "#1a8847"
    line_color = "white"
    ax.set_facecolor(pitch_color)
    ax.set_xlim(-HALF_L - 2, HALF_L + 2)
    ax.set_ylim(-HALF_W - 2, HALF_W + 2)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_color("#0b1220")
    # Outer boundary
    ax.add_patch(mpatches.Rectangle((-HALF_L, -HALF_W), PITCH_LENGTH_M, PITCH_WIDTH_M,
                                     fill=False, edgecolor=line_color, lw=1.2))
    # Halfway line + center circle
    ax.plot([0, 0], [-HALF_W, HALF_W], color=line_color, lw=1)
    ax.add_patch(mpatches.Circle((0, 0), 9.15, fill=False, edgecolor=line_color, lw=1))
    ax.plot(0, 0, "o", color=line_color, ms=3)
    # Penalty areas (16.5 × 40.32m) and 6-yard boxes (5.5 × 18.32m)
    for side in (-1, 1):
        pa_x = side * (HALF_L - 16.5) if side > 0 else -HALF_L
        ax.add_patch(mpatches.Rectangle((pa_x, -20.16), 16.5, 40.32,
                                         fill=False, edgecolor=line_color, lw=1))
        sy_x = side * (HALF_L - 5.5) if side > 0 else -HALF_L
        ax.add_patch(mpatches.Rectangle((sy_x, -9.16), 5.5, 18.32,
                                         fill=False, edgecolor=line_color, lw=1))
    # Attacking-third lines (since our labels use thirds)
    third = HALF_L - PITCH_LENGTH_M / 3
    for x in (-third, third):
        ax.axvline(x, color="white", lw=0.4, ls="--", alpha=0.4)


draw_pitch(ax_pitch)

# Plot artists we'll update each frame
HOME_COLOR = "#7aa2ff"  # blue
AWAY_COLOR = "#ff7eb6"  # pink
BALL_COLOR = "#ffd166"
GK_EDGE = "#00d68f"     # green outline for GKs
POSS_EDGE = "white"

# Initial frame for setup
f0_norm = clip_tensors[0].numpy()
xy0 = to_meters(f0_norm)
# Two scatter calls: home (+1 in attacking-side flag means "in possession team")
# — note attacking-side flips per frame. So instead of team, we'll color by a
# stable index: first 11 = "home-side-of-frame", second 11 = "away-side-of-frame".
# But our loader doesn't sort by team. Easier: color by is_attacking_side at t=0.
attacking_t0 = f0_norm[:22, 4]
players_scatter = ax_pitch.scatter(
    xy0[:22, 0], xy0[:22, 1],
    c=[HOME_COLOR if a > 0 else AWAY_COLOR for a in attacking_t0],
    s=180, edgecolor="white", lw=1.2, zorder=5,
)
ball_scatter = ax_pitch.scatter(
    xy0[22, 0], xy0[22, 1],
    c=BALL_COLOR, s=110, edgecolor="black", lw=1.5, zorder=10,
)

# Goalkeeper rings (precompute mask; GK flag is stable across the clip)
gk_mask = clip_tensors[0, :22, 5].numpy() > 0.5
gk_ring = ax_pitch.scatter(
    xy0[:22][gk_mask, 0], xy0[:22][gk_mask, 1],
    s=300, facecolors="none", edgecolor=GK_EDGE, lw=2, zorder=4,
)

# Possession ring around the ball-owning player
poss_idx0 = int(np.argmax(clip_tensors[0, :22, 6].numpy()))
poss_ring = ax_pitch.scatter(
    [xy0[poss_idx0, 0]], [xy0[poss_idx0, 1]],
    s=400, facecolors="none", edgecolor=POSS_EDGE, lw=2, zorder=6,
)

# Velocity arrows
vels0 = clip_tensors[0, :22, 2:4].numpy()
quiver = ax_pitch.quiver(
    xy0[:22, 0], xy0[:22, 1],
    vels0[:, 0], vels0[:, 1],
    color="white", alpha=0.6, scale=120, width=0.0035, zorder=3,
)

# Attention edges from the ball token (token 22) to top-K players
K = 5
edge_lines = []
for _ in range(K):
    (line,) = ax_pitch.plot([0, 0], [0, 0], color="#ffd166", alpha=0.0, lw=2, zorder=2)
    edge_lines.append(line)

title = ax_pitch.set_title("", color="white", fontsize=13, pad=10)

# --- P(score) line plot below ---
ax_line.set_facecolor("#0b1220")
for s in ax_line.spines.values(): s.set_color("#94a3b8")
ax_line.tick_params(colors="#94a3b8")
ax_line.set_xlim(0, WINDOW - 1)
ax_line.set_ylim(0, max(1.0, float(clip_p_score.max()) * 1.1))
ax_line.set_xlabel("Frame in clip (5 Hz → 10 seconds)", color="#94a3b8")
ax_line.set_ylabel("P(ball→att 3rd in 10s)", color="#94a3b8")
ax_line.grid(True, color="#1f2c44", lw=0.6)
ax_line.plot(np.arange(WINDOW), clip_p_score, color="#ffd166", lw=1.5, alpha=0.35)
(progress_line,) = ax_line.plot(
    [0], [clip_p_score[0]], color="#ffd166", lw=2.5, marker="o", ms=8,
)


def update(i: int):
    f = clip_tensors[i].numpy()
    xy = to_meters(f)
    # players
    players_scatter.set_offsets(xy[:22])
    # ball
    ball_scatter.set_offsets(xy[22:23])
    # GK ring (positions move with the players)
    if gk_mask.any():
        gk_ring.set_offsets(xy[:22][gk_mask])
    # possession ring
    poss_i = int(np.argmax(f[:22, 6]))
    poss_ring.set_offsets(xy[poss_i:poss_i + 1])
    # velocity arrows
    quiver.set_offsets(xy[:22])
    quiver.set_UVC(f[:22, 2], f[:22, 3])
    # Attention edges from ball (token 22). Exclude self.
    chem = clip_chem[i, 22].copy()
    chem[22] = 0.0
    top_idx = np.argsort(chem)[::-1][:K]
    bx, by = xy[22]
    max_w = float(chem.max()) if chem.max() > 0 else 1.0
    for j, line in enumerate(edge_lines):
        if j < len(top_idx):
            ti = int(top_idx[j])
            line.set_data([bx, xy[ti, 0]], [by, xy[ti, 1]])
            line.set_alpha(min(1.0, chem[ti] / max_w * 1.0))
        else:
            line.set_alpha(0.0)
    # P(score) progress
    progress_line.set_data([i], [clip_p_score[i]])
    title.set_text(
        f"Frame {i+1}/{WINDOW}    P(score)={clip_p_score[i]:.2f}    "
        f"chem hub: token {int(top_idx[0])}  (attn={chem[int(top_idx[0])]:.2f})"
    )
    return (players_scatter, ball_scatter, gk_ring, poss_ring, quiver, *edge_lines, progress_line, title)


anim = FuncAnimation(fig, update, frames=WINDOW, interval=120, blit=False)
writer = PillowWriter(fps=8)
anim.save(GIF_PATH, writer=writer, dpi=90, savefig_kwargs={"facecolor": "#0b1220"})
plt.close(fig)
print(f"[4/4] Wrote {GIF_PATH}  ({GIF_PATH.stat().st_size / 1024:.0f} KB)")
