"""SkillCorner Open Data loader.

Dataset: SkillCorner Open Data — 10 A-League matches.
    * License: MIT — fully open.
    * Source: <https://github.com/SkillCorner/opendata>
    * Broadcast tracking at **10 fps** (vs Metrica's 25 fps). Camera-visible
      players only; kloppy filters frames sensibly via ``only_alive=True``.

We fetch inline through :func:`kloppy.skillcorner.load_open_data`, so no
local download or path management is needed (same pattern as Metrica).

Phase-1 simplifications mirror the Metrica loader:
    * In-possession team derived per-frame from the player nearest the ball.
    * ``has_possession`` flag on that single nearest player.
    * Goalkeepers identified by extreme-x heuristic over a calibration window.
    * Velocities computed by finite-difference vs the previous yielded frame,
      with ``dt = sampling_stride / 10`` (10 Hz native), clamped to ±25 m/s.
    * If a frame has fewer than 22 visible players, pad the remaining
      tokens with zeros — the transformer treats them as inert.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
from kloppy import skillcorner

from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_PLAYERS_PER_FRAME,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    TrackingFrame,
)

OPEN_DATA_MATCH_IDS = (
    "1886347", "1899585", "1925299", "1953632", "1996435",
    "2006229", "2011166", "2013725", "2015213", "2017461",
)
MAX_SPEED_MPS = 25.0
GK_CALIBRATION_FRAMES = 200


def _resolve_match_id(match_path: Path | str | int) -> str:
    if isinstance(match_path, int):
        return str(match_path)
    s = str(match_path)
    if s.isdigit():
        return s
    return Path(s).name


def _identify_goalkeepers(dataset, n_calib: int = GK_CALIBRATION_FRAMES) -> set[str]:
    n = min(n_calib, len(dataset.frames))
    sums: dict[str, list[float]] = {}
    teams: dict[str, str] = {}
    for f in dataset.frames[:n]:
        for player, pdata in f.players_data.items():
            if pdata.coordinates is None:
                continue
            pid = player.player_id
            if pid not in sums:
                sums[pid] = [0.0, 0]
                teams[pid] = player.team.team_id
            sums[pid][0] += pdata.coordinates.x
            sums[pid][1] += 1
    mean_x: dict[str, float] = {
        pid: vals[0] / vals[1] for pid, vals in sums.items() if vals[1] > 0
    }
    gks: set[str] = set()
    for team_id in set(teams.values()):
        team_players = {pid: x for pid, x in mean_x.items() if teams[pid] == team_id}
        if not team_players:
            continue
        team_mean = sum(team_players.values()) / len(team_players)
        best_pid, best_score = None, -1.0
        for pid, x in team_players.items():
            score = abs(x - team_mean)
            if score > best_score:
                best_score, best_pid = score, pid
        if best_pid is not None:
            gks.add(best_pid)
    return gks


def load_skillcorner_match(
    match_path: Path | str | int,
    *,
    include_dead_ball: bool = True,
    sampling_stride: int = 1,
) -> Iterator[TrackingFrame]:
    """Load a single SkillCorner match as a stream of :class:`TrackingFrame`.

    Args:
        match_path: SkillCorner open-data match id (one of
            :data:`OPEN_DATA_MATCH_IDS`) or a Path whose leaf is the id.
        include_dead_ball: Currently unused — kloppy's ``only_alive`` default
            already filters dead-ball frames.
        sampling_stride: Yield every Nth raw frame (native is 10 Hz).
            ``2`` gives 5 Hz, matching the Metrica 5 Hz target.

    Yields:
        :class:`TrackingFrame` in chronological order.
    """
    del include_dead_ball
    match_id = _resolve_match_id(match_path)
    if match_id not in OPEN_DATA_MATCH_IDS:
        raise ValueError(
            f"SkillCorner open-data match id must be in {OPEN_DATA_MATCH_IDS!r}; "
            f"got {match_id!r}"
        )
    dataset = skillcorner.load_open_data(match_id=match_id)
    half_len = PITCH_LENGTH_M / 2.0
    half_wid = PITCH_WIDTH_M / 2.0
    dt = float(sampling_stride) / float(dataset.frame_rate)
    gk_ids = _identify_goalkeepers(dataset)
    n_features = len(FRAME_FEATURE_COLUMNS)

    prev_pos: dict[str, np.ndarray] = {}
    BALL_KEY = "__ball__"

    for frame_idx, f in enumerate(dataset.frames):
        if frame_idx % sampling_stride != 0:
            continue
        items = list(f.players_data.items())
        if not items:
            continue
        if f.ball_coordinates is None:
            continue

        positions_m = np.array(
            [(pd.coordinates.x * PITCH_LENGTH_M - half_len,
              pd.coordinates.y * PITCH_WIDTH_M - half_wid)
             for _, pd in items],
            dtype=np.float32,
        )
        # Ball may be Point3D; we use x, y only.
        ball_m = np.array(
            [f.ball_coordinates.x * PITCH_LENGTH_M - half_len,
             f.ball_coordinates.y * PITCH_WIDTH_M - half_wid],
            dtype=np.float32,
        )

        velocities = np.zeros_like(positions_m)
        for i, (player, _) in enumerate(items):
            prev = prev_pos.get(player.player_id)
            if prev is not None:
                v = (positions_m[i] - prev) / dt
                velocities[i] = np.clip(v, -MAX_SPEED_MPS, MAX_SPEED_MPS)
            prev_pos[player.player_id] = positions_m[i]

        prev_b = prev_pos.get(BALL_KEY)
        if prev_b is not None:
            ball_v = np.clip((ball_m - prev_b) / dt, -MAX_SPEED_MPS, MAX_SPEED_MPS)
        else:
            ball_v = np.zeros(2, dtype=np.float32)
        prev_pos[BALL_KEY] = ball_m

        dists = np.linalg.norm(positions_m - ball_m, axis=1)
        closest_idx = int(np.argmin(dists))
        in_possession_team = items[closest_idx][0].team

        players_feat = np.zeros((NUM_PLAYERS_PER_FRAME, n_features), dtype=np.float32)
        for i, (player, _) in enumerate(items[:NUM_PLAYERS_PER_FRAME]):
            is_attacking = 1.0 if player.team == in_possession_team else -1.0
            is_gk = 1.0 if player.player_id in gk_ids else 0.0
            has_poss = 1.0 if i == closest_idx else 0.0
            players_feat[i, 0] = positions_m[i, 0] / half_len
            players_feat[i, 1] = positions_m[i, 1] / half_wid
            players_feat[i, 2] = velocities[i, 0]
            players_feat[i, 3] = velocities[i, 1]
            players_feat[i, 4] = is_attacking
            players_feat[i, 5] = is_gk
            players_feat[i, 6] = has_poss

        ball_feat = np.zeros(n_features, dtype=np.float32)
        ball_feat[0] = ball_m[0] / half_len
        ball_feat[1] = ball_m[1] / half_wid
        ball_feat[2] = ball_v[0]
        ball_feat[3] = ball_v[1]

        yield TrackingFrame(
            match_id=f"skillcorner_{match_id}",
            period=f.period.id,
            frame_id=int(f.frame_id),
            timestamp_ms=int(f.timestamp.total_seconds() * 1000),
            players=players_feat,
            ball=ball_feat,
            in_possession_team_id=in_possession_team.team_id if in_possession_team else None,
        )


def list_skillcorner_matches(root: Path) -> list[Path]:
    """Return the open-data match ids as virtual paths.

    Args:
        root: Ignored (kloppy fetches inline). Kept for dispatcher symmetry.

    Returns:
        List of ten virtual paths, one per match id.
    """
    del root
    return [Path(mid) for mid in OPEN_DATA_MATCH_IDS]
