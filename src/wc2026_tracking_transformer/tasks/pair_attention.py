"""Pair-attention extraction as a ball-independent chemistry signal.

The argument: once a transformer is trained on a supervised tracking task
(any reasonable one — next-event-value, expected possession, pitch control,
xT-flow), pair attention weights between two outfield players quantify how
much each player conditions the model's representation of the other.
Aggregated over many frames, that's a chemistry signal that is

  - **ball-independent** (defined per frame regardless of who is on the ball),
  - **continuous** (not binned to pass events the way JOI90 / VAEP-chemistry are),
  - **role-aware** (the attention head specializes by role / line).

This is the *co-movement chemistry* milestone from the project README. The
output is the tracking-data complement to the event-based JOI90 metric in
the sibling ``wc2026-chemistry`` repo.

NOTE: Implementation is a SKELETON. No new trainable params live here.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from torch import Tensor


class PairAttentionHead:
    """Convert backbone attention weights into per-pair chemistry scores.

    Args:
        reduce_layers: How to combine attention across encoder layers.
            One of ``"mean"``, ``"last"``, ``"max"``. Default ``"mean"``.
        reduce_heads: How to combine attention across heads. One of
            ``"mean"``, ``"max"``. Default ``"mean"``.
        symmetrize: If True, average ``A[i, j]`` with ``A[j, i]`` so the
            chemistry score for pair ``(i, j)`` is order-independent.
    """

    def __init__(
        self,
        reduce_layers: str = "mean",
        reduce_heads: str = "mean",
        symmetrize: bool = True,
    ) -> None:
        self.reduce_layers = reduce_layers
        self.reduce_heads = reduce_heads
        self.symmetrize = symmetrize

    def __call__(self, attn_weights: "Tensor") -> "Tensor":  # noqa: F821
        """Reduce per-layer per-head attention to a single per-pair score.

        Args:
            attn_weights: ``(B, num_layers, num_heads, T, T)`` from
                :meth:`SoccerTrackingTransformer.attention_weights`.

        Returns:
            ``(B, T, T)`` symmetric (if requested) pair chemistry matrix.

        Raises:
            NotImplementedError: scaffolding only.
        """
        raise NotImplementedError(
            "PairAttentionHead.__call__ is a scaffold. Implementation: reduce over "
            "the layer and head dims per the configured strategy, then symmetrize."
        )
