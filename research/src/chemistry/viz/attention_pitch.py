"""Render attention-chemistry network plots per team.

Similar to pitch_chemistry.py but uses transformer ball-attention totals
between pairs instead of VAEP-driven JOI / JDI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from .pitch_chemistry import (_draw_pitch, _fetch_flag_image, _last_name,
                               _player_xy_from_cell, _resolve_team_name,
                               _resolve_unique_cells, PITCH_LENGTH, PITCH_WIDTH)
from ..joint.grid import grid_role
from ..teams_meta import flag_code as _flag_code

CMAP_ATTN = LinearSegmentedColormap.from_list(
    "attn_seq", ["#1a3f6a", "#56a0d3", "#ffd76b", "#f25b3c"], N=256
)

# Three semantic edge colors, used both in the matplotlib team plots and as a
# parallel signal on the site's leaderboard chips. Restrained palette so they
# read clearly on the dark-on-light pitch and on the dark site theme alike.
EDGE_COLORS = {
    "off": "#d4793a",   # Offence ↔ offence: warm rust, "creative" colour
    "def": "#3b6ea0",   # Defence ↔ defence: cool steel blue
    "cross": "#7a4f9a", # Cross-role linking attack to defence: violet
}

OFFENSIVE_ROLES = {"FWD", "MID"}
DEFENSIVE_ROLES = {"DEF", "GK"}


def pair_category(pos_a: str | None, pos_b: str | None) -> str:
    """Classify a pair into off/def/cross by their grid roles."""
    a = grid_role(pos_a)
    b = grid_role(pos_b)
    if a in OFFENSIVE_ROLES and b in OFFENSIVE_ROLES:
        return "off"
    if a in DEFENSIVE_ROLES and b in DEFENSIVE_ROLES:
        return "def"
    return "cross"


def draw_team_attention(
    team_id: str,
    attention_pairs: pd.DataFrame,
    *,
    lineups: pd.DataFrame,
    out_path: Path,
    matches: pd.DataFrame | None = None,
    accent_color: str = "#bb8a2a",
    top_k: int = 20,
) -> dict[str, Any]:
    """Render a pitch with attention-chemistry edges between starters."""
    team_name = (_resolve_team_name(team_id, matches) if matches is not None
                  else f"Team {team_id}")

    # Top starters by total on-pitch minutes, mirroring the JOI/JDI viz.
    sub = lineups[lineups.team_id == team_id]
    starters = (
        sub.groupby(["player_id", "player_name"], as_index=False)
        .agg(on_seconds=("on_seconds", "sum"))
        .sort_values("on_seconds", ascending=False)
        .head(11)
        .reset_index(drop=True)
    )

    def modal_pos(pid: int) -> str:
        rows = sub[sub.player_id == pid]
        if rows.empty:
            return "DM"
        c = rows["position"].value_counts()
        return str(c.index[0]) if len(c) else "DM"

    starters["position"] = starters.player_id.apply(modal_pos)
    cells = _resolve_unique_cells(starters)
    players: list[dict[str, Any]] = []
    for (gr, gc), (_, r) in zip(cells, starters.iterrows()):
        x, y = _player_xy_from_cell(gr, gc)
        players.append({
            "player_id": int(r["player_id"]),
            "name": str(r["player_name"]),
            "position": str(r["position"]),
            "x": x, "y": y, "row": gr, "col": gc,
        })
    pid_to_player = {p["player_id"]: p for p in players}
    pids = set(pid_to_player.keys())

    # Filter the attention DataFrame to this team + these players
    ap = attention_pairs[attention_pairs.team_id == team_id]
    ap = ap[ap.player_p.isin(pids) & ap.player_q.isin(pids)].copy()
    ap = ap.sort_values("attention_per90", ascending=False).head(top_k)

    fig, ax = plt.subplots(figsize=(7.5, 11.2), dpi=160)
    _draw_pitch(ax)
    flag = _fetch_flag_image(_flag_code(team_name)) if team_name else None
    if flag is not None:
        ax.imshow(flag, extent=(0, PITCH_WIDTH, 0, PITCH_LENGTH),
                  aspect="auto", alpha=0.32, zorder=0.5, interpolation="bilinear")

    if not ap.empty:
        max_v = float(ap.attention_per90.max())
        min_v = float(ap.attention_per90.min())
        rng = max(max_v - min_v, 1e-9)
        for _, row in ap.iterrows():
            p = pid_to_player[int(row.player_p)]
            q = pid_to_player[int(row.player_q)]
            t = (float(row.attention_per90) - min_v) / rng
            # Edge colour by pair category (off/def/cross), opacity by strength.
            cat = pair_category(p["position"], q["position"])
            base = EDGE_COLORS[cat]
            lw = 1.4 + 4.0 * t
            ax.plot([p["x"], q["x"]], [p["y"], q["y"]],
                    color=base, linewidth=lw, alpha=0.55 + 0.40 * t,
                    solid_capstyle="round", antialiased=True, zorder=2)

    for p in players:
        ax.add_patch(mpatches.Circle((p["x"], p["y"]), 2.4,
                                     facecolor=accent_color, edgecolor="white",
                                     linewidth=1.4, zorder=3))
        ly = p["y"] + 4.2 if p["row"] <= 2 else p["y"] - 4.2
        va = "bottom" if p["row"] <= 2 else "top"
        ax.text(p["x"], ly, f"{_last_name(p['name'])}\n{p['position']}",
                ha="center", va=va, fontsize=8.0, color="#101010",
                bbox=dict(facecolor="white", edgecolor="none",
                          boxstyle="round,pad=0.25", alpha=0.92),
                zorder=4, linespacing=1.0)

    ax.set_title(f"{team_name} — Attention Chemistry (Transformer)",
                 fontsize=14, color="#111", pad=10, fontweight="bold")

    # Edge-colour legend, lower-left corner of the pitch.
    legend_handles = [
        mpatches.Patch(color=EDGE_COLORS["off"],   label="Off ↔ Off"),
        mpatches.Patch(color=EDGE_COLORS["def"],   label="Def ↔ Def"),
        mpatches.Patch(color=EDGE_COLORS["cross"], label="Cross (Off ↔ Def)"),
    ]
    ax.legend(handles=legend_handles, loc="lower left", frameon=True,
              facecolor="white", edgecolor="none", framealpha=0.92,
              fontsize=8.5, title="Edge type", title_fontsize=8.5)

    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {
        "team_id": team_id,
        "team_name": team_name,
        "path": str(out_path),
        "n_pairs": int(len(ap)),
    }


def render_all_teams_attention(
    attention_pairs: pd.DataFrame,
    lineups: pd.DataFrame,
    matches: pd.DataFrame,
    *,
    out_dir: Path,
    min_pairs: int = 5,
) -> list[dict[str, Any]]:
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    counts = attention_pairs.groupby("team_id").size()
    eligible = [str(t) for t, n in counts.items() if n >= min_pairs]
    for team_id in sorted(eligible):
        op = out_dir / f"team_{team_id}_attention.png"
        try:
            meta = draw_team_attention(
                team_id, attention_pairs, lineups=lineups, out_path=op, matches=matches
            )
            results.append(meta)
        except Exception as e:
            print(f"  skip {team_id}: {e}")
    return results
