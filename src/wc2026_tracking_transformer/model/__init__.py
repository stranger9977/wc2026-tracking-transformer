"""Transformer backbone + LightningModule for soccer tracking.

The backbone (:class:`SoccerTrackingTransformer`) is adapted from
SumerSports/SportsTrackingTransformer, used with attribution. See
``model/transformer.py`` for licensing details.

Paper: Ranasaria, U. & Vabishchevich, P. "Attention Is All You Need, for Sports
Tracking Data." CMSAC Workshop, 2024.
"""

from wc2026_tracking_transformer.model.lit_model import NextEventValueLitModule
from wc2026_tracking_transformer.model.transformer import SoccerTrackingTransformer

__all__ = ["NextEventValueLitModule", "SoccerTrackingTransformer"]
