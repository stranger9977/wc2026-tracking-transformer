"""DFL / Bassek 2025 (IDSSE) loader — PRIMARY data source.

Dataset: Bassek et al., "An integrated dataset of synchronized spatiotemporal
and event data in elite soccer", *Scientific Data* 12, 195 (2025).

  * 7 matches: 2 Bundesliga + 5 2. Bundesliga, 2022/23 season.
  * 25 Hz optical tracking (full pitch, all players, ball).
  * Synchronized Sportec event stream alongside tracking.
  * **License: CC-BY 4.0** — fully open. Cite the paper if you use it.
  * Paper: https://www.nature.com/articles/s41597-025-04505-y
  * Data:  hosted on figshare (linked from the paper).

The data ships in **Sportec / DFL XML format** (the same schema the Bundesliga
uses internally). kloppy ships a first-class Sportec adapter; this module
wraps :func:`kloppy.sportec.load_tracking` and :func:`kloppy.sportec.load_event`.

Expected directory layout
-------------------------

::

    data/raw/dfl_bassek/
      J03WMX/
        meta.xml         # Sportec match metadata (rosters, periods, pitch dims)
        tracking.xml     # 25 Hz positions feed
        event.xml        # synchronized event stream (optional for tracking-only)
      J03WN1/
        meta.xml
        tracking.xml
        event.xml
      ...

Per-match directory names are arbitrary but conventionally match the Sportec
``MatchId`` (e.g. ``J03WMX``, ``J03WPY`` — see the seven IDs in
:func:`kloppy.sportec.load_open_tracking_data`).

The three canonical filenames recognized by :func:`list_dfl_matches` and
:func:`_resolve_match_files` are:

  * tracking: ``tracking.xml`` (also accepted: anything matching ``*positions*.xml``
    or ``*_tracking.xml`` or ``*.dat.xml``).
  * metadata: ``meta.xml`` (also accepted: ``*metadata*.xml``, ``*_meta.xml``).
  * events  : ``event.xml`` (also accepted: ``*events*.xml``, ``*_event.xml``).

If the figshare download ships files with different names (the figshare
downloader emits numeric file IDs), rename or symlink them into the layout
above. The loader will pick them up via the glob patterns.

Phase status
------------

  * Phase 1 (this commit): tracking-only. ``load_dfl_match`` yields the
    normalized 22-player + ball :class:`TrackingFrame` stream and
    ``label_mode="thirds"`` works end-to-end.
  * Phase 2 (TODO): events. :func:`load_dfl_events` is implemented against
    ``kloppy.sportec.load_event`` but the exact column projection (especially
    ``is_goal`` detection across kloppy's Sportec event taxonomy) needs
    validation once the user has real XML to point at.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
from kloppy import sportec

from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_PLAYERS_PER_FRAME,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    TrackingFrame,
)

MAX_SPEED_MPS = 25.0  # cap for velocity clamping (matches metrica loader)
GK_CALIBRATION_FRAMES = 200  # frames to average over for GK detection

# Glob patterns for recognized filenames per match directory.
_TRACKING_GLOBS = ("tracking.xml", "*positions*.xml", "*_tracking.xml", "*.dat.xml")
_META_GLOBS = ("meta.xml", "*metadata*.xml", "*_meta.xml")
_EVENT_GLOBS = ("event.xml", "*events*.xml", "*_event.xml")


def _first_match(d: Path, patterns: tuple[str, ...]) -> Path | None:
    """Return the first file in ``d`` matching any of the glob patterns."""
    for pat in patterns:
        hits = sorted(d.glob(pat))
        if hits:
            return hits[0]
    return None


def _resolve_match_files(match_dir: Path) -> tuple[Path, Path, Path | None]:
    """Find ``(tracking_xml, meta_xml, event_xml_or_None)`` inside a match dir."""
    tracking = _first_match(match_dir, _TRACKING_GLOBS)
    meta = _first_match(match_dir, _META_GLOBS)
    if tracking is None or meta is None:
        raise FileNotFoundError(
            f"DFL match dir {match_dir!s} must contain a tracking XML "
            f"(one of {_TRACKING_GLOBS}) and a metadata XML "
            f"(one of {_META_GLOBS}). See module docstring for layout."
        )
    event = _first_match(match_dir, _EVENT_GLOBS)
    return tracking, meta, event


def _identify_goalkeepers(dataset, n_calib: int = GK_CALIBRATION_FRAMES) -> set[str]:
    """Return the player_ids of each team's goalkeeper.

    Same heuristic as the Metrica loader: average each player's x-position
    across the first ``n_calib`` frames, then on each team pick the player
    whose mean x is most extreme relative to the team's centroid. Works
    regardless of jersey-number convention.
    """
    n = min(n_calib, len(dataset.frames))
    sums: dict[str, list[float]] = {}     # player_id -> [x_total, count]
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


def load_dfl_match(
    match_path: Path | str,
    *,
    include_dead_ball: bool = True,
    sampling_stride: int = 1,
) -> Iterator[TrackingFrame]:
    """Load a single DFL/Bassek match as a stream of :class:`TrackingFrame`.

    Args:
        match_path: Per-match directory under ``data/raw/dfl_bassek/``,
            containing at minimum a tracking XML and a metadata XML (see
            module docstring for accepted filenames).
        include_dead_ball: If ``True`` (default), include frames where the
            ball is dead. Sportec exposes ``BallStatus`` so this is honored
            via kloppy's ``only_alive`` parameter — passing ``False`` makes
            kloppy filter to ALIVE-only frames upstream.
        sampling_stride: Yield every Nth raw frame (native is 25 Hz). ``5``
            gives 5 Hz, matching the Metrica default.

    Yields:
        :class:`TrackingFrame` in chronological order.
    """
    match_dir = Path(match_path)
    tracking_xml, meta_xml, _event_xml = _resolve_match_files(match_dir)

    # kloppy.sportec.load_tracking with coordinates="kloppy" returns
    # positions in normalized [0, 1] over (pitch_length, pitch_width), which
    # is the same convention the Metrica loader consumes.
    dataset = sportec.load_tracking(
        meta_data=str(meta_xml),
        raw_data=str(tracking_xml),
        coordinates="kloppy",
        only_alive=not include_dead_ball,
    )

    half_len = PITCH_LENGTH_M / 2.0
    half_wid = PITCH_WIDTH_M / 2.0
    dt = float(sampling_stride) / float(dataset.frame_rate)

    gk_ids = _identify_goalkeepers(dataset)
    n_features = len(FRAME_FEATURE_COLUMNS)

    # Velocity bookkeeping keyed by player_id (sentinel for ball).
    prev_pos: dict[str, np.ndarray] = {}
    BALL_KEY = "__ball__"

    # Stable match identifier — prefer the kloppy-extracted Sportec game_id,
    # fall back to the directory name.
    sportec_game_id = getattr(dataset.metadata, "game_id", None) or match_dir.name
    match_id_str = f"dfl_{sportec_game_id}"

    for frame_idx, f in enumerate(dataset.frames):
        if frame_idx % sampling_stride != 0:
            continue

        items = list(f.players_data.items())
        if not items:
            continue
        if f.ball_coordinates is None:
            continue

        positions_m = np.array(
            [(pd_.coordinates.x * PITCH_LENGTH_M - half_len,
              pd_.coordinates.y * PITCH_WIDTH_M - half_wid)
             for _, pd_ in items],
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
                v = np.clip(v, -MAX_SPEED_MPS, MAX_SPEED_MPS)
                velocities[i] = v
            prev_pos[player.player_id] = positions_m[i]

        prev_b = prev_pos.get(BALL_KEY)
        if prev_b is not None:
            ball_v = np.clip((ball_m - prev_b) / dt, -MAX_SPEED_MPS, MAX_SPEED_MPS)
        else:
            ball_v = np.zeros(2, dtype=np.float32)
        prev_pos[BALL_KEY] = ball_m

        # In-possession team: kloppy populates ``ball_owning_team`` from
        # Sportec's ``BallPossession`` field per frame. Fall back to the
        # nearest-player heuristic if it isn't set.
        in_possession_team = getattr(f, "ball_owning_team", None)
        dists = np.linalg.norm(positions_m - ball_m, axis=1)
        closest_idx = int(np.argmin(dists))
        if in_possession_team is None:
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
            match_id=match_id_str,
            period=f.period.id,
            frame_id=int(f.frame_id),
            timestamp_ms=int(f.timestamp.total_seconds() * 1000),
            players=players_feat,
            ball=ball_feat,
            in_possession_team_id=in_possession_team.team_id if in_possession_team else None,
        )


def list_dfl_matches(root: Path) -> list[Path]:
    """Return the per-match directories under a DFL release root.

    Args:
        root: Path to ``data/raw/dfl_bassek/``.

    Returns:
        Sorted list of per-match directory paths that contain both a tracking
        XML and a metadata XML (events are optional). If ``root`` does not
        exist or contains no eligible match dirs, returns an empty list — the
        caller is expected to surface a clear "data not downloaded" message.
    """
    root = Path(root)
    if not root.exists() or not root.is_dir():
        return []
    matches: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        has_tracking = _first_match(child, _TRACKING_GLOBS) is not None
        has_meta = _first_match(child, _META_GLOBS) is not None
        if has_tracking and has_meta:
            matches.append(child)
    return matches


def load_dfl_events(match_path: Path | str) -> pd.DataFrame:
    """Load Sportec event data for a DFL match as a flat DataFrame.

    Args:
        match_path: Per-match directory containing ``event.xml`` (or any
            file matching the event globs) and ``meta.xml``.

    Returns:
        DataFrame with at least the columns:
          * ``frame_id`` — frame number aligned to the tracking stream.
          * ``period`` — period id (1, 2, 3, 4).
          * ``team`` — team id of the team performing the event (or empty
            string if not applicable, e.g. period-boundary events).
          * ``event_type`` — kloppy event class name (e.g. ``"shot"``,
            ``"pass"``, ``"recovery"``).
          * ``subtype`` — kloppy event ``result`` enum value (e.g.
            ``"goal"`` for shots that scored), as a string. Empty if absent.
          * ``is_goal`` — bool, ``True`` iff this is a shot whose result is
            ``GOAL``.

    Raises:
        FileNotFoundError: If no event XML is present in ``match_path``.

    Notes:
        Phase-2 status. The exact projection from kloppy's Sportec event
        model to these columns may need light tweaking once we can verify
        against real data — in particular, kloppy's shot result enum spells
        a goal as ``ShotResult.GOAL`` and we stringify the .name on it,
        which the tests should sanity-check against a known goal frame.
    """
    match_dir = Path(match_path)
    tracking_xml, meta_xml, event_xml = _resolve_match_files(match_dir)
    del tracking_xml  # not needed for events
    if event_xml is None:
        raise FileNotFoundError(
            f"No event XML found in {match_dir!s} (looked for {_EVENT_GLOBS}). "
            f"Tracking-only mode is fine for label_mode='thirds'; for "
            f"label_mode='events' provide a synchronized event feed."
        )

    event_dataset = sportec.load_event(
        event_data=str(event_xml),
        meta_data=str(meta_xml),
    )

    rows: list[dict[str, object]] = []
    for ev in event_dataset.events:
        team = getattr(ev, "team", None)
        result = getattr(ev, "result", None)
        result_name = ""
        if result is not None:
            result_name = getattr(result, "name", str(result))
        event_type = type(ev).__name__.replace("Event", "").lower() or "unknown"
        is_goal = event_type == "shot" and result_name.upper() == "GOAL"
        rows.append(
            {
                "frame_id": int(getattr(ev, "raw_event", {}).get("frame_id", 0))
                if hasattr(ev, "raw_event") and isinstance(ev.raw_event, dict)
                else int(getattr(ev, "frame_id", 0) or 0),
                "period": int(ev.period.id) if getattr(ev, "period", None) else 0,
                "team": team.team_id if team is not None else "",
                "event_type": event_type,
                "subtype": result_name,
                "is_goal": bool(is_goal),
            }
        )
    return pd.DataFrame(
        rows,
        columns=["frame_id", "period", "team", "event_type", "subtype", "is_goal"],
    )
