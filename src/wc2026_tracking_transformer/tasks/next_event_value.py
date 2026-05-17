"""Two-head P(score) / P(concede) prediction.

Goal: train the shared transformer backbone with a unified supervised target —
the probability that the next on-ball outcome within the next K seconds is a
goal scored by the in-possession team, or a goal conceded.

This is the *unified two-head model* milestone from the project README. It's
the soccer analogue of Sumer's tackle-location regressor and lets per-player
decomposition fall out of attention weights / gradient attribution.
"""

from __future__ import annotations

from torch import Tensor, nn


class NextEventValueHead(nn.Module):
    """Pool encoder outputs and predict (P(score), P(concede)) logits.

    Args:
        model_dim: Encoder embedding dimension (must match the backbone).
        pool: Pooling strategy across tokens.
            ``"mean"`` — average all 23 tokens (default; mirrors Sumer).
            ``"ball"`` — read out the ball token (token 0 by convention).
        hidden: MLP hidden dim.
        dropout: Dropout rate inside the head.
    """

    def __init__(
        self,
        model_dim: int,
        pool: str = "mean",
        hidden: int = 128,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if pool not in {"mean", "ball"}:
            raise ValueError(f"pool must be 'mean' or 'ball', got {pool!r}")
        self.model_dim = model_dim
        self.pool = pool
        self.head = nn.Sequential(
            nn.Linear(model_dim, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, 2),  # P(score) logit, P(concede) logit
        )

    def forward(self, encoded: Tensor) -> Tensor:
        """Pool + project to two-logit output.

        Args:
            encoded: ``(B, T, model_dim)`` output from the backbone.

        Returns:
            ``(B, 2)`` logits. Apply ``sigmoid`` for per-class probabilities.
            P(score) and P(concede) are NOT mutually exclusive (a 10s window
            can contain both), so use BCE-with-logits, not softmax.
        """
        if self.pool == "mean":
            pooled = encoded.mean(dim=1)
        else:  # "ball"
            pooled = encoded[:, 0, :]
        return self.head(pooled)
