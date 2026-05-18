"""Metrica Sports sample data loader.

Uses :func:`kloppy.metrica.load_open_data` which fetches tracking CSVs
directly from <https://github.com/metrica-sports/sample-data> on first call,
so no local download or path management is needed.

Match IDs:
    "1", "2" — 25 Hz full-pitch tracking, both work end-to-end.
    "3"      — event-only release in a different format; skipped here.

Phase-1 simplifications (will refine when events are wired in):
    * ``in_possession_team`` derived per frame from the team owning the
      player nearest the ball. Cheap; will replace with the event stream's
      explicit ``ball_owning_team`` when we add events.
    * ``has_possession`` flag set on the single nearest player to the ball.
    * Goalkeeper identified per match by extreme-x heuristic: for each
      team, the player whose mean x over a calibration window sits closest
      to that team's defended goal line. (Metrica jersey numbers are
      anonymized — home is 1–14, away is 15–25, so the "jersey=1" trick
      from real soccer doesn't generalize.)
    * Velocities computed by finite-difference vs. the previously *yielded*
      frame, with ``dt = sampling_stride / frame_rate`` so downsampling
      doesn't inflate speeds. Clamped to ±25 m/s defensively to handle
      substitutions and tracker glitches.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
from kloppy import metrica

from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_PLAYERS_PER_FRAME,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    TrackingFrame,
)

OPEN_DATA_MATCH_IDS = ("1", "2")  # "3" is event-only, different format
MAX_SPEED_MPS = 25.0  # cap for clamping (cheetahs sprint at 30, ball passes at 30)
GK_CALIBRATION_FRAMES = 200  # frames to average over for GK detection


def _resolve_match_id(match_path: Path | str | int) -> str:
    """Pull a Metrica open-data match id out of the dispatcher's match_path."""
    if isinstance(match_path, int):
        return str(match_path)
    s = str(match_path)
    if s.isdigit():
        return s
    return Path(s).name


def _identify_goalkeepers(dataset, n_calib: int = GK_CALIBRATION_FRAMES) -> set[str]:
    """Return the player_ids of each team's goalkeeper.

    Heuristic: average each player's x-position across the first ``n_calib``
    frames; on each team, the player at the most extreme x is the GK. Works
    regardless of anonymization scheme.
    """
    n = min(n_calib, len(dataset.frames))
    sums: dict[str, list[float]] = {}     # player_id -> [x_total, count, team_id]
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
        # Mean x over this team — GK is the player furthest from their team's
        # mean x toward the goal line. We don't know which side of the pitch
        # each team defends a priori, so pick whichever extreme is farther.
        team_mean = sum(team_players.values()) / len(team_players)
        # Score each player by distance from the team's COM in the "toward
        # goal line" direction. Whoever's most extreme on either end is GK.
        best_pid, best_score = None, -1.0
        for pid, x in team_players.items():
            score = abs(x - team_mean)
            if score > best_score:
                best_score, best_pid = score, pid
        if best_pid is not None:
            gks.add(best_pid)
    return gks


def load_metrica_match(
    match_path: Path | str | int,
    *,
    include_dead_ball: bool = True,
    sampling_stride: int = 1,
) -> Iterator[TrackingFrame]:
    """Load a single Metrica match as a stream of :class:`TrackingFrame`.

    Args:
        match_path: Either a Metrica open-data match id (``"1"`` or ``"2"``)
            or a path whose leaf is the match id.
        include_dead_ball: Currently ignored — Metrica open data doesn't
            expose ball_state, so every frame is yielded.
        sampling_stride: Yield every Nth raw frame (native is 25 Hz).
            ``5`` gives 5 Hz, which is plenty for a smoke test.

    Yields:
        :class:`TrackingFrame` in chronological order.
    """
    del include_dead_ball  # placeholder until we wire in events
    match_id = _resolve_match_id(match_path)
    if match_id not in OPEN_DATA_MATCH_IDS:
        raise ValueError(
            f"Metrica open-data match id must be one of {OPEN_DATA_MATCH_IDS!r}; "
            f"got {match_id!r}. (Sample 3 is event-only and not supported.)"
        )

    dataset = metrica.load_open_data(match_id=match_id)
    half_len = PITCH_LENGTH_M / 2.0
    half_wid = PITCH_WIDTH_M / 2.0
    dt = float(sampling_stride) / float(dataset.frame_rate)

    gk_ids = _identify_goalkeepers(dataset)
    n_features = len(FRAME_FEATURE_COLUMNS)

    # Velocity bookkeeping: keyed by player_id (sentinel for ball).
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
                # Clamp to handle substitutions / tracker glitches.
                v = np.clip(v, -MAX_SPEED_MPS, MAX_SPEED_MPS)
                velocities[i] = v
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
            match_id=f"metrica_{match_id}",
            period=f.period.id,
            frame_id=int(f.frame_id),
            timestamp_ms=int(f.timestamp.total_seconds() * 1000),
            players=players_feat,
            ball=ball_feat,
            in_possession_team_id=in_possession_team.team_id if in_possession_team else None,
        )


def list_metrica_matches(root: Path) -> list[Path]:
    """Return the open-data match ids as virtual paths."""
    del root
    return [Path(mid) for mid in OPEN_DATA_MATCH_IDS]
