"""End-to-end tests for the DFL/Bassek (Sportec) loader.

Gated on the ``has_dfl_data`` fixture from ``conftest.py`` — every test here
is skipped automatically when ``data/raw/dfl_bassek/`` is empty, which is
the default state until the user downloads the figshare release.

When data is present, these tests verify:
  * ``load_dfl_match`` yields :class:`TrackingFrame` instances.
  * The ``(22, 7)`` player feature schema is honored.
  * Velocities are clamped at ``MAX_SPEED_MPS = 25`` m/s.
  * ``list_dfl_matches`` enumerates the per-match dirs.
"""

from pathlib import Path

import numpy as np
import pytest


def test_list_dfl_matches_no_data_returns_empty(has_dfl_data: bool, raw_data_root: Path) -> None:
    """list_dfl_matches must be safe to call even without downloaded data."""
    from wc2026_tracking_transformer.data.loaders.dfl import list_dfl_matches

    if has_dfl_data:
        pytest.skip("DFL data is present — this test only covers the empty case")
    assert list_dfl_matches(raw_data_root / "dfl_bassek") == []


def test_load_dfl_match_yields_tracking_frames(has_dfl_data: bool, raw_data_root: Path) -> None:
    """One real match yields valid TrackingFrame instances with the right shape."""
    if not has_dfl_data:
        pytest.skip("No DFL data present under data/raw/dfl_bassek/")

    from wc2026_tracking_transformer.data.loaders.dfl import (
        list_dfl_matches,
        load_dfl_match,
    )
    from wc2026_tracking_transformer.data.schema import TrackingFrame

    matches = list_dfl_matches(raw_data_root / "dfl_bassek")
    assert matches, "has_dfl_data is True but list_dfl_matches returned []"

    # Stride 25 = 1 Hz to keep CI fast.
    gen = load_dfl_match(matches[0], sampling_stride=25)
    frames = []
    for i, f in enumerate(gen):
        frames.append(f)
        if i >= 50:  # cap for test speed
            break

    assert len(frames) > 10, f"too few frames: {len(frames)}"
    assert all(isinstance(f, TrackingFrame) for f in frames)
    f0 = frames[0]
    assert f0.match_id.startswith("dfl_")
    assert f0.players.shape == (22, 7)
    assert f0.ball is not None and f0.ball.shape == (7,)


def test_load_dfl_match_clamps_velocities(has_dfl_data: bool, raw_data_root: Path) -> None:
    """Velocities should be clamped to ±25 m/s."""
    if not has_dfl_data:
        pytest.skip("No DFL data present under data/raw/dfl_bassek/")

    from wc2026_tracking_transformer.data.batching import batch_frames
    from wc2026_tracking_transformer.data.loaders.dfl import (
        list_dfl_matches,
        load_dfl_match,
    )

    matches = list_dfl_matches(raw_data_root / "dfl_bassek")
    gen = load_dfl_match(matches[0], sampling_stride=25)
    frames = []
    for i, f in enumerate(gen):
        frames.append(f)
        if i >= 50:
            break

    arr = batch_frames(frames)  # (N, 23, 7)
    assert arr.shape == (len(frames), 23, 7)

    # Position columns in [-1, 1] (small slack for edge frames).
    x_norm = arr[:, :, 0]
    y_norm = arr[:, :, 1]
    assert float(x_norm.min()) >= -1.1 and float(x_norm.max()) <= 1.1
    assert float(y_norm.min()) >= -1.1 and float(y_norm.max()) <= 1.1

    # Velocity columns clamped.
    v = arr[:, :, 2:4]
    assert float(np.abs(v).max()) <= 25.0 + 1e-3


def test_load_dfl_match_schema_flags(has_dfl_data: bool, raw_data_root: Path) -> None:
    """Per-frame: 2 GKs, 1 nearest-to-ball, 11-vs-11 attacking split."""
    if not has_dfl_data:
        pytest.skip("No DFL data present under data/raw/dfl_bassek/")

    from wc2026_tracking_transformer.data.batching import batch_frames
    from wc2026_tracking_transformer.data.loaders.dfl import (
        list_dfl_matches,
        load_dfl_match,
    )

    matches = list_dfl_matches(raw_data_root / "dfl_bassek")
    gen = load_dfl_match(matches[0], sampling_stride=25)
    frames = []
    for i, f in enumerate(gen):
        frames.append(f)
        if i >= 50:
            break

    arr = batch_frames(frames)
    # Note: these are sanity checks; Sportec data with substitutions may
    # produce frames missing a player, so we assert weakly here.
    gk_per_frame = arr[:, :22, 5].sum(axis=1)
    assert (gk_per_frame >= 1).all(), "expected at least 1 GK per frame"
    assert (gk_per_frame <= 2).all(), "expected at most 2 GKs per frame"
    poss_per_frame = arr[:, :22, 6].sum(axis=1)
    assert (poss_per_frame == 1).all(), "expected 1 nearest-to-ball flag per frame"


def test_load_dfl_events_raises_or_returns_df(has_dfl_data: bool, raw_data_root: Path) -> None:
    """load_dfl_events: returns a DataFrame with required columns, or
    FileNotFoundError if the event XML isn't present."""
    if not has_dfl_data:
        pytest.skip("No DFL data present under data/raw/dfl_bassek/")

    import pandas as pd

    from wc2026_tracking_transformer.data.loaders.dfl import (
        list_dfl_matches,
        load_dfl_events,
    )

    matches = list_dfl_matches(raw_data_root / "dfl_bassek")
    try:
        df = load_dfl_events(matches[0])
    except FileNotFoundError:
        pytest.skip("Event XML not present for this match (tracking-only)")
        return

    assert isinstance(df, pd.DataFrame)
    required_cols = {"frame_id", "period", "team", "event_type", "subtype", "is_goal"}
    assert required_cols.issubset(set(df.columns)), (
        f"missing cols: {required_cols - set(df.columns)}"
    )
