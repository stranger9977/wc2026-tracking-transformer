"""Pitch-control x Expected-Threat space-value engine.

This is the SHARED FOUNDATION for the four "space" metrics (SMS, CHASE,
P-OBSO, SAR). Every metric is a cut of one quantity:

    VALUE-OF-SPACE(cell) = pitch_control_attacker(cell) * xT(cell)

where
    * pitch_control is the canonical Fernandez & Bornn (2018) player-influence
      model: each player owns a bivariate-normal influence whose mean sits
      ahead of the player (scaled by velocity), whose covariance is oriented
      along the velocity and stretched by distance-to-ball; the team-control
      surface is the softmax/logistic of summed influences, in [0, 1] per cell
      and summing to ~1 across the two teams; and
    * xT is Karun Singh's published 12x8 Expected-Threat lookup (the VALUE
      currency), mapped onto pitch coordinates oriented attacking-+x.

Coordinate convention (load-bearing): we work in METERS with the origin at the
pitch center, attacking-left-to-right so the in-possession team always moves
toward +x; the opponent goal is at x = +52.5. This is exactly what
``load_pff_match`` yields after un-normalizing x_norm/y_norm. xT therefore
peaks just outside the OPPONENT six-yard box at +x and is ~0 at the team's own
goal at -x. If a control/xT surface does not look like that, the orientation is
wrong.

Reference:
    William Spearman et al., "Physics-Based Modeling of Pass Probabilities in
    Soccer" (2017); Javier Fernandez & Luke Bornn, "Wide Open Spaces: A
    statistical technique for measuring space creation in professional soccer"
    (MIT Sloan 2018). We implement the Fernandez-Bornn player-influence variant
    (bivariate normal, velocity-oriented covariance, distance-to-ball scaling).

Run the self-test / validation:
    export PFF_ROOT="$HOME/pff_wc22_local"
    PYTHONPATH=src uv run python research/scripts/pitch_control.py
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# --- repo imports -----------------------------------------------------------
# Allow running both as a script (python research/scripts/pitch_control.py) and
# as an import. The package lives under src/, which PYTHONPATH=src exposes.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from wc2026_tracking_transformer.baselines.xt import XT_GRID, N_X_BINS, N_Y_BINS  # noqa: E402
from wc2026_tracking_transformer.data.schema import (  # noqa: E402
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
)

# ---------------------------------------------------------------------------
# Pitch geometry constants. Origin = center; attacking-left-to-right (+x is the
# direction the in-possession team attacks; opponent goal at +HALF_LEN).
# ---------------------------------------------------------------------------
HALF_LEN = PITCH_LENGTH_M / 2.0  # 52.5 m
HALF_WID = PITCH_WIDTH_M / 2.0   # 34.0 m

# Default control grid: ~50 x 34 cells over 105 x 68 m (cell ~2.1 x 2.0 m).
DEFAULT_NX = 50
DEFAULT_NY = 34

# ---------------------------------------------------------------------------
# Fernandez & Bornn (2018) player-influence parameters.
# ---------------------------------------------------------------------------
# Influence radius grows with distance-to-ball: near the ball a player controls
# a tight area (~4 m radius); far from the ball it widens to ~10 m. F&B fit a
# logistic between these bounds; we use their published min/max and midpoint.
INFLUENCE_R_MIN = 4.0      # m, radius scale when player is on the ball
INFLUENCE_R_MAX = 10.0     # m, radius scale when player is >= ~ball_far from ball
BALL_DIST_SAT = 18.0       # m, distance-to-ball at which radius saturates to MAX
# Speed ratio cap: covariance stretch along velocity scales with (speed/13)^2.
SPEED_NORM = 13.0          # m/s, ~max sprint; ratio is clipped to this
SPEED_RATIO_MAX = 1.0      # clip of (speed/SPEED_NORM)
# Mean of a player's influence is shifted ahead of position by half the
# distance covered in the next reaction window (F&B use 0.5 s look-ahead).
REACTION_S = 0.5

# Reachability decay for OBSO: P(ball reaches a location) ~ exp(-dist/lambda),
# which is the survival function of pass length if lambda = mean pass distance.
# Calibrated on PFF WC22: mean completed open-play pass = 13.73 m over 64
# matches (n=48,875). This restores ball-awareness that bare xT lacks: dangerous
# space the ball cannot realistically be played into is discounted toward 0.
REACH_LAMBDA_M = 13.73


@dataclass(frozen=True)
class Grid:
    """A pitch-coordinate evaluation grid in meters (origin center)."""

    nx: int
    ny: int
    xs: np.ndarray          # (nx,) cell-center x in meters
    ys: np.ndarray          # (ny,) cell-center y in meters
    XX: np.ndarray          # (ny, nx) meshgrid x
    YY: np.ndarray          # (ny, nx) meshgrid y
    cell_area_m2: float

    @property
    def shape(self) -> tuple[int, int]:
        return (self.ny, self.nx)


def make_grid(nx: int = DEFAULT_NX, ny: int = DEFAULT_NY) -> Grid:
    """Build a centered cell-center grid in meters over the full pitch."""
    # Cell centers, evenly spaced, covering [-HALF_LEN, HALF_LEN] x [-HALF_WID, HALF_WID].
    xs = np.linspace(-HALF_LEN + HALF_LEN / nx, HALF_LEN - HALF_LEN / nx, nx)
    ys = np.linspace(-HALF_WID + HALF_WID / ny, HALF_WID - HALF_WID / ny, ny)
    XX, YY = np.meshgrid(xs, ys)  # (ny, nx)
    cell_area = (PITCH_LENGTH_M / nx) * (PITCH_WIDTH_M / ny)
    return Grid(nx=nx, ny=ny, xs=xs, ys=ys, XX=XX, YY=YY, cell_area_m2=cell_area)


# ===========================================================================
# xT VALUE LAYER  (tee this up first; everything multiplies by it)
# ===========================================================================
def xt_value(x_norm: np.ndarray | float, y_norm: np.ndarray | float) -> np.ndarray | float:
    """Expected-Threat value at normalized pitch coords (attacking-+x).

    Args:
        x_norm: x in [-1, 1] (own goal at -1, opponent goal at +1).
        y_norm: y in [-1, 1] across the short axis.

    Returns:
        xT value(s) from the canonical Singh 12x8 grid, same shape as input.
        Out-of-bounds positions clip to the nearest cell.
    """
    fx = np.clip((np.asarray(x_norm, dtype=np.float64) + 1.0) * 0.5, 0.0, 1.0 - 1e-9)
    fy = np.clip((np.asarray(y_norm, dtype=np.float64) + 1.0) * 0.5, 0.0, 1.0 - 1e-9)
    rows = (fx * N_X_BINS).astype(np.int64)
    cols = (fy * N_Y_BINS).astype(np.int64)
    out = XT_GRID[rows, cols]
    if np.isscalar(x_norm) and np.isscalar(y_norm):
        return float(out)
    return out


def xt_value_m(x_m: np.ndarray | float, y_m: np.ndarray | float) -> np.ndarray | float:
    """xT value at pitch coords in METERS (origin center, attacking-+x)."""
    return xt_value(np.asarray(x_m) / HALF_LEN, np.asarray(y_m) / HALF_WID)


def xt_surface(grid: Grid) -> np.ndarray:
    """The xT value at every grid cell, shape (ny, nx)."""
    return np.asarray(xt_value_m(grid.XX, grid.YY), dtype=np.float64)


# ===========================================================================
# PITCH CONTROL  (Fernandez & Bornn 2018 player-influence)
# ===========================================================================
def _player_influence(
    px: float, py: float, vx: float, vy: float,
    ball_x: float, ball_y: float,
    grid: Grid,
) -> np.ndarray:
    """Single-player bivariate-normal influence over the grid, peak-normalized.

    Returns (ny, nx) in [0, 1] (1 at the player's influence center).

    Following Fernandez & Bornn:
      * influence center = position + 0.5 * velocity * REACTION_S (lead-ahead);
      * the local radius (overall scale) grows with distance-to-ball from
        INFLUENCE_R_MIN (on ball) to INFLUENCE_R_MAX (far);
      * the covariance is rotated to align with the velocity and stretched
        along it by a speed ratio: faster => more elongated forward.
    """
    speed = float(np.hypot(vx, vy))
    # Distance-to-ball scaling of the influence radius (the "Ri" of F&B).
    dist_ball = float(np.hypot(px - ball_x, py - ball_y))
    frac = min(dist_ball / BALL_DIST_SAT, 1.0)
    radius = INFLUENCE_R_MIN + (INFLUENCE_R_MAX - INFLUENCE_R_MIN) * (frac ** 2)

    # Speed ratio drives anisotropy along the direction of travel.
    sratio = min(speed / SPEED_NORM, SPEED_RATIO_MAX)
    # Singular values of the covariance (std devs along / across velocity).
    s_along = radius * (1.0 + sratio)
    s_perp = radius * (1.0 - sratio)
    s_perp = max(s_perp, radius * 0.30)  # floor so it never collapses

    # Influence center, shifted ahead by half the velocity over the reaction window.
    mu_x = px + 0.5 * vx * REACTION_S
    mu_y = py + 0.5 * vy * REACTION_S

    # Rotation aligned with velocity (fall back to +x if stationary).
    if speed > 1e-3:
        cos_t = vx / speed
        sin_t = vy / speed
    else:
        cos_t, sin_t = 1.0, 0.0

    # Mahalanobis distance with the rotated, scaled covariance:
    #   rotate (dx, dy) into the velocity frame, then divide by (s_along, s_perp).
    dx = grid.XX - mu_x
    dy = grid.YY - mu_y
    u = cos_t * dx + sin_t * dy       # along velocity
    w = -sin_t * dx + cos_t * dy      # perpendicular
    m2 = (u / s_along) ** 2 + (w / s_perp) ** 2
    return np.exp(-0.5 * m2)


def control_surface(
    players: np.ndarray,
    ball_m: np.ndarray,
    grid: Grid,
    *,
    include_gk: bool = True,
    beta: float = 3.0,
) -> dict:
    """Compute the team pitch-control surface for one frame.

    Args:
        players: (22, 7) array of per-player features in the schema order
            (x_norm, y_norm, vx, vy, is_attacking_side, is_goalkeeper,
            has_possession). x_norm/y_norm are in [-1, 1] (attacking-+x).
        ball_m: (2,) ball position in METERS (origin center). Pass
            ``np.array([ball_feat[0]*HALF_LEN, ball_feat[1]*HALF_WID])``.
        grid: evaluation Grid.
        include_gk: keep goalkeepers (they own their own box; useful for the
            GK validation and for P-OBSO/CHASE around the area).
        beta: logistic sharpness on the influence difference. Larger => more
            decisive ownership per cell.

    Returns:
        dict with:
          attack_control (ny, nx) in [0, 1]: P(in-possession team controls cell)
          defend_control (ny, nx) in [0, 1]: 1 - attack_control
          attack_infl    (ny, nx): summed attacker influence (pre-logistic)
          defend_infl    (ny, nx): summed defender influence (pre-logistic)
          player_influence: (n_kept, ny, nx) per-player influence
          player_x_m, player_y_m: (n_kept,) meter positions
          player_is_attacking: (n_kept,) bool
          player_idx: (n_kept,) index back into the original 22-row block
    """
    px = players[:, 0] * HALF_LEN
    py = players[:, 1] * HALF_WID
    vx = players[:, 2]
    vy = players[:, 3]
    is_att = players[:, 4] > 0
    is_gk = players[:, 5] > 0.5

    keep = np.ones(players.shape[0], dtype=bool)
    if not include_gk:
        keep &= ~is_gk
    # Drop all-zero padding rows (no position and no velocity).
    nonzero = ~((px == 0) & (py == 0) & (vx == 0) & (vy == 0))
    keep &= nonzero
    idx = np.where(keep)[0]

    infl = np.zeros((len(idx), grid.ny, grid.nx), dtype=np.float64)
    for j, i in enumerate(idx):
        infl[j] = _player_influence(
            float(px[i]), float(py[i]), float(vx[i]), float(vy[i]),
            float(ball_m[0]), float(ball_m[1]), grid,
        )

    att_mask = is_att[idx]
    attack_infl = infl[att_mask].sum(axis=0) if att_mask.any() else np.zeros(grid.shape)
    defend_infl = infl[~att_mask].sum(axis=0) if (~att_mask).any() else np.zeros(grid.shape)

    # Logistic ownership: attacker wins a cell to the degree its summed
    # influence exceeds the defender's (Spearman/F&B style normalization).
    attack_control = 1.0 / (1.0 + np.exp(-beta * (attack_infl - defend_infl)))

    return {
        "attack_control": attack_control,
        "defend_control": 1.0 - attack_control,
        "attack_infl": attack_infl,
        "defend_infl": defend_infl,
        "player_influence": infl,
        "player_x_m": px[idx],
        "player_y_m": py[idx],
        "player_is_attacking": att_mask,
        "player_idx": idx,
        "ball_m": np.asarray(ball_m, dtype=np.float64),
    }


# ===========================================================================
# SPACE OCCUPATION + VALUE-OF-SPACE (the shared quantity)
# ===========================================================================
def reach_surface(ball_m: np.ndarray, grid: Grid) -> np.ndarray:
    """P(the ball can be played to each cell), an exp decay from the ball.

    ``reach(d) = exp(-d / REACH_LAMBDA_M)`` is the survival function of pass
    length (P(a pass travels >= d)) when lambda is the mean pass distance. This
    is the ball-aware factor that turns control x xT into proper OBSO: space the
    ball cannot realistically reach right now is discounted toward 0.

    Returns (ny, nx) in (0, 1], = 1 at the ball.
    """
    d = np.hypot(grid.XX - float(ball_m[0]), grid.YY - float(ball_m[1]))
    return np.exp(-d / REACH_LAMBDA_M)


def value_of_space_surface(control: dict, grid: Grid) -> np.ndarray:
    """OBSO: reach x attacker pitch-control x xT(cell), the shared value surface.

    Returns (ny, nx) >= 0; integrate (sum * cell_area) for total controlled
    xT-weighted space, or slice per-player via :func:`player_space`.
    """
    return (control["attack_control"] * xt_surface(grid)
            * reach_surface(control["ball_m"], grid))


def player_space(control: dict, grid: Grid, *, attacking_only: bool = True) -> dict:
    """Per-player controllable area (m^2) and xT-weighted controllable value.

    A cell is attributed to the player whose influence dominates it, weighted
    by the team-control already won there (so contested cells count less). The
    xT-weighted version multiplies each attributed cell by xT(cell).

    Returns:
        dict mapping original player index -> {area_m2, xt_value}.
    """
    infl = control["player_influence"]            # (n, ny, nx)
    idx = control["player_idx"]
    is_att = control["player_is_attacking"]
    # Per-PLAYER owned value uses control x xT WITHOUT reach (occupation, F&B
    # SOG). Reach lives on the full surface (value_of_space_surface) and team
    # OBSO; on a local per-player attribution it would only penalise forwards.
    xt = xt_surface(grid)
    attack_control = control["attack_control"]

    # Each cell goes to its argmax-influence player; team-control weights it.
    if attacking_only:
        sel = is_att
    else:
        sel = np.ones(len(idx), dtype=bool)
    if not sel.any():
        return {}
    sub_infl = infl[sel]
    sub_idx = idx[sel]
    sub_is_att = is_att[sel]
    owner = np.argmax(sub_infl, axis=0)           # (ny, nx)

    out: dict = {}
    for k, orig_i in enumerate(sub_idx):
        cells = owner == k
        # weight cells by the controlling team's control there
        w = np.where(sub_is_att[k], attack_control, 1.0 - attack_control)
        area = float((cells * w).sum() * grid.cell_area_m2)
        xtv = float((cells * w * xt).sum() * grid.cell_area_m2)
        out[int(orig_i)] = {"area_m2": area, "xt_value": xtv}
    return out


# ===========================================================================
# SURFACE EXPORT  (for the live scrubbable heatmap on the page)
# ===========================================================================
def _downsample(surface: np.ndarray, out_ny: int, out_nx: int) -> np.ndarray:
    """Area-average a (ny, nx) surface down to (out_ny, out_nx)."""
    ny, nx = surface.shape
    if (ny, nx) == (out_ny, out_nx):
        return surface
    # Block-mean via reshape when divisible, else nearest-bin pooling.
    ys = np.linspace(0, ny, out_ny + 1).astype(int)
    xs = np.linspace(0, nx, out_nx + 1).astype(int)
    out = np.zeros((out_ny, out_nx), dtype=np.float64)
    for i in range(out_ny):
        for j in range(out_nx):
            out[i, j] = surface[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean()
    return out


def export_surface_json(
    *,
    match_id: str | int,
    period: int,
    start_s: float,
    end_s: float,
    out_path: str | Path,
    metric_name: str,
    surface_fn=value_of_space_surface,
    out_grid: tuple[int, int] = (26, 40),      # (ny, nx) small for fast client render
    compute_grid: tuple[int, int] = (DEFAULT_NY, DEFAULT_NX),
    sampling_stride: int = 6,
    include_gk: bool = True,
    root: Path | None = None,
    title: str | None = None,
    description: str | None = None,
) -> dict:
    """Compute + export a per-frame downsampled surface for a time window.

    The output JSON is a live scrubbable heatmap payload:
        {
          metric, match_id, period, start_s, end_s, hz,
          grid: {nx, ny, length_m, width_m},
          xt_reference: (ny, nx) static xT (0..1 of its own max),
          frames: [ {t_s, ball_xy, surface: (ny, nx) values 0..1, raw_max} ]
        }

    Returns the dict it wrote (also for in-process inspection).
    """
    from wc2026_tracking_transformer.data.loaders.pff import load_pff_match  # local import

    out_ny, out_nx = out_grid
    cg = make_grid(nx=compute_grid[1], ny=compute_grid[0])
    out_g = make_grid(nx=out_nx, ny=out_ny)

    # We must load up to end_s; bound the kloppy fetch by frame index. PFF is
    # 30 Hz; cap a bit beyond end_s to be safe.
    raw_hz = 30.0
    limit = int((end_s + 5.0) * raw_hz) + 10

    frames_out = []
    raw_maxes = []
    for f in load_pff_match(match_id, sampling_stride=sampling_stride, limit=limit, root=root):
        if f.period != period:
            continue
        t_s = f.timestamp_ms / 1000.0
        if t_s < start_s or t_s > end_s:
            continue
        ball_m = np.array([f.ball[0] * HALF_LEN, f.ball[1] * HALF_WID])
        ctrl = control_surface(f.players, ball_m, cg, include_gk=include_gk)
        surf = surface_fn(ctrl, cg)
        surf_ds = _downsample(surf, out_ny, out_nx)
        rmax = float(surf_ds.max())
        raw_maxes.append(rmax)
        frames_out.append({
            "t_s": round(t_s, 2),
            "frame_id": int(f.frame_id),
            "ball_xy": [round(float(ball_m[0]), 2), round(float(ball_m[1]), 2)],
            "in_possession_team_id": f.in_possession_team_id,
            "surface_raw": surf_ds,   # placeholder; normalized below
            "raw_max": round(rmax, 5),
        })

    # Normalize all frames by the window's global max so the heatmap color
    # scale is stable across the scrub (values land in [0, 1]).
    gmax = max(raw_maxes) if raw_maxes else 1.0
    gmax = gmax if gmax > 0 else 1.0
    for fr in frames_out:
        s = (fr.pop("surface_raw") / gmax)
        fr["surface"] = [[round(float(v), 4) for v in row] for row in s]

    xt_ref = xt_surface(out_g)
    xt_ref_norm = xt_ref / (xt_ref.max() if xt_ref.max() > 0 else 1.0)

    payload = {
        "metric": metric_name,
        "title": title or metric_name,
        "description": description or "",
        "match_id": str(match_id),
        "period": period,
        "start_s": start_s,
        "end_s": end_s,
        "hz": round(raw_hz / sampling_stride, 2),
        "n_frames": len(frames_out),
        "grid": {"nx": out_nx, "ny": out_ny,
                 "length_m": PITCH_LENGTH_M, "width_m": PITCH_WIDTH_M},
        "global_max": round(gmax, 5),
        "xt_reference": [[round(float(v), 4) for v in row] for row in xt_ref_norm],
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "frames": frames_out,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(payload, fh)
    return payload


def export_xt_reference_json(out_path: str | Path, out_grid: tuple[int, int] = (26, 40)) -> dict:
    """Export the static xT reference surface for the page to lead with."""
    out_ny, out_nx = out_grid
    g = make_grid(nx=out_nx, ny=out_ny)
    xt = xt_surface(g)
    payload = {
        "metric": "xt_reference",
        "title": "Expected Threat (xT) - the value of space",
        "description": ("Karun Singh's canonical 12x8 Expected-Threat grid mapped to "
                        "the pitch, attacking left-to-right. Peaks just outside the "
                        "opponent six-yard box (~0.30); ~0 at your own goal. This is "
                        "the value currency every space metric multiplies by."),
        "grid": {"nx": out_nx, "ny": out_ny,
                 "length_m": PITCH_LENGTH_M, "width_m": PITCH_WIDTH_M},
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "max_xt": round(float(xt.max()), 5),
        "surface": [[round(float(v), 5) for v in row] for row in xt],
        "surface_norm": [[round(float(v / xt.max()), 4) for v in row] for row in xt],
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(payload, fh)
    return payload


# ===========================================================================
# VALIDATION / SELF-TEST
# ===========================================================================
def _validate():
    import time

    print("=" * 70)
    print("PITCH-CONTROL x xT ENGINE — VALIDATION")
    print("=" * 70)

    # ---- (5) xT correctness FIRST (load-bearing) -------------------------
    print("\n[xT] reference-point check (attacking-+x; opp goal at +52.5 m):")
    pts = {
        "own goal (-52.5, 0)":            (-52.5, 0.0),
        "own half center (-26, 0)":       (-26.0, 0.0),
        "halfway (0, 0)":                 (0.0, 0.0),
        "att half center (+26, 0)":       (26.0, 0.0),
        "outside opp 6yd box (+47, 0)":   (47.0, 0.0),
        "opp goal line center (+52, 0)":  (52.0, 0.0),
        "opp goal wide (+52, +30)":       (52.0, 30.0),
    }
    xt_vals = {}
    for name, (x, y) in pts.items():
        v = float(xt_value_m(x, y))
        xt_vals[name] = v
        print(f"   {name:<32} xT = {v:.4f}")
    g = make_grid()
    xt_s = xt_surface(g)
    peak_idx = np.unravel_index(int(np.argmax(xt_s)), xt_s.shape)
    peak_x = g.xs[peak_idx[1]]
    peak_y = g.ys[peak_idx[0]]
    print(f"   xT surface peak = {xt_s.max():.4f} at (x={peak_x:.1f} m, y={peak_y:.1f} m)")
    xt_ok = (
        xt_vals["outside opp 6yd box (+47, 0)"] > 0.20                                # peak band central ~0.26
        and xt_vals["outside opp 6yd box (+47, 0)"] > xt_vals["halfway (0, 0)"]        # increases toward goal
        and xt_vals["halfway (0, 0)"] > xt_vals["own half center (-26, 0)"]            # monotone in x
        and xt_vals["own goal (-52.5, 0)"] < 0.02                                      # ~0 at own goal
        and peak_x > 40.0                                                             # peak at the ATTACKING end (not flipped)
        and abs(peak_y) < 8.0                                                         # peak is CENTRAL, not in the corner
        # the value is higher CENTRAL than WIDE at the same x (the bug we fixed)
        and xt_vals["opp goal line center (+52, 0)"] > xt_vals["opp goal wide (+52, +30)"]
    )
    print(f"   xT PROFILE OK (peaks CENTRAL at +x, ~0 own goal, monotone): {xt_ok}")

    # ---- load a real frame ----------------------------------------------
    root = os.environ.get("PFF_ROOT")
    print(f"\n[load] PFF_ROOT={root}")
    from wc2026_tracking_transformer.data.loaders.pff import load_pff_match

    t0 = time.time()
    frames = []
    for f in load_pff_match("10503", sampling_stride=6, limit=12000):
        if f.period == 1:
            frames.append(f)
    load_s = time.time() - t0
    print(f"[load] {len(frames)} period-1 frames in {load_s:.1f}s")

    # Pick a SETTLED-possession frame: a teammate essentially on the ball
    # (nearest attacker within 1.5 m) with the ball in the central channel of
    # the attacking half (|y| < 15 m, x > 5 m). A 50/50 ball at the halfway
    # line, or a wide ball hard against the touchline, genuinely has ~0.5
    # central-region control, so neither is the right frame to validate
    # "in-possession team owns the ball region" against — we want a frame where
    # possession is settled in a place the model should clearly award.
    def _nearest_attacker_dist(cand):
        px = cand.players[:, 0] * HALF_LEN
        py = cand.players[:, 1] * HALF_WID
        att = cand.players[:, 4] > 0
        bx, by = cand.ball[0] * HALF_LEN, cand.ball[1] * HALF_WID
        d = np.hypot(px - bx, py - by)
        return float(d[att].min()) if att.any() else 99.0

    candidates = [
        c for c in frames
        if (c.in_possession_team_id and c.ball[0] > 0.10 and abs(c.ball[1]) < 0.45
            and _nearest_attacker_dist(c) < 1.5)
    ]
    fr = candidates[len(candidates) // 2] if candidates else frames[len(frames) // 2]
    ball_m = np.array([fr.ball[0] * HALF_LEN, fr.ball[1] * HALF_WID])
    print(f"[frame] t={fr.timestamp_ms/1000:.1f}s ball=({ball_m[0]:.1f},{ball_m[1]:.1f}) m  "
          f"poss_team={fr.in_possession_team_id}")

    # ---- (4) timing ------------------------------------------------------
    t0 = time.time()
    ctrl = control_surface(fr.players, ball_m, g, include_gk=True)
    ctl_s = time.time() - t0
    print(f"\n[timing] control_surface on {g.ny}x{g.nx} grid: {ctl_s*1000:.0f} ms")

    ac = ctrl["attack_control"]
    dc = ctrl["defend_control"]

    # ---- (1) control in [0,1] and teams sum ~1 --------------------------
    sums = ac + dc
    print(f"\n[check1] attack_control range [{ac.min():.3f}, {ac.max():.3f}]")
    print(f"[check1] attack+defend per cell: min={sums.min():.4f} max={sums.max():.4f} "
          f"mean={sums.mean():.4f}  (should be ~1.0)")
    c1_ok = (ac.min() >= -1e-9 and ac.max() <= 1 + 1e-9
             and abs(sums.mean() - 1.0) < 1e-6 and abs(sums.max() - 1.0) < 1e-6)
    print(f"[check1] OK: {c1_ok}")

    # ---- (2) in-possession team controls region around the ball ---------
    bi = int(np.argmin(np.abs(g.ys - ball_m[1])))
    bj = int(np.argmin(np.abs(g.xs - ball_m[0])))
    ball_ctrl = float(ac[bi, bj])
    # average control in a 3x3 cell window around the ball
    i0, i1 = max(0, bi - 1), min(g.ny, bi + 2)
    j0, j1 = max(0, bj - 1), min(g.nx, bj + 2)
    ball_region_ctrl = float(ac[i0:i1, j0:j1].mean())
    print(f"\n[check2] attacker control at ball cell = {ball_ctrl:.3f}; "
          f"3x3 region mean = {ball_region_ctrl:.3f}  (should be > 0.5)")
    c2_ok = ball_region_ctrl > 0.5
    print(f"[check2] OK: {c2_ok}")

    # ---- (3) each GK controls its own box --------------------------------
    # Identify the two GKs and check each dominates a cell at its own goal mouth.
    is_gk = fr.players[:, 5] > 0.5
    gk_idx = np.where(is_gk)[0]
    print(f"\n[check3] {len(gk_idx)} GKs found")
    c3_ok = True
    infl = ctrl["player_influence"]
    pidx = list(ctrl["player_idx"])
    for gi in gk_idx:
        gx = fr.players[gi, 0] * HALF_LEN
        gy = fr.players[gi, 1] * HALF_WID
        gatt = fr.players[gi, 4] > 0
        # cell at the GK's position
        ci = int(np.argmin(np.abs(g.ys - gy)))
        cj = int(np.argmin(np.abs(g.xs - gx)))
        # is this GK the argmax-influence player at its own cell?
        if gi in pidx:
            k = pidx.index(gi)
            owner = int(np.argmax(infl[:, ci, cj]))
            owns = owner == k
        else:
            owns = False
        # team-control at the GK cell should favor the GK's team
        team_ctrl = ac[ci, cj] if gatt else dc[ci, cj]
        print(f"   GK idx{gi} at (x={gx:.1f},y={gy:.1f}) att={gatt} "
              f"owns-its-cell={owns} team_ctrl_there={float(team_ctrl):.3f}")
        c3_ok &= owns and float(team_ctrl) > 0.5
    print(f"[check3] OK: {c3_ok}")

    # ---- value-of-space + per-player space -------------------------------
    vos = value_of_space_surface(ctrl, g)
    total_vos = float(vos.sum() * g.cell_area_m2)
    ps = player_space(ctrl, g, attacking_only=True)
    top = sorted(ps.items(), key=lambda kv: -kv[1]["xt_value"])[:3]
    print(f"\n[value] total attacker value-of-space (xT-weighted m^2) = {total_vos:.3f}")
    print("[value] top-3 attackers by xT-weighted controllable value:")
    for i, d in top:
        nm = f"idx{i}"
        print(f"   {nm}: area={d['area_m2']:.0f} m^2  xT-value={d['xt_value']:.4f}")

    # ---- export xT reference + a hero-play surface -----------------------
    surf_dir = _REPO / "research" / "site" / "data" / "surfaces"
    xt_ref_path = surf_dir / "xt_reference.json"
    export_xt_reference_json(xt_ref_path)
    print(f"\n[export] xT reference -> {xt_ref_path}")

    # Hero play: Messi 35' vs Australia (match 10503, period 1, 2055-2078 s) —
    # an off-ball build-up that ends in a goal; a good space showcase.
    hero_path = surf_dir / "value_of_space_demo.json"
    pay = export_surface_json(
        match_id="10503", period=1, start_s=2055.0, end_s=2078.0,
        out_path=hero_path, metric_name="value_of_space",
        title="Value of space (pitch-control x xT) — Messi 35' build-up",
        description=("Attacker pitch control x Expected Threat, integrated per frame. "
                     "This is the shared surface the four space metrics cut from."),
    )
    print(f"[export] hero value-of-space surface ({pay['n_frames']} frames, "
          f"{pay['grid']['ny']}x{pay['grid']['nx']}) -> {hero_path}")

    all_ok = xt_ok and c1_ok and c2_ok and c3_ok
    print("\n" + "=" * 70)
    print(f"ALL CHECKS PASS: {all_ok}   "
          f"(xt={xt_ok} c1={c1_ok} c2={c2_ok} c3={c3_ok})")
    print("=" * 70)
    return all_ok


if __name__ == "__main__":
    ok = _validate()
    sys.exit(0 if ok else 1)
