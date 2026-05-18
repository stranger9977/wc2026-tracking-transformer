"""Frame batching utilities.

Converts streams of :class:`TrackingFrame` into model-ready tensors.
Soccer equivalent of Sumer's ``BDB2024_Dataset`` in ``src/datasets.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_PLAYERS_PER_FRAME,
    NUM_TOKENS_PER_FRAME,
    TrackingFrame,
)

N_FEATURES = len(FRAME_FEATURE_COLUMNS)


def frame_to_tensor(frame: TrackingFrame) -> np.ndarray:
    """Stack a frame's players + ball into a ``(23, 7)`` array.

    Order: 22 player slots first, then the ball token at index 22.
    Order within the player block is whatever the loader produced — the
    transformer is permutation-equivariant so this is OK.

    Args:
        frame: A normalized tracking frame.

    Returns:
        Float32 array of shape ``(NUM_TOKENS_PER_FRAME, N_FEATURES)``.
    """
    out = np.zeros((NUM_TOKENS_PER_FRAME, N_FEATURES), dtype=np.float32)
    players = np.asarray(frame.players, dtype=np.float32)
    n = min(players.shape[0], NUM_PLAYERS_PER_FRAME)
    out[:n] = players[:n]
    if frame.ball is not None:
        out[NUM_PLAYERS_PER_FRAME] = np.asarray(frame.ball, dtype=np.float32)
    return out


def batch_frames(frames: Sequence[TrackingFrame]) -> np.ndarray:
    """Stack N frames into a single ``(N, 23, 7)`` array.

    Args:
        frames: Sequence of normalized tracking frames.

    Returns:
        Float32 array of shape ``(len(frames), NUM_TOKENS_PER_FRAME, N_FEATURES)``.
    """
    if not frames:
        return np.zeros((0, NUM_TOKENS_PER_FRAME, N_FEATURES), dtype=np.float32)
    return np.stack([frame_to_tensor(f) for f in frames], axis=0)
