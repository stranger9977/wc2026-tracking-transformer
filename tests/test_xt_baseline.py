"""Smoke tests for the xT baseline."""

from __future__ import annotations

import numpy as np

from wc2026_tracking_transformer.baselines.xt import (
    N_X_BINS,
    N_Y_BINS,
    XT_GRID,
    xt_for_ball,
    xt_per_frame,
)


def test_xt_grid_shape() -> None:
    """Singh's grid is 12 (x) by 8 (y)."""
    assert XT_GRID.shape == (12, 8)
    assert N_X_BINS == 12
    assert N_Y_BINS == 8
    assert np.isfinite(XT_GRID).all()
    assert (XT_GRID >= 0).all()


def test_attacking_third_has_higher_xt_than_defensive_third() -> None:
    """Ball near the attacking goal should be worth more than near your own goal."""
    # Central channel, deep in attack
    near_attack = xt_for_ball(0.95, 0.0)
    # Central channel, deep in defense
    near_defense = xt_for_ball(-0.95, 0.0)
    assert near_attack > near_defense
    # Should also dominate a halfway-line position
    midfield = xt_for_ball(0.0, 0.0)
    assert near_attack > midfield


def test_edge_coordinates_dont_crash() -> None:
    """Out-of-bounds and exact-boundary positions return finite xT."""
    for x in (-1.0, 1.0, -1.5, 1.5, -1.0 + 1e-12, 1.0 - 1e-12):
        for y in (-1.0, 1.0, -1.5, 1.5):
            v = xt_for_ball(x, y)
            assert np.isfinite(v)
            assert v >= 0.0


def test_xt_per_frame_vectorized_matches_scalar() -> None:
    """Vectorized lookup should agree with the scalar version frame-by-frame."""
    rng = np.random.default_rng(0)
    n = 32
    frames = np.zeros((n, 23, 7), dtype=np.float32)
    frames[:, 22, 0] = rng.uniform(-1.2, 1.2, size=n).astype(np.float32)
    frames[:, 22, 1] = rng.uniform(-1.2, 1.2, size=n).astype(np.float32)

    vec = xt_per_frame(frames)
    assert vec.shape == (n,)
    for i in range(n):
        scalar = xt_for_ball(float(frames[i, 22, 0]), float(frames[i, 22, 1]))
        assert np.isclose(vec[i], scalar)


def test_xt_per_frame_rejects_wrong_shape() -> None:
    """A misshaped input should raise rather than silently produce garbage."""
    import pytest

    with pytest.raises(ValueError):
        xt_per_frame(np.zeros((10, 5, 7), dtype=np.float32))
