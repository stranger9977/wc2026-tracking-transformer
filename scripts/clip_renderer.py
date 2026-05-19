"""Shared rendering for the attention GIFs.

``render_clip`` builds a single animated GIF from a precomputed clip
(tensors, chemistry, probabilities, jersey/team metadata). Used by:

  * ``visualize_attention_gif.py`` — Metrica-events-trained model.
  * ``visualize_attention_combined.py`` — combined Metrica+SkillCorner model.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import torch
from matplotlib.animation import FuncAnimation, PillowWriter

from wc2026_tracking_transformer.baselines.xt import XT_GRID
from wc2026_tracking_transformer.data.schema import PITCH_LENGTH_M, PITCH_WIDTH_M

HOME_COLOR = "#5eead4"
AWAY_COLOR = "#f87171"
BALL_COLOR = "#ffd166"
GK_RING   = "#00d68f"
POSS_RING = "white"
# Same-team attention (ball attending to a teammate of the ball-owner):
ATTN_SAME = "#fde047"   # yellow / gold
# Cross-team attention (ball attending to an opponent):
ATTN_CROSS = "#fb923c"  # warm orange
HALO_COLOR = "#ffd166"

HALF_L, HALF_W = PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2


def to_meters(token_arr_norm: np.ndarray) -> np.ndarray:
    xy = token_arr_norm[:, :2].copy()
    xy[:, 0] *= HALF_L
    xy[:, 1] *= HALF_W
    return xy


def draw_pitch(ax: plt.Axes, *, show_xt_heatmap: bool = True) -> None:
    ax.set_facecolor("#1a8847")
    ax.set_xlim(-HALF_L - 3, HALF_L + 3)
    ax.set_ylim(-HALF_W - 3, HALF_W + 3)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_color("#0b1220")

    # Static xT heatmap, SYMMETRIZED across the halfway line. Karun's grid
    # is one-directional (def→att) but a soccer pitch has TWO dangerous zones
    # (one in front of each goal). Mirror + max so both ends glow — that's
    # what readers expect to see when looking at a "threat map."
    if show_xt_heatmap:
        grid_t = XT_GRID.T                          # (8 y, 12 x)
        sym = np.maximum(grid_t, np.flip(grid_t, axis=1))
        ax.imshow(
            sym,
            extent=(-HALF_L, HALF_L, -HALF_W, HALF_W),
            origin="lower",
            cmap="YlOrRd",
            alpha=0.50,
            aspect="auto",
            zorder=0,
            interpolation="bilinear",   # smooth the 12×8 cells into a gradient
        )

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
    goal_frame_in_clip: int | None = None,
    head0_label: str = "P(shot in next 15s)",
    head1_label: str = "P(goal in next 15s)",
    team_color_map: dict[str, str] | None = None,
    team_label_map: dict[str, str] | None = None,
) -> None:
    """Render one animated GIF."""
    W = clip_tensors.shape[0]
    fig = plt.figure(figsize=(12, 9), facecolor="#0b1220", constrained_layout=False)
    gs = fig.add_gridspec(
        2, 1, height_ratios=[1.5, 1.0],
        left=0.06, right=0.97, top=0.88, bottom=0.10, hspace=0.30,
    )
    ax_pitch = fig.add_subplot(gs[0])
    ax_line  = fig.add_subplot(gs[1])
    draw_pitch(ax_pitch)

    f0_norm = clip_tensors[0].numpy()
    xy0 = to_meters(f0_norm)
    team_at_0 = clip_teams[0]
    # Use the optional team_color_map for source-specific palettes (e.g. WC nations).
    # Falls back to home/away teal/coral.
    def _team_to_color(t: str) -> str:
        if team_color_map and t in team_color_map:
            return team_color_map[t]
        return HOME_COLOR if t == "home" else AWAY_COLOR
    player_colors = [_team_to_color(t) for t in team_at_0]

    halo_outer = ax_pitch.scatter([], [], s=1300, color=HALO_COLOR, alpha=0.10, zorder=1, edgecolor="none")
    halo_mid   = ax_pitch.scatter([], [], s=750,  color=HALO_COLOR, alpha=0.22, zorder=1.5, edgecolor="none")
    halo_inner = ax_pitch.scatter([], [], s=430,  color=HALO_COLOR, alpha=0.40, zorder=2, edgecolor="none")

    # Smaller player dots so the pitch breathes and ball stays the focal point.
    players_scatter = ax_pitch.scatter(
        xy0[:22, 0], xy0[:22, 1],
        c=player_colors, s=140, edgecolor="white", lw=1.0, zorder=5,
        alpha=0.6,
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
    arrow_q = ax_pitch.quiver(
        xy0[:22, 0], xy0[:22, 1],
        np.zeros(22), np.zeros(22),
        color="white", scale=30, width=0.0045, headwidth=4, headlength=5,
        zorder=7,
    )

    K_EDGES = 5
    edge_lines = []
    for _ in range(K_EDGES):
        # Edge color is reassigned per-frame in update() based on attended-player team.
        (line,) = ax_pitch.plot([0, 0], [0, 0], color=ATTN_SAME,
                                alpha=0.0, lw=2.4, zorder=3, solid_capstyle="round")
        edge_lines.append(line)

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

    fig.text(0.5, 0.975, top_banner, ha="center", va="top",
             color="#e9f0ff", fontsize=13, fontweight="bold")
    legend_y = 0.942
    # Default Home/Away labels; if a team_label_map is supplied (e.g. PFF
    # source with WC nation names), use those.
    if team_label_map and len(team_label_map) >= 2:
        teams_in_label_order = list(team_label_map.items())[:2]
        (tid_a, name_a), (tid_b, name_b) = teams_in_label_order
        col_a = team_color_map.get(tid_a, HOME_COLOR) if team_color_map else HOME_COLOR
        col_b = team_color_map.get(tid_b, AWAY_COLOR) if team_color_map else AWAY_COLOR
        legend_items = [
            (0.040, "●", col_a, f" {name_a}"),
            (0.180, "●", col_b, f" {name_b}"),
            (0.320, "●", BALL_COLOR, " Ball"),
            (0.380, "◯", GK_RING, " GK"),
            (0.440, "◯", POSS_RING, " on ball"),
            (0.520, "▬", ATTN_SAME, " same-team attn"),
            (0.640, "▬", ATTN_CROSS, " cross-team attn"),
            (0.770, "✸", HALO_COLOR, " halos = top-attended"),
        ]
    else:
        legend_items = [
            (0.050, "●", HOME_COLOR, " Home"),
            (0.120, "●", AWAY_COLOR, " Away"),
            (0.185, "●", BALL_COLOR, " Ball"),
            (0.240, "◯", GK_RING, " GK"),
            (0.300, "◯", POSS_RING, " on ball"),
            (0.380, "▬", ATTN_SAME, " same-team attention"),
            (0.520, "▬", ATTN_CROSS, " cross-team attention"),
            (0.680, "✸", HALO_COLOR, " halos = top-attended"),
        ]
    for x, sym, col, lbl in legend_items:
        fig.text(x, legend_y, sym, color=col, va="top", fontsize=12)
        fig.text(x + 0.012, legend_y, lbl, color="#94a3b8", va="top", fontsize=9.5)

    status_text = fig.text(
        0.5, 0.495, "", ha="center", va="top",
        color="#e9f0ff", fontsize=11,
    )
    title = status_text

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
    ax_line.plot(np.arange(W), clip_p_shot, color="#fde047", lw=1.8, alpha=0.55, label=head0_label)
    ax_line.plot(np.arange(W), clip_p_goal, color="#f87171", lw=1.8, alpha=0.75, label=head1_label)
    if goal_frame_in_clip is not None and 0 <= goal_frame_in_clip < W:
        ax_line.axvline(goal_frame_in_clip, color="#00d68f", lw=2, alpha=0.75, label="actual goal")
    ax_line.legend(loc="upper left", framealpha=0.0, labelcolor="#e9f0ff", fontsize=9)
    (progress_dot_shot,) = ax_line.plot([0], [clip_p_shot[0]], color="#fde047", marker="o", ms=10, lw=0)
    (progress_dot_goal,) = ax_line.plot([0], [clip_p_goal[0]], color="#f87171", marker="o", ms=10, lw=0)

    def update(i: int):
        f = clip_tensors[i].numpy()
        xy = to_meters(f)
        # Per-player attention RECEIVED from the ball — used for alpha dimming.
        ball_chem = clip_chem[i, 22].copy()
        ball_chem[22] = 0.0
        max_w = float(ball_chem.max()) if ball_chem.max() > 0 else 1.0
        # Player alpha: scale 0.30 → 1.0 based on attention received.
        player_alphas = 0.30 + 0.70 * (ball_chem[:22] / max_w)
        # Players the ball isn't really looking at fade out.
        cols = [_team_to_color(t) for t in clip_teams[i]]
        # RGBA tuple per player, alpha-modulated.
        from matplotlib.colors import to_rgba
        rgba = np.array([to_rgba(c, alpha=float(a)) for c, a in zip(cols, player_alphas)])
        players_scatter.set_offsets(xy[:22])
        players_scatter.set_facecolor(rgba)

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

        order = np.argsort(ball_chem)[::-1]
        top_edges = order[:K_EDGES]
        top_halos = order[:3]
        halo_xy = xy[top_halos]
        halo_outer.set_offsets(halo_xy)
        halo_mid.set_offsets(halo_xy)
        halo_inner.set_offsets(halo_xy)

        bx, by = xy[22]
        # is_attacking_side feature column = 4 in the schema.
        # +1 = same team as the in-possession side → same-team attention.
        # -1 = opposing team → cross-team attention.
        for j, line in enumerate(edge_lines):
            if j < len(top_edges):
                ti = int(top_edges[j])
                line.set_data([bx, xy[ti, 0]], [by, xy[ti, 1]])
                line.set_alpha(min(1.0, 0.35 + 0.65 * (ball_chem[ti] / max_w)))
                line.set_linewidth(2.4 + 3.2 * (ball_chem[ti] / max_w))
                # Same-team vs cross-team edge color
                is_atk = f[ti, 4] if ti < 22 else 0.0
                line.set_color(ATTN_SAME if is_atk >= 0 else ATTN_CROSS)
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
            f"P0={clip_p_shot[i]:.2f}    P1={clip_p_goal[i]:.2f}    "
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
