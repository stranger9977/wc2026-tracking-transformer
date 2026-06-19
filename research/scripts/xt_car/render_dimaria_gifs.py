#!/usr/bin/env python3
"""Render two GIFs of Di María's goal in the 2022 final (ARG v FRA, 35th minute),
from OUR pitch-control x xT surface, for the off-ball + passing applications.

  dimaria-buildup.gif — the full build-up: the move that ends with Di María's run
      into the danger pocket. Di María is ringed; the surface is control x xT, so
      the bright pocket is the dangerous space he finds.
  dimaria-finish.gif   — tight on the final pass into that space and the finish.

Server-side render mirrors the site's canvas look (rampHot heatmap on a flat dark
base, pitch lines, team-coloured dots, Di María ringed + named), then ffmpeg
assembles the GIF. Same play scrubbed in Application 1; this shows the full move.

Run from the MAIN loop:
  PFF_ROOT=$HOME/pff_wc22_local PYTHONPATH=src \
    uv run python research/scripts/xt_car/render_dimaria_gifs.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

_REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_REPO / "research" / "scripts"), str(_REPO / "src"),
                str(Path(__file__).resolve().parent)]
import space_io        # noqa: E402
import pitch_control as pc  # noqa: E402
import clip_examples as ce  # noqa: E402

HALF_LEN, HALF_WID = pc.HALF_LEN, pc.HALF_WID
OUT_DIR = _REPO / "research" / "site" / "data" / "gifs"
MID, PERIOD, GC = "10517", 1, 2121.0     # ARG v FRA final, Di María's goal
HERO = "Ángel Di María"

# rampHot stops copied from space.js (dark navy -> teal -> green -> yellow -> hot)
_STOPS = [(14, 16, 20), (26, 52, 92), (33, 122, 140), (60, 184, 120),
          (190, 220, 70), (255, 196, 60), (255, 107, 107)]
RAMP = LinearSegmentedColormap.from_list(
    "hot", [(i / (len(_STOPS) - 1), tuple(c / 255 for c in s)) for i, s in enumerate(_STOPS)])
EDGE = (0.74, 0.82, 0.9, 0.22)


def surf_rgba(surface, gamma=0.55, thr=0.02):
    s = np.array(surface, dtype=float)
    t = np.clip(s, 0.0, 1.0) ** gamma
    rgba = RAMP(t)
    rgba[..., 3] = np.where(s <= thr, 0.0, np.clip(t, 0.0, 1.0))   # linear alpha (matches the page)
    return rgba


def draw_pitch(ax):
    ax.add_patch(plt.Rectangle((-52.5, -34), 105, 68, fill=False, ec=EDGE, lw=1.2))
    ax.plot([0, 0], [-34, 34], color=EDGE, lw=1)
    ax.add_patch(plt.Circle((0, 0), 9.15, fill=False, ec=EDGE, lw=1))
    for sx in (-52.5, 36.0):                       # 18-yard boxes (16.5 x 40.3)
        ax.add_patch(plt.Rectangle((sx, -20.15), 16.5, 40.3, fill=False, ec=EDGE, lw=1))
    for sx in (-52.5, 47.0):                       # 6-yard boxes (5.5 x 18.32)
        ax.add_patch(plt.Rectangle((sx, -9.16), 5.5, 18.32, fill=False, ec=EDGE, lw=1))


def render_frame(fr, teams, path):
    fig, ax = plt.subplots(figsize=(8.4, 5.44), dpi=110)
    fig.patch.set_facecolor("#0e1014"); ax.set_facecolor("#101a14")
    ax.imshow(surf_rgba(fr["surface"]), extent=[-52.5, 52.5, -34, 34], origin="upper",
              interpolation="bilinear", zorder=1, aspect="auto")
    draw_pitch(ax)
    for p in fr["players"]:
        col = "#6dd58c" if p["gk"] else ("#7ec8ff" if p["att"] else "#ff9a9a")
        x, y = p["x"], p["y"]
        ax.scatter([x], [y], s=95, c=col, edgecolors="#0a0c10", linewidths=1.4, zorder=3)
        if p["name"] == HERO:
            ax.scatter([x], [y], s=260, facecolors="none", edgecolors="#fff", linewidths=2, zorder=4)
            ax.text(x, y + 2.8, "Di María", color="#fff", fontsize=9, ha="center", va="bottom",
                    zorder=5, bbox=dict(boxstyle="round,pad=0.2", fc=(0.04, 0.05, 0.06, 0.88), ec="none"))
    bx, by = fr["ball_xy"]
    ax.scatter([bx], [by], s=42, c="#fff", edgecolors="#000", linewidths=1.2, zorder=6)
    ax.text(-51, 0, f"◂ {teams['attack']}'s goal", color="#cdd6e2", fontsize=8, va="center", zorder=5)
    ax.text(51, 0, f"{teams['defend']}'s goal ▸", color="#cdd6e2", fontsize=8, va="center",
            ha="right", zorder=5)
    ax.text(0, 35.4, f"{teams['attack']} attacking →", color="#cdd6e2", fontsize=9, ha="center")
    ax.set_xlim(-52.5, 52.5); ax.set_ylim(-34, 34); ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(path, facecolor=fig.get_facecolor()); plt.close(fig)


def make_gif(pre, post, out_name, fps):
    meta = space_io.load_metadata(MID)
    lock = str(meta["homeTeam"]["id"])     # Argentina is the home team in 10517
    teams = ce._teams_block(meta, lock)
    payload = ce.export_window(MID, PERIOD, GC, lock, "danger",
                               {"name": HERO, "team": teams["attack"]},
                               teams=teams, pre=pre, post=post, stride=6, anchor_name=HERO)
    if not payload:
        print(f"[gif] no window for {out_name}", flush=True); return
    frames = payload["frames"]
    tmp = Path(tempfile.mkdtemp())
    for i, fr in enumerate(frames):
        render_frame(fr, teams, tmp / f"f{i:03d}.png")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / out_name
    subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(tmp / "f%03d.png"),
         "-vf", "scale=760:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse",
         str(out)], check=True, capture_output=True)
    kb = out.stat().st_size / 1024
    print(f"[gif] {out_name}: {len(frames)} frames, {kb:.0f} KB "
          f"(window {payload['start_s']:.1f}-{payload['end_s']:.1f}s)", flush=True)


def main():
    make_gif(pre=10.0, post=1.5, out_name="dimaria-buildup.gif", fps=10)
    make_gif(pre=3.0, post=1.6, out_name="dimaria-finish.gif", fps=8)
    print("EXIT_OK", flush=True)


if __name__ == "__main__":
    main()
