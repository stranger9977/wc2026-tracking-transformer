"""End-to-end smoke tests for the Metrica loader.

Each test pulls a small slice of real data from Metrica's open-data GitHub
repo via kloppy. Gated on network availability so a CI box without internet
won't fail catastrophically.
"""

import socket

import numpy as np
import pytest


def _has_internet(host: str = "github.com", port: int = 443, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


requires_net = pytest.mark.skipif(
    not _has_internet(), reason="Metrica open-data fetch needs network access"
)


@requires_net
def test_load_metrica_one_match() -> None:
    """Loader returns frames with the right schema and reasonable values."""
    from wc2026_tracking_transformer.data.batching import batch_frames
    from wc2026_tracking_transformer.data.loaders.metrica import load_metrica_match

    # Stride 25 = 1 Hz → ~100 frames per ~100 seconds of play, fast enough for CI.
    frames = list(load_metrica_match("1", sampling_stride=25))
    assert len(frames) > 100, f"too few frames: {len(frames)}"

    f0 = frames[0]
    assert f0.match_id == "metrica_1"
    assert f0.players.shape == (22, 7)
    assert f0.ball.shape == (7,)

    # Stack and sanity-check feature ranges.
    arr = batch_frames(frames[:50])
    assert arr.shape == (50, 23, 7)
    x_norm = arr[:, :, 0]
    y_norm = arr[:, :, 1]
    assert -1.05 <= float(x_norm.min()) and float(x_norm.max()) <= 1.05
    assert -1.05 <= float(y_norm.min()) and float(y_norm.max()) <= 1.05

    # Velocities are clamped.
    v = arr[:, :, 2:4]
    assert float(np.abs(v).max()) <= 25.0 + 1e-3

    # Flags are well-formed.
    gk_per_frame = arr[:, :22, 5].sum(axis=1)
    assert (gk_per_frame == 2).all(), f"expected 2 GKs per frame, got {gk_per_frame[:5]}"
    poss_per_frame = arr[:, :22, 6].sum(axis=1)
    assert (poss_per_frame == 1).all(), f"expected 1 ball-owner per frame"
    # 11-vs-11 attacking-side split (ball is 0)
    pos = (arr[:, :22, 4] == 1.0).sum(axis=1)
    neg = (arr[:, :22, 4] == -1.0).sum(axis=1)
    assert (pos == 11).all() and (neg == 11).all()


@requires_net
def test_metrica_datamodule_yields_real_batches() -> None:
    """The DataModule wires Metrica end-to-end and produces real labels."""
    from wc2026_tracking_transformer.data import SoccerTrackingDataModule

    dm = SoccerTrackingDataModule(
        source="metrica",
        batch_size=16,
        metrica_sampling_stride=25,  # 1 Hz for CI speed
        metrica_k_seconds=5.0,
    )
    dm.setup()
    x, y = next(iter(dm.train_dataloader()))
    assert x.shape == (16, 23, 7)
    assert y.shape == (16, 2)
    # Phase-1 labels are derived from tracking and should be non-degenerate
    # across the full dataset (different from synthetic 5% Bernoulli).
    train_labels = dm.train_ds.labels
    p_score = float(train_labels[:, 0].mean())
    p_concede = float(train_labels[:, 1].mean())
    assert 0.05 < p_score < 0.95, f"phase-1 P(score) rate looks degenerate: {p_score}"
    assert 0.05 < p_concede < 0.95, f"phase-1 P(concede) rate looks degenerate: {p_concede}"
