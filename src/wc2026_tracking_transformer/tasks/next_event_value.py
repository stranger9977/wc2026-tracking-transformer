"""Two-head P(score) / P(concede) prediction.

Goal: train the shared transformer backbone with a unified supervised target —
the probability that the next on-ball outcome within the next K seconds is a
goal scored by the in-possession team, or a goal conceded.

This is the *unified two-head model* milestone from the project README. It's
the soccer-friendly replacement for Sumer's tackle-location regression task,
and lets per-player decomposition fall out of attention weights / gradient
attribution.

NOTE: Implementation is a SKELETON.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from torch import Tensor


class NextEventValueHead:
    """Pool encoder outputs and predict (P(score), P(concede)).

    Args:
        model_dim: Encoder embedding dimension (must match the backbone).
        pool: Pooling strategy across tokens. ``"mean"`` averages all 23 tokens;
            ``"ball"`` reads out only the ball token; ``"attn"`` learns a
            single-query attention pool. Default ``"mean"`` mirrors Sumer's
            ``AdaptiveAvgPool1d``.
        horizon_seconds: How far ahead to look for the next goal event when
            constructing labels. 10s is a reasonable default; explore.
    """

    def __init__(
        self,
        model_dim: int,
        pool: str = "mean",
        horizon_seconds: float = 10.0,
    ) -> None:
        self.model_dim = model_dim
        self.pool = pool
        self.horizon_seconds = horizon_seconds
        # TODO: build nn.Sequential(Linear -> ReLU -> Dropout -> Linear -> 2 logits)

    def forward(self, encoded: "Tensor") -> "Tensor":  # noqa: F821
        """Pool + project to two-logit output.

        Args:
            encoded: ``(B, T, model_dim)`` output from the backbone.

        Returns:
            ``(B, 2)`` logits — apply ``sigmoid`` for per-class probabilities.
            Note that P(score) and P(concede) are NOT mutually exclusive (a
            10-second window can contain both), so use BCE not softmax.

        Raises:
            NotImplementedError: scaffolding only.
        """
        raise NotImplementedError(
            "NextEventValueHead.forward is a scaffold. See docstring TODOs."
        )
