#!/usr/bin/env python3
"""Render a surface-clip JSON to a frame montage (and optional GIF) so we can SEE the clip
the way the page draws it — surface heatmap + players + ball + ball-xT + current-receiver ring
+ the pass arrow. Pure matplotlib (no PFF/tracking reads), reads only the exported JSON.

  uv run python research/scripts/xt_car/inspect_clip.py research/site/data/surfaces/pobso.json
Writes /tmp/clip_montage.png (a grid of frames) and, with --gif, /tmp/clip.gif.
"""
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HALF_LEN, HALF_WID = 52.5, 34.0


def receiver_at(passes, t):
    r = None
    for p in passes:
        if p["t_s"] <= t + 0.05:
            r = p["receiver"]
        else:
            break
    return r


def recent_pass(passes, t):
    p0 = None
    for p in passes:
        if p["t_s"] <= t + 0.05:
            p0 = p
        else:
            break
    if p0 and (t - p0["t_s"]) <= 2.8:
        return p0
    return None


def draw_frame(ax, d, fr, passes):
    surf = np.array(fr["surface"])              # (ny, nx), row0 drawn at TOP, col0 = -x (left)
    # JS: off-image row r/col c -> drawn at (c,r); m2px puts +y at TOP. So surface row 0 = top = +y.
    ax.imshow(surf, extent=[-HALF_LEN, HALF_LEN, -HALF_WID, HALF_WID], origin="upper",
              cmap="inferno", vmin=0, vmax=1, aspect="auto", alpha=0.92, zorder=1)
    # pitch outline
    ax.add_patch(plt.Rectangle((-HALF_LEN, -HALF_WID), 2 * HALF_LEN, 2 * HALF_WID,
                               fill=False, ec="#88909c", lw=0.8, zorder=2))
    ax.plot([0, 0], [-HALF_WID, HALF_WID], color="#88909c", lw=0.6, zorder=2)
    for gx in (-HALF_LEN, HALF_LEN):
        ax.add_patch(plt.Rectangle((gx - 0 if gx < 0 else gx - 16.5, -20.15), 16.5, 40.3,
                                   fill=False, ec="#5a626e", lw=0.6, zorder=2))
    t = fr["t_s"]
    recv = receiver_at(passes, t) if passes else None
    # pass arrow (most-recent within 2.8s)
    rp = recent_pass(passes, t) if passes else None
    if rp:
        ax.annotate("", xy=(rp["x1"], rp["y1"]), xytext=(rp["x0"], rp["y0"]),
                    arrowprops=dict(arrowstyle="-|>", color="#ffe08a", lw=1.6), zorder=5)
        mx, my = (rp["x0"] + rp["x1"]) / 2, (rp["y0"] + rp["y1"]) / 2
        ax.text(mx, my, f"{rp['xt_added']:+.2f}", color="#ffe08a", fontsize=6, ha="center",
                va="center", zorder=6, bbox=dict(boxstyle="round,pad=0.1", fc="#0a0c10", ec="none"))
    # players
    for p in fr["players"]:
        col = "#6dd58c" if p["gk"] else ("#7ec8ff" if p["att"] else "#ff9a9a")
        ax.scatter([p["x"]], [p["y"]], s=46, c=col, ec="#0a0c10", lw=0.7, zorder=4)
        if recv and p["name"] == recv:
            win = (p.get("ctrl", 0) or 0) >= 0.5
            ax.add_patch(plt.Circle((p["x"], p["y"]), 2.6, fill=False,
                                    ec="#5fd38a" if win else "#ff6b6b", lw=1.8, zorder=5))
            ax.text(p["x"], p["y"] - 4.5, f"{round((p.get('ctrl',0) or 0)*100)}%",
                    color="#5fd38a" if win else "#ff6b6b", fontsize=6, ha="center", zorder=6)
        if p["name"].split()[-1] in ("María", "Allister", "Messi", "Alvarez", "Álvarez", "Molina"):
            ax.text(p["x"], p["y"] + 2.2, p["name"].split()[-1], color="#e8edf4", fontsize=5,
                    ha="center", zorder=6)
    # ball + nearest-player distance (the "passed to no one" check)
    bx, by = fr["ball_xy"]
    nd = min(math.hypot(p["x"] - bx, p["y"] - by) for p in fr["players"])
    ax.scatter([bx], [by], s=30, c="#ffffff", ec="#000", lw=0.8, zorder=7)
    ax.text(bx + 2, by + 2, f"xT {fr.get('xt', 0):.2f}", color="#fff", fontsize=5, zorder=7)
    ax.set_title(f"t={t:.1f}s  ball→nearest {nd:.1f}m", color="#cdd6e2", fontsize=7)
    ax.set_xlim(-HALF_LEN, HALF_LEN); ax.set_ylim(-HALF_WID, HALF_WID)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("#0b160f")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "research/site/data/surfaces/pobso.json"
    d = json.load(open(path))
    frames = d["frames"]; passes = d.get("passes") or []
    n = len(frames)
    # 15 evenly-spaced frames
    idx = [round(k) for k in np.linspace(0, n - 1, 15)]
    fig, axes = plt.subplots(3, 5, figsize=(20, 9), facecolor="#0b0d11")
    for ax, i in zip(axes.flat, idx):
        draw_frame(ax, d, frames[i], passes)
    fig.suptitle(f"{Path(path).name} — {d.get('match','')} — {n} frames @ {d.get('hz')}Hz",
                 color="#e8edf4", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = "/tmp/clip_montage.png"
    fig.savefig(out, dpi=80, facecolor="#0b0d11"); print("wrote", out)


if __name__ == "__main__":
    main()
