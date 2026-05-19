"""PFF FC 2022 World Cup loader.

PFF ships per-match bundles:
    * ``Metadata/<match_id>.json``  — match metadata (teams, season, kickoff)
    * ``Rosters/<match_id>.json``   — both teams' rosters with player ids
    * ``Event Data/<match_id>.json`` — event stream
    * ``Tracking Data/<match_id>.jsonl.bz2`` — per-frame tracking (bzipped JSONL)

The data is registration-gated (PFF requires sign-up). Once downloaded,
point this loader at the root directory containing the four subfolders.

Default root: ``/Users/nick/Desktop/drive-download-20260518T234612Z-3-001/``
(the user-downloaded folder). Override via ``PFF_ROOT`` env var or the
``root`` arg to :func:`load_pff_match` / :func:`list_pff_matches`.

The loader handles all 45 WC matches but is **designed for incremental
scale-up** — typical use is to call it with a small subset of match IDs
first (e.g., 1-2 matches), validate the pipeline, then scale up.
"""

from __future__ import annotations

import bz2
import os
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from kloppy import pff

from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_PLAYERS_PER_FRAME,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    TrackingFrame,
)

DEFAULT_PFF_ROOT = Path(
    os.environ.get("PFF_ROOT", "/Users/nick/Desktop/drive-download-20260518T234612Z-3-001")
)
MAX_SPEED_MPS = 25.0
GK_CALIBRATION_FRAMES = 200


def _resolve_match_paths(match_id: str | int, root: Path | None = None) -> tuple[Path, Path, Path]:
    """Return (metadata_path, roster_path, tracking_path) for a match."""
    root = root or DEFAULT_PFF_ROOT
    mid = str(match_id)
    meta = root / "Metadata" / f"{mid}.json"
    roster = root / "Rosters" / f"{mid}.json"
    tracking = root / "Tracking Data" / f"{mid}.jsonl.bz2"
    for p in (meta, roster, tracking):
        if not p.exists():
            raise FileNotFoundError(f"PFF file missing: {p}")
    return meta, roster, tracking


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
    mean_x = {pid: vals[0] / vals[1] for pid, vals in sums.items() if vals[1] > 0}
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


def load_pff_match(
    match_path: Path | str | int,
    *,
    include_dead_ball: bool = True,
    sampling_stride: int = 1,
    limit: int | None = None,
    root: Path | None = None,
) -> Iterator[TrackingFrame]:
    """Load a PFF match as a stream of :class:`TrackingFrame`.

    Args:
        match_path: Match id (e.g. ``"10502"``) or a path whose leaf is the id.
        include_dead_ball: Passed to kloppy's ``only_alive`` (inverted).
        sampling_stride: Yield every Nth raw frame. PFF native is ~30 Hz;
            ``6`` gives 5 Hz, matching Metrica/SkillCorner setups.
        limit: Optional cap on the number of frames to fetch from kloppy
            (useful for small-corpus smoke tests).
        root: Override the PFF data root directory.

    Yields:
        :class:`TrackingFrame` in chronological order.
    """
    match_id = _resolve_match_id(match_path)
    meta_path, roster_path, tracking_path = _resolve_match_paths(match_id, root)

    try:
        dataset = pff.load_tracking(
            meta_data=meta_path,
            roster_meta_data=roster_path,
            raw_data=tracking_path,
            only_alive=not include_dead_ball,
            limit=limit,
        )
    except Exception as e:
        # Fall back to in-memory decompress if kloppy's IO can't sniff .bz2.
        if any(t in str(e).lower() for t in ("bz2", "decode", "json", "compression")):
            with bz2.open(tracking_path, "rb") as fh:
                raw_bytes = fh.read()
            dataset = pff.load_tracking(
                meta_data=meta_path,
                roster_meta_data=roster_path,
                raw_data=raw_bytes,
                only_alive=not include_dead_ball,
                limit=limit,
            )
        else:
            raise

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
        if not items: continue
        if f.ball_coordinates is None: continue

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
                velocities[i] = np.clip(v, -MAX_SPEED_MPS, MAX_SPEED_MPS)
            prev_pos[player.player_id] = positions_m[i]

        prev_b = prev_pos.get(BALL_KEY)
        ball_v = np.clip((ball_m - prev_b) / dt, -MAX_SPEED_MPS, MAX_SPEED_MPS) \
                 if prev_b is not None else np.zeros(2, dtype=np.float32)
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
            match_id=f"pff_{match_id}",
            period=f.period.id,
            frame_id=int(f.frame_id),
            timestamp_ms=int(f.timestamp.total_seconds() * 1000),
            players=players_feat,
            ball=ball_feat,
            in_possession_team_id=in_possession_team.team_id if in_possession_team else None,
        )


def list_pff_matches(root: Path | None = None) -> list[Path]:
    """Return all PFF match ids available under ``root`` (as virtual paths).

    The returned list is sorted by match id so callers can deterministically
    slice ``[:N]`` to scale the corpus from 1 → 45 matches over time.
    """
    root = root or DEFAULT_PFF_ROOT
    tracking_dir = root / "Tracking Data"
    if not tracking_dir.exists():
        return []
    ids = sorted(p.stem.replace(".jsonl", "") for p in tracking_dir.glob("*.jsonl.bz2"))
    return [Path(mid) for mid in ids]
