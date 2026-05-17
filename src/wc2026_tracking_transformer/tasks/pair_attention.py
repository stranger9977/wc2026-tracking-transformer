"""Pair-attention extraction as a ball-independent chemistry signal.

Once the transformer is trained on a supervised target, pair attention weights
between two outfield players quantify how much each player conditions the
model's representation of the other. Aggregated over many frames, that's a
chemistry signal that is:

  - **ball-independent** — defined per frame regardless of who is on the ball
  - **continuous** — not gated on event triggers the way JOI90 / VAEP-chemistry are
  - **role-aware** — attention heads tend to specialize by role / line

This is the *co-movement chemistry* milestone — the tracking-data complement
to the event-based JOI90 in the sibling ``wc2026-chemistry`` project.

No new trainable params live here; this is an analysis head.
"""

from __future__ import annotations

import torch
from torch import Tensor


class PairAttentionHead:
    """Reduce per-layer per-head attention to a single per-pair chemistry score.

    Args:
        reduce_layers: How to combine attention across encoder layers.
            One of ``"mean"`` (default), ``"last"``, ``"max"``.
        reduce_heads: How to combine attention across heads. One of
            ``"mean"`` (default), ``"max"``.
        symmetrize: If True, average ``A[i, j]`` with ``A[j, i]`` so the
            chemistry score for pair ``(i, j)`` is order-independent.
    """

    def __init__(
        self,
        reduce_layers: str = "mean",
        reduce_heads: str = "mean",
        symmetrize: bool = True,
    ) -> None:
        if reduce_layers not in {"mean", "last", "max"}:
            raise ValueError(f"reduce_layers must be mean/last/max, got {reduce_layers!r}")
        if reduce_heads not in {"mean", "max"}:
            raise ValueError(f"reduce_heads must be mean/max, got {reduce_heads!r}")
        self.reduce_layers = reduce_layers
        self.reduce_heads = reduce_heads
        self.symmetrize = symmetrize

    def __call__(self, attn_weights: Tensor) -> Tensor:
        """Apply the configured reduction.

        Args:
            attn_weights: ``(B, num_layers, num_heads, T, T)`` from
                :meth:`SoccerTrackingTransformer.encode_with_attention`.

        Returns:
            ``(B, T, T)`` per-pair chemistry matrix (symmetrized if requested).
        """
        # reduce heads (dim=2)
        if self.reduce_heads == "mean":
            x = attn_weights.mean(dim=2)
        else:
            x = attn_weights.max(dim=2).values  # type: ignore[union-attr]
        # x is now (B, num_layers, T, T); reduce layers (dim=1)
        if self.reduce_layers == "mean":
            x = x.mean(dim=1)
        elif self.reduce_layers == "last":
            x = x[:, -1]
        else:  # "max"
            x = x.max(dim=1).values  # type: ignore[union-attr]
        # x is now (B, T, T)
        if self.symmetrize:
            x = 0.5 * (x + x.transpose(-1, -2))
        return x
