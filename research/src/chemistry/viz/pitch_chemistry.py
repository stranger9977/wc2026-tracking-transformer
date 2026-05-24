"""Pitch chemistry visualization (Bransen 2020 style)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

import io
import urllib.request

from chemistry.joint.grid import grid_cell
from chemistry.teams_meta import flag_code as _flag_code

PITCH_LENGTH = 105.0  # vertical (y)
PITCH_WIDTH = 68.0    # horizontal (x)
# Tufte-style muted grey-green pitch with restrained line colour.
LINE_COLOR = "#9aa3aa"
PITCH_COLOR = "#dbe2dc"
# Sequential amber: lighter == weaker, darker == stronger. Single hue, no diverge.
CMAP = LinearSegmentedColormap.from_list(
    "chem_seq", ["#f3e9c6", "#e9b949", "#8a5a00"], N=256
)


def _grid_to_pitch(row: int, col: int) -> tuple[float, float]:
    """Map (row, col) on the 5x5+GK grid to (x, y) on a vertical pitch."""
    y_pitch = (5 - row) * (PITCH_LENGTH / 6.0) + 5.0
    x_pitch = (col + 0.5) * (PITCH_WIDTH / 5.0)
    return x_pitch, y_pitch


def _draw_pitch(ax: plt.Axes) -> None:
    """Draw a vertical soccer pitch (length=105 along y, width=68 along x)."""
    ax.set_facecolor(PITCH_COLOR)
    ax.set_xlim(-3, PITCH_WIDTH + 3)
    ax.set_ylim(-3, PITCH_LENGTH + 3)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    lw = 1.4
    lc = LINE_COLOR
    # Outer rectangle
    ax.add_patch(mpatches.Rectangle((0, 0), PITCH_WIDTH, PITCH_LENGTH,
                                    fill=False, edgecolor=lc, linewidth=lw))
    # Halfway line
    ax.plot([0, PITCH_WIDTH], [PITCH_LENGTH / 2, PITCH_LENGTH / 2],
            color=lc, linewidth=lw)
    # Center circle + spot
    ax.add_patch(mpatches.Circle((PITCH_WIDTH / 2, PITCH_LENGTH / 2), 9.15,
                                 fill=False, edgecolor=lc, linewidth=lw))
    ax.add_patch(mpatches.Circle((PITCH_WIDTH / 2, PITCH_LENGTH / 2), 0.3,
                                 color=lc))
    # Penalty boxes (16.5m deep, 40.32m wide, centered)
    pen_w = 40.32
    pen_d = 16.5
    pen_x = (PITCH_WIDTH - pen_w) / 2
    # bottom
    ax.add_patch(mpatches.Rectangle((pen_x, 0), pen_w, pen_d,
                                    fill=False, edgecolor=lc, linewidth=lw))
    # top
    ax.add_patch(mpatches.Rectangle((pen_x, PITCH_LENGTH - pen_d), pen_w, pen_d,
                                    fill=False, edgecolor=lc, linewidth=lw))
    # Goal boxes (5.5m deep, 18.32m wide)
    gb_w = 18.32
    gb_d = 5.5
    gb_x = (PITCH_WIDTH - gb_w) / 2
    ax.add_patch(mpatches.Rectangle((gb_x, 0), gb_w, gb_d,
                                    fill=False, edgecolor=lc, linewidth=lw))
    ax.add_patch(mpatches.Rectangle((gb_x, PITCH_LENGTH - gb_d), gb_w, gb_d,
                                    fill=False, edgecolor=lc, linewidth=lw))
    # Penalty spots
    ax.add_patch(mpatches.Circle((PITCH_WIDTH / 2, 11), 0.25, color=lc))
    ax.add_patch(mpatches.Circle((PITCH_WIDTH / 2, PITCH_LENGTH - 11), 0.25,
                                 color=lc))
    # Goals (small rectangles outside pitch)
    goal_w = 7.32
    goal_x = (PITCH_WIDTH - goal_w) / 2
    ax.add_patch(mpatches.Rectangle((goal_x, -2), goal_w, 2,
                                    fill=False, edgecolor=lc, linewidth=lw))
    ax.add_patch(mpatches.Rectangle((goal_x, PITCH_LENGTH), goal_w, 2,
                                    fill=False, edgecolor=lc, linewidth=lw))


def _resolve_team_name(team_id: str, matches: pd.DataFrame) -> str:
    home = matches[matches.home_id == team_id]
    if len(home):
        return str(home.iloc[0].home_name)
    away = matches[matches.away_id == team_id]
    if len(away):
        return str(away.iloc[0].away_name)
    return f"Team {team_id}"


def _pick_starters(team_id: str, lineups: pd.DataFrame, n: int = 11) -> pd.DataFrame:
    """Return top-N players by total on_seconds, with their modal position."""
    sub = lineups[lineups.team_id == team_id]
    if sub.empty:
        return sub
    totals = (
        sub.groupby(["player_id", "player_name"], as_index=False)["on_seconds"]
        .sum()
        .sort_values("on_seconds", ascending=False)
    )

    def modal_pos(pid: int) -> str:
        rows = sub[sub.player_id == pid]
        if rows.empty:
            return "DM"
        counts = rows["position"].value_counts()
        return str(counts.index[0]) if len(counts) else "DM"

    totals["position"] = totals["player_id"].apply(modal_pos)
    return totals.head(n).reset_index(drop=True)


def _resolve_unique_cells(starters: pd.DataFrame) -> list[tuple[int, int]]:
    """Assign each starter to a UNIQUE (row, col) cell on the 5x5+GK grid.

    Players with more minutes get their preferred cell first; later ties get
    bumped to the nearest empty cell.
    """
    # GK row is 5 (reserved), other valid cells are the 22 Bransen grid cells.
    # We expand to a slightly larger reachable set so 11 unique slots always exist.
    valid_cells = {
        (0, 0), (0, 2), (0, 4),
        (1, 1), (1, 2), (1, 3),
        (2, 0), (2, 1), (2, 2), (2, 3), (2, 4),
        (3, 0), (3, 1), (3, 2), (3, 3), (3, 4),
        (4, 0), (4, 1), (4, 2), (4, 3), (4, 4),
        (5, 2),  # GK
    }
    assignments: list[tuple[int, int]] = []
    taken: set[tuple[int, int]] = set()
    for _, r in starters.iterrows():
        pref = grid_cell(r["position"])
        if pref in valid_cells and pref not in taken:
            taken.add(pref); assignments.append(pref); continue
        # Find nearest empty cell by Manhattan distance from preferred
        candidates = sorted(
            valid_cells - taken,
            key=lambda c: (abs(c[0] - pref[0]) + abs(c[1] - pref[1]), c[0], c[1])
        )
        if not candidates:
            # Shouldn't happen with 11 starters and 22 cells, but fallback safely
            candidates = [(pref[0], pref[1])]
        chosen = candidates[0]
        taken.add(chosen); assignments.append(chosen)
    return assignments


def _player_xy_from_cell(row: int, col: int) -> tuple[float, float]:
    return _grid_to_pitch(row, col)


def _fetch_flag_image(code: str) -> "np.ndarray | None":
    """Fetch a PNG from flagcdn.com and return an RGB array. Cached on disk."""
    if not code:
        return None
    cache = Path.home() / ".cache" / "wc22_chemistry" / "flags"
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / f"{code}.png"
    if not cached.exists():
        url = f"https://flagcdn.com/640x480/{code}.png"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                cached.write_bytes(resp.read())
        except Exception:
            return None
    try:
        import matplotlib.image as mpimg
        return mpimg.imread(str(cached))
    except Exception:
        return None


def _last_name(name: str) -> str:
    parts = str(name).strip().split()
    if len(parts) >= 2:
        return parts[-1]
    return name


def draw_team_chemistry(
    team_id: str,
    *,
    metric: str,
    joi: pd.DataFrame,
    jdi: pd.DataFrame,
    lineups: pd.DataFrame,
    out_path: Path,
    min_minutes: float = 60.0,
    title: str | None = None,
    accent_color: str = "#1a5a1a",
    matches: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Render a chemistry pitch for one team and return metadata."""
    metric = metric.lower()
    if metric not in {"joi90", "jdi90"}:
        raise ValueError(f"metric must be joi90 or jdi90, got {metric}")
    pair_df = joi if metric == "joi90" else jdi
    mode_label = "Offensive Chemistry" if metric == "joi90" else "Defensive Chemistry"

    starters = _pick_starters(team_id, lineups, n=11)
    if starters.empty:
        raise ValueError(f"No lineup rows for team_id={team_id}")

    # Resolve unique grid cells (one player per cell).
    cells = _resolve_unique_cells(starters)
    players: list[dict[str, Any]] = []
    for (gr, gc), (_, r) in zip(cells, starters.iterrows()):
        x, y = _player_xy_from_cell(gr, gc)
        players.append({
            "player_id": int(r["player_id"]),
            "name": str(r["player_name"]),
            "position": str(r["position"]),
            "x": float(x),
            "y": float(y),
            "row": int(gr),
            "col": int(gc),
            "on_seconds": int(r["on_seconds"]),
        })
    pid_to_player = {p["player_id"]: p for p in players}
    pids = set(pid_to_player.keys())

    # Pull qualifying pairs that involve only our starters.
    team_pairs = pair_df[pair_df.team_id == team_id]
    team_pairs = team_pairs[
        team_pairs.player_p.isin(pids) & team_pairs.player_q.isin(pids)
    ]
    team_pairs = team_pairs[team_pairs.minutes_together >= min_minutes].copy()

    if len(team_pairs) == 0:
        median_val = 0.0
    else:
        median_val = float(team_pairs[metric].median())

    # Build figure
    fig, ax = plt.subplots(figsize=(7.5, 11.2), dpi=160)
    _draw_pitch(ax)

    # Tufte: drop the flag overlay. A muted grey-green pitch carries no chartjunk.
    # (Team identity belongs in the title/caption, not behind the data.)

    drawn_pairs: list[dict[str, Any]] = []
    if len(team_pairs) > 0:
        vals = team_pairs[metric].to_numpy()
        vmin = float(np.min(vals))
        vmax = float(np.max(vals)) if np.max(vals) > vmin else vmin + 1.0
        span = vmax - vmin or 1.0
        for _, row in team_pairs.iterrows():
            p = pid_to_player[int(row.player_p)]
            q = pid_to_player[int(row.player_q)]
            val = float(row[metric])
            # Sequential map: weakest → light, strongest → dark amber.
            t = float(np.clip((val - vmin) / span, 0.0, 1.0))
            color = CMAP(t)
            # Width also encodes strength but stays restrained.
            lw = 1.0 + 2.2 * t
            ax.plot(
                [p["x"], q["x"]], [p["y"], q["y"]],
                color=color, linewidth=lw, alpha=0.92,
                solid_capstyle="round", antialiased=True, zorder=2,
            )
            drawn_pairs.append({
                "player_p": p["player_id"],
                "player_q": q["player_id"],
                "name_p": p["name"],
                "name_q": q["name"],
                "value": val,
                "minutes_together": float(row.minutes_together),
            })

    # Player nodes + labels (small dots, no halos, no box around the name).
    for p in players:
        ax.add_patch(mpatches.Circle((p["x"], p["y"]), 1.6,
                                     facecolor="#111111",
                                     edgecolor="none",
                                     zorder=3))
        label = _last_name(p["name"])
        pos_tag = p["position"]
        if p["row"] <= 2:
            ly = p["y"] + 3.4
            va = "bottom"
        else:
            ly = p["y"] - 3.4
            va = "top"
        # Direct label, no chart-box. Inherits paper background.
        ax.text(
            p["x"], ly,
            f"{label}  {pos_tag}",
            ha="center", va=va, fontsize=8.0, color="#111111",
            zorder=4, linespacing=1.0,
        )

    # Title (figure-style, set in roman) and caption underneath.
    team_name = (
        _resolve_team_name(team_id, matches) if matches is not None else f"Team {team_id}"
    )
    side_label = "offensive" if metric == "joi90" else "defensive"
    metric_units = "JOI per 90 (action-VAEP·90/min)" if metric == "joi90" else "JDI per 90 (expected-OI saved·90/min)"
    figure_title = title or f"{team_name} — {side_label} chemistry"
    ax.set_title(figure_title, fontsize=13, color="#111111", pad=8,
                 fontweight="normal", loc="left")

    # Caption directly under the chart (Tufte print convention).
    caption = (
        f"Edges connect same-team pairs with ≥ {int(min_minutes)} shared minutes; "
        f"line darkness and width encode {metric_units}. "
        f"n = {len(drawn_pairs)} pairs."
    )
    ax.text(
        PITCH_WIDTH / 2, -6.0,
        caption,
        ha="center", va="top", fontsize=7.5, color="#555b62",
        wrap=True,
    )

    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight",
                facecolor="#f7f5ef")  # warm print-paper
    plt.close(fig)

    return {
        "team_id": team_id,
        "team_name": team_name,
        "metric": metric,
        "mode": mode_label,
        "out_path": str(out_path),
        "n_pairs": len(drawn_pairs),
        "median": median_val,
        "min_minutes": min_minutes,
        "players": players,
        "pairs": drawn_pairs,
    }


def render_all_teams(
    out_dir: Path,
    joi: pd.DataFrame,
    jdi: pd.DataFrame,
    lineups: pd.DataFrame,
    matches: pd.DataFrame,
    min_minutes: float = 60.0,
    min_qualifying_pairs: int = 5,
) -> list[dict[str, Any]]:
    """Render offensive + defensive chemistry pitches for every eligible team."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    qual = joi[joi.minutes_together >= min_minutes]
    counts = qual.groupby("team_id").size()
    eligible = [str(t) for t, n in counts.items() if n >= min_qualifying_pairs]

    results: list[dict[str, Any]] = []
    for team_id in sorted(eligible):
        for metric in ("joi90", "jdi90"):
            out_path = out_dir / f"team_{team_id}_{metric}.png"
            meta = draw_team_chemistry(
                team_id,
                metric=metric,
                joi=joi,
                jdi=jdi,
                lineups=lineups,
                out_path=out_path,
                min_minutes=min_minutes,
                matches=matches,
            )
            results.append(meta)
    return results
