"""Data ingest, schema, and frame-batching for soccer tracking.

The public entry point is :func:`load_pff_match`, which wraps kloppy's PFF
loader and returns a :class:`TrackingFrameDataset` of normalized frames
suitable for feeding into a transformer.
"""

from wc2026_tracking_transformer.data.pff_loader import load_pff_match
from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_PLAYERS_PER_FRAME,
    TrackingFrame,
)

__all__ = [
    "FRAME_FEATURE_COLUMNS",
    "NUM_PLAYERS_PER_FRAME",
    "TrackingFrame",
    "load_pff_match",
]
