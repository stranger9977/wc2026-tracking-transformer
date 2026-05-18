"""Baselines for comparison against the tracking transformer.

Each baseline operates on the same per-frame inputs (or a strict subset)
that the transformer sees, so head-to-head AUC numbers are apples-to-apples.
"""

from wc2026_tracking_transformer.baselines.vaep import (
    VAEPModel,
    events_to_actions,
    label_actions,
    predict_vaep,
    train_vaep,
)
from wc2026_tracking_transformer.baselines.xt import (
    XT_GRID,
    xt_for_ball,
    xt_per_frame,
)

__all__ = [
    "VAEPModel",
    "XT_GRID",
    "events_to_actions",
    "label_actions",
    "predict_vaep",
    "train_vaep",
    "xt_for_ball",
    "xt_per_frame",
]
