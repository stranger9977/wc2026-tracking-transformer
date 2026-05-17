"""Frame batching utilities.

Converts streams of :class:`TrackingFrame` into PyTorch tensors / DataLoader-
compatible batches. This is the soccer equivalent of Sumer's
``BDB2024_Dataset`` (``src/datasets.py`` in the upstream repo).

NOTE: Implementations here are SKELETONS.
"""

from collections.abc import Sequence

import numpy as np

from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_TOKENS_PER_FRAME,
    TrackingFrame,
)


def frame_to_tensor(frame: TrackingFrame) -> np.ndarray:
    """Stack a :class:`TrackingFrame` into a ``(NUM_TOKENS_PER_FRAME, F)`` array.

    The output is the per-frame input to the transformer: an unordered set of
    token vectors. Order within the array carries no semantic meaning — that's
    the architectural argument we're inheriting from Sumer.

    Args:
        frame: A normalized tracking frame.

    Returns:
        Float32 numpy array of shape ``(NUM_TOKENS_PER_FRAME, len(FRAME_FEATURE_COLUMNS))``.

    Raises:
        NotImplementedError: scaffolding only.
    """
    raise NotImplementedError(
        f"frame_to_tensor must emit shape ({NUM_TOKENS_PER_FRAME}, {len(FRAME_FEATURE_COLUMNS)})."
    )


def batch_frames(frames: Sequence[TrackingFrame]) -> np.ndarray:
    """Stack N frames into a single ``(N, NUM_TOKENS_PER_FRAME, F)`` array.

    Args:
        frames: A sequence of normalized tracking frames.

    Returns:
        Float32 numpy array.

    Raises:
        NotImplementedError: scaffolding only.
    """
    raise NotImplementedError("batch_frames is a scaffold.")
