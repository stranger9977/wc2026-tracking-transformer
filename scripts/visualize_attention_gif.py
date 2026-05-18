"""Train briefly on Metrica match 1 (real shot/goal labels), then animate
attention on the val match.

Produces TWO gifs in ``output/``:
    * ``attention_buildup.gif`` — the 12s window where the model's predicted
      probability of a shot/goal rises the most.
    * ``attention_goal.gif`` — the 15s leading up to a REAL goal in match 2.

Visual conventions:
    * Team colors with an in-figure legend.
    * Each player is a colored dot with their jersey number and a small
      direction arrowhead (no separate velocity quivers).
    * Top-3 attended tokens (from the ball) get radiating halos.
    * Attention edges from the ball drawn darker, thicker, gold.
    * Labels say "Ball watching: player #X (away)" rather than "chem hub."
    * Slowed to 4 fps for readability.
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

import lightning.pytorch as pl
from kloppy import metrica

from wc2026_tracking_transformer.data import SoccerTrackingDataModule
from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.metrica import (
    load_metrica_events,
    load_metrica_match,
)
from wc2026_tracking_transformer.data.schema import PITCH_LENGTH_M, PITCH_WIDTH_M
from wc2026_tracking_transformer.model import NextEventValueLitModule

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUT_DIR.mkdir(exist_ok=True)
BUILDUP_PATH = OUT_DIR / "attention_buildup.gif"
GOAL_PATH = OUT_DIR / "attention_goal.gif"

# Visual palette
HOME_COLOR = "#5eead4"
AWAY_COLOR = "#f87171"
BALL_COLOR = "#ffd166"
GK_RING   = "#00d68f"
POSS_RING = "white"
ATTN_GOLD = "#fde047"
HALO_COLOR = "#ffd166"

HALF_L, HALF_W = PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2


def to_meters(token_arr_norm: np.ndarray) -> np.ndarray:
    xy = token_arr_norm[:, :2].copy()
    xy[:, 0] *= HALF_L
    xy[:, 1] *= HALF_W
    return xy


def draw_pitch(ax: plt.Axes) -> None:
    ax.set_facecolor("#1a8847")
    ax.set_xlim(-HALF_L - 3, HALF_L + 3)
    ax.set_ylim(-HALF_W - 3, HALF_W + 3)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_color("#0b1220")
    ax.add_patch(mpatches.Rectangle((-HALF_L, -HALF_W), PITCH_LENGTH_M, PITCH_WIDTH_M,
                                     fill=False, edgecolor="white", lw=1.2))
    ax.plot([0, 0], [-HALF_W, HALF_W], color="white", lw=1)
    ax.add_patch(mpatches.Circle((0, 0), 9.15, fill=False, edgecolor="white", lw=1))
    ax.plot(0, 0, "o", color="white", ms=3)
    for side in (-1, 1):
        pa_x = side * (HALF_L - 16.5) if side > 0 else -HALF_L
        ax.add_patch(mpatches.Rectangle((pa_x, -20.16), 16.5, 40.32,
                                         fill=False, edgecolor="white", lw=1))
        sy_x = side * (HALF_L - 5.5) if side > 0 else -HALF_L
        ax.add_patch(mpatches.Rectangle((sy_x, -9.16), 5.5, 18.32,
                                         fill=False, edgecolor="white", lw=1))
    # Goal lines highlighted
    for side in (-1, 1):
        gx = side * HALF_L
        ax.plot([gx, gx], [-3.66, 3.66], color="#ffd166", lw=2.5, zorder=3)


def render_clip(
    *,
    out_path: Path,
    clip_tensors: torch.Tensor,
    clip_chem: np.ndarray,
    clip_p_shot: np.ndarray,
    clip_p_goal: np.ndarray,
    clip_jerseys: list,
    clip_teams: list,
    top_banner: str,
    fps: int = 4,
) -> None:
    """Render one animated GIF. Function-scoped state — call repeatedly."""
    W = clip_tensors.shape[0]
    # Taller figure with explicit space for: banner row · legend row · pitch ·
    # status row · probability chart. Each row gets its own clear zone so they
    # never overlap.
    fig = plt.figure(figsize=(12, 10), facecolor="#0b1220", constrained_layout=False)
    gs = fig.add_gridspec(
        2, 1, height_ratios=[2.0, 1.0],
        left=0.06, right=0.97, top=0.86, bottom=0.08, hspace=0.40,
    )
    ax_pitch = fig.add_subplot(gs[0])
    ax_line  = fig.add_subplot(gs[1])
    draw_pitch(ax_pitch)

    f0_norm = clip_tensors[0].numpy()
    xy0 = to_meters(f0_norm)
    team_at_0 = clip_teams[0]
    player_colors = [HOME_COLOR if t == "home" else AWAY_COLOR for t in team_at_0]

    # Halos: smaller + softer so they read as accents, not as covering layers.
    halo_outer = ax_pitch.scatter([], [], s=1300, color=HALO_COLOR, alpha=0.10, zorder=1, edgecolor="none")
    halo_mid   = ax_pitch.scatter([], [], s=750,  color=HALO_COLOR, alpha=0.22, zorder=1.5, edgecolor="none")
    halo_inner = ax_pitch.scatter([], [], s=430,  color=HALO_COLOR, alpha=0.40, zorder=2, edgecolor="none")

    players_scatter = ax_pitch.scatter(
        xy0[:22, 0], xy0[:22, 1],
        c=player_colors, s=240, edgecolor="white", lw=1.2, zorder=5,
    )

    gk_mask = clip_tensors[0, :22, 5].numpy() > 0.5
    gk_ring = ax_pitch.scatter(
        xy0[:22][gk_mask, 0], xy0[:22][gk_mask, 1],
        s=400, facecolors="none", edgecolor=GK_RING, lw=2.0, zorder=4,
    )
    poss_idx0 = int(np.argmax(clip_tensors[0, :22, 6].numpy()))
    poss_ring = ax_pitch.scatter(
        [xy0[poss_idx0, 0]], [xy0[poss_idx0, 1]],
        s=470, facecolors="none", edgecolor=POSS_RING, lw=1.8, zorder=6,
    )
    ball_scatter = ax_pitch.scatter(
        xy0[22, 0], xy0[22, 1],
        c=BALL_COLOR, s=160, edgecolor="black", lw=1.5, zorder=11,
    )
    # Smaller arrowheads, just enough to read direction
    arrow_q = ax_pitch.quiver(
        xy0[:22, 0], xy0[:22, 1],
        np.zeros(22), np.zeros(22),
        color="white", scale=30, width=0.0045, headwidth=4, headlength=5,
        zorder=7,
    )

    K_EDGES = 5
    edge_lines = []
    for _ in range(K_EDGES):
        (line,) = ax_pitch.plot([0, 0], [0, 0], color=ATTN_GOLD,
                                alpha=0.0, lw=2.4, zorder=3, solid_capstyle="round")
        edge_lines.append(line)

    # Jersey numbers — smaller and tucked closer to the dot
    jersey_texts = [
        ax_pitch.text(xy0[i, 0], xy0[i, 1] + 1.4,
                      str(clip_jerseys[0][i] if i < len(clip_jerseys[0]) else ""),
                      ha="center", va="bottom", color="white",
                      fontsize=6.5, fontweight="bold", zorder=12)
        for i in range(22)
    ]
    ball_text = ax_pitch.text(xy0[22, 0], xy0[22, 1] + 1.4, "•",
                              ha="center", va="bottom", color="black",
                              fontsize=6.5, fontweight="bold", zorder=12)

    # Banner row at the very top
    fig.text(0.5, 0.975, top_banner, ha="center", va="top",
             color="#e9f0ff", fontsize=14, fontweight="bold")
    # Legend row underneath the banner — its own clear horizontal line
    legend_y = 0.935
    legend_items = [
        (0.080, "●", HOME_COLOR, " Home"),
        (0.160, "●", AWAY_COLOR, " Away"),
        (0.235, "●", BALL_COLOR, " Ball"),
        (0.305, "◯", GK_RING, " GK"),
        (0.380, "◯", POSS_RING, " on ball"),
        (0.480, "▶", "white", " motion"),
        (0.595, "✸", HALO_COLOR, " ball's top-attended (halos + edges)"),
    ]
    for x, sym, col, lbl in legend_items:
        fig.text(x, legend_y, sym, color=col, va="top", fontsize=13)
        fig.text(x + 0.013, legend_y, lbl, color="#94a3b8", va="top", fontsize=10)

    # Status row BELOW the pitch and ABOVE the chart — no longer overlapping the legend.
    # We update its text per-frame in update().
    status_text = fig.text(
        0.5, 0.395, "", ha="center", va="top",
        color="#e9f0ff", fontsize=11.5,
    )
    title = status_text  # keep variable name so the inner update() doesn't need refactoring

    # --- probability plot below ---
    ax_line.set_facecolor("#0b1220")
    for s in ax_line.spines.values(): s.set_color("#94a3b8")
    ax_line.tick_params(colors="#94a3b8")
    ax_line.set_xlim(0, W - 1)
    y_top = max(0.05, float(max(clip_p_shot.max(), clip_p_goal.max()))) * 1.18
    ax_line.set_ylim(0, y_top)
    seconds = W / 5.0
    ax_line.set_xlabel(f"Frame in clip (5 Hz → {seconds:.0f} seconds)", color="#94a3b8")
    ax_line.set_ylabel("Model probability", color="#94a3b8")
    ax_line.grid(True, color="#1f2c44", lw=0.6)
    ax_line.plot(np.arange(W), clip_p_shot, color="#fde047", lw=1.6, alpha=0.45, label="P(shot in next 15s)")
    ax_line.plot(np.arange(W), clip_p_goal, color="#f87171", lw=1.6, alpha=0.7,  label="P(goal in next 15s)")
    ax_line.legend(loc="upper left", framealpha=0.0, labelcolor="#e9f0ff", fontsize=9)
    (progress_dot_shot,) = ax_line.plot([0], [clip_p_shot[0]], color="#fde047", marker="o", ms=10, lw=0)
    (progress_dot_goal,) = ax_line.plot([0], [clip_p_goal[0]], color="#f87171", marker="o", ms=10, lw=0)

    def update(i: int):
        f = clip_tensors[i].numpy()
        xy = to_meters(f)
        players_scatter.set_offsets(xy[:22])
        cols = [HOME_COLOR if t == "home" else AWAY_COLOR for t in clip_teams[i]]
        players_scatter.set_facecolor(cols)
        ball_scatter.set_offsets(xy[22:23])
        if gk_mask.any():
            gk_ring.set_offsets(xy[:22][gk_mask])
        poss_i = int(np.argmax(f[:22, 6]))
        poss_ring.set_offsets(xy[poss_i:poss_i + 1])

        vels = f[:22, 2:4]
        speeds = np.linalg.norm(vels, axis=1, keepdims=True)
        unit = np.where(speeds > 0.1, vels / np.maximum(speeds, 1e-6), 0.0)
        arrow_q.set_offsets(xy[:22])
        arrow_q.set_UVC(unit[:, 0], unit[:, 1])

        ball_chem = clip_chem[i, 22].copy()
        ball_chem[22] = 0.0
        order = np.argsort(ball_chem)[::-1]
        top_edges = order[:K_EDGES]
        top_halos = order[:3]
        halo_xy = xy[top_halos]
        halo_outer.set_offsets(halo_xy)
        halo_mid.set_offsets(halo_xy)
        halo_inner.set_offsets(halo_xy)

        bx, by = xy[22]
        max_w = float(ball_chem.max()) if ball_chem.max() > 0 else 1.0
        for j, line in enumerate(edge_lines):
            if j < len(top_edges):
                ti = int(top_edges[j])
                line.set_data([bx, xy[ti, 0]], [by, xy[ti, 1]])
                line.set_alpha(min(1.0, 0.35 + 0.65 * (ball_chem[ti] / max_w)))
                line.set_linewidth(2.4 + 3.2 * (ball_chem[ti] / max_w))
            else:
                line.set_alpha(0.0)

        for j, t in enumerate(jersey_texts):
            t.set_position((xy[j, 0], xy[j, 1] + 1.4))
            jn = clip_jerseys[i][j] if j < len(clip_jerseys[i]) else None
            t.set_text(str(jn) if jn is not None else "")
        ball_text.set_position((xy[22, 0], xy[22, 1] + 1.4))

        progress_dot_shot.set_data([i], [clip_p_shot[i]])
        progress_dot_goal.set_data([i], [clip_p_goal[i]])

        top0 = int(top_edges[0])
        if top0 == 22:
            watching = "itself"
        elif top0 < 22:
            jn = clip_jerseys[i][top0]
            team = clip_teams[i][top0]
            watching = f"player #{jn} ({team})"
        else:
            watching = "?"
        title.set_text(
            f"Frame {i+1}/{W}    "
            f"P(shot)={clip_p_shot[i]:.2f}    P(goal)={clip_p_goal[i]:.2f}    "
            f"Ball watching: {watching} (attn={ball_chem[top0]:.2f})"
        )
        return (players_scatter, ball_scatter, gk_ring, poss_ring, arrow_q,
                halo_outer, halo_mid, halo_inner, *edge_lines, *jersey_texts,
                ball_text, progress_dot_shot, progress_dot_goal, title)

    interval_ms = int(round(1000 / fps))
    anim = FuncAnimation(fig, update, frames=W, interval=interval_ms, blit=False)
    writer = PillowWriter(fps=fps)
    anim.save(out_path, writer=writer, dpi=92, savefig_kwargs={"facecolor": "#0b1220"})
    plt.close(fig)
    print(f"      wrote {out_path}  ({out_path.stat().st_size / 1024:.0f} KB)")


# ---------------------------------------------------------------------------
# 1) Train
# ---------------------------------------------------------------------------
print("[1/5] Training on Metrica match 1 with real shot+goal labels …")
torch.manual_seed(0)
dm = SoccerTrackingDataModule(
    source="metrica",
    batch_size=128,
    metrica_sampling_stride=5,
    metrica_k_seconds=15.0,
    metrica_label_mode="events",
)
lit = NextEventValueLitModule(
    feature_len=7, model_dim=64, num_heads=4, num_layers=2,
    learning_rate=5e-4,
)
trainer = pl.Trainer(
    accelerator="cpu", devices=1, max_epochs=8,
    enable_progress_bar=False, logger=False, enable_checkpointing=False,
    log_every_n_steps=50,
)
trainer.fit(lit, datamodule=dm)
lit.eval()

import json
metrics = {
    k: float(v.item()) if hasattr(v, "item") else float(v)
    for k, v in trainer.callback_metrics.items()
}
# Also compute val accuracy split per-head, on the full val set, for the deck.
val_loader = dm.val_dataloader()
with torch.no_grad():
    all_p, all_y = [], []
    for x, y in val_loader:
        all_p.append(torch.sigmoid(lit(x)))
        all_y.append(y)
    P = torch.cat(all_p).numpy()
    Y = torch.cat(all_y).numpy()
metrics["val_acc_shot_head"] = float(((P[:, 0] > 0.5) == (Y[:, 0] > 0.5)).mean())
metrics["val_acc_goal_head"] = float(((P[:, 1] > 0.5) == (Y[:, 1] > 0.5)).mean())
# Marginal baselines for context
metrics["val_pos_rate_shot"] = float(Y[:, 0].mean())
metrics["val_pos_rate_goal"] = float(Y[:, 1].mean())
# Pseudo-AUC: average rank of positives — quick discrimination check
def quick_auc(scores, labels):
    n = len(labels); pos = labels > 0.5
    if pos.sum() == 0 or pos.sum() == n: return float("nan")
    ranks = scores.argsort().argsort() + 1
    return float((ranks[pos].mean() - (pos.sum() + 1) / 2) / (n - pos.sum()))
metrics["val_auc_shot_head"] = quick_auc(P[:, 0], Y[:, 0])
metrics["val_auc_goal_head"] = quick_auc(P[:, 1], Y[:, 1])

OUT_DIR.mkdir(exist_ok=True)
with (OUT_DIR / "training_metrics.json").open("w") as fp:
    json.dump(metrics, fp, indent=2)
print(f"      done.  val_loss={metrics.get('val_loss', 'n/a'):.3f}  "
      f"val_acc_shot={metrics['val_acc_shot_head']:.3f}  "
      f"val_auc_shot={metrics['val_auc_shot_head']:.3f}  "
      f"val_auc_goal={metrics['val_auc_goal_head']:.3f}")

# ---------------------------------------------------------------------------
# 2) Score match 2 frames
# ---------------------------------------------------------------------------
print("[2/5] Scoring all match-2 frames …")
match2_frames = list(load_metrica_match("2", sampling_stride=5))
m2_tensors = batch_frames(match2_frames)
m2_torch = torch.from_numpy(m2_tensors)
with torch.no_grad():
    encoded, attn = lit.backbone.encode_with_attention(m2_torch)
    logits = lit.head(encoded)
    probs = torch.sigmoid(logits).numpy()
p_shot, p_goal = probs[:, 0], probs[:, 1]

# Build a frame_id → sampled-index map for goal anchoring
sampled_native_frames = np.array([tf.frame_id for tf in match2_frames], dtype=np.int64)

# ---------------------------------------------------------------------------
# 3) Load jersey/team metadata for the whole match (single kloppy load)
# ---------------------------------------------------------------------------
print("[3/5] Indexing player metadata …")
raw_m2 = metrica.load_open_data(match_id="2")
# Build a map native_frame_id -> ([jerseys], [team_ids]) for fast lookup
frame_meta: dict[int, tuple[list, list]] = {}
for rf in raw_m2.frames:
    items = list(rf.players_data.items())
    frame_meta[int(rf.frame_id)] = (
        [p.jersey_no for p, _ in items],
        [p.team.team_id for p, _ in items],
    )


def gather_window(start: int, end: int):
    """Slice tensors + attention + per-frame metadata for a [start, end) window."""
    ct = m2_torch[start:end]
    cattn = attn[start:end]
    cchem = cattn.mean(dim=(1, 2)).numpy()
    cps = p_shot[start:end]
    cpg = p_goal[start:end]
    cj, ct_ = [], []
    for tf in match2_frames[start:end]:
        j, t = frame_meta[tf.frame_id]
        cj.append(j); ct_.append(t)
    return ct, cchem, cps, cpg, cj, ct_


# ---------------------------------------------------------------------------
# 4) Buildup clip: model's pick
# ---------------------------------------------------------------------------
print("[4/5] Picking the peak-probability 12s window …")
W_BUILD = 60  # 12 s at 5 Hz
score_seq = p_shot + 2.0 * p_goal
# End the clip at the global peak of the score; clip is the W frames ending there.
peak_idx = int(np.argmax(score_seq))
best_start = max(0, peak_idx - W_BUILD + 1)
b_end = best_start + W_BUILD
print(f"      buildup window: frames {best_start}-{b_end}  peak at idx {peak_idx}  "
      f"P(shot) {p_shot[best_start]:.2f}→{p_shot[b_end-1]:.2f}, "
      f"P(goal) {p_goal[best_start]:.2f}→{p_goal[b_end-1]:.2f}, "
      f"peak P(shot)={p_shot[peak_idx]:.2f}")
ct, cchem, cps, cpg, cj, ct_ = gather_window(best_start, b_end)
render_clip(
    out_path=BUILDUP_PATH,
    clip_tensors=ct, clip_chem=cchem,
    clip_p_shot=cps, clip_p_goal=cpg,
    clip_jerseys=cj, clip_teams=ct_,
    top_banner="Metrica match 2  ·  12s buildup the model rated highest",
    fps=6,
)

# ---------------------------------------------------------------------------
# 5) Goal-anchored clip
# ---------------------------------------------------------------------------
print("[5/5] Picking a real goal and rendering the 15s before it …")
events = load_metrica_events("2")
goal_rows = events[
    (events["Type"] == "SHOT")
    & events["Subtype"].astype(str).str.contains("GOAL", na=False)
]
print(f"      {len(goal_rows)} goals available in match 2.")
# Pick the goal whose pre-goal window is best contained in the dataset.
# Each goal's native Start Frame → find nearest sampled index.
W_GOAL = 75  # 15 s at 5 Hz
chosen_start = None
for _, g in goal_rows.iterrows():
    native_goal_f = int(g["Start Frame"])
    # Sampled idx whose native frame is closest to and just before the goal
    diffs = sampled_native_frames - native_goal_f
    # We want the largest sampled idx with diff <= 0 (i.e., at or before goal)
    pre_mask = diffs <= 0
    if not pre_mask.any():
        continue
    end_idx = int(np.where(pre_mask)[0].max())
    s = end_idx - W_GOAL
    if s >= 0:
        chosen_start = s
        chosen_end = end_idx
        chosen_goal = g
        break

if chosen_start is not None:
    print(f"      goal @ native frame {int(chosen_goal['Start Frame'])} "
          f"team={chosen_goal['Team']} subtype={chosen_goal['Subtype']}  "
          f"→ window {chosen_start}-{chosen_end}")
    ct, cchem, cps, cpg, cj, ct_ = gather_window(chosen_start, chosen_end)
    banner = (f"Metrica match 2  ·  15s before a real goal "
              f"({chosen_goal['Team']} · {chosen_goal['Subtype']})")
    render_clip(
        out_path=GOAL_PATH,
        clip_tensors=ct, clip_chem=cchem,
        clip_p_shot=cps, clip_p_goal=cpg,
        clip_jerseys=cj, clip_teams=ct_,
        top_banner=banner,
        fps=6,
    )
else:
    print("      no goal had a fully-contained 15s pre-window.")
