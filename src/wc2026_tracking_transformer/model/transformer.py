"""Soccer tracking transformer backbone.

Architectural credit: SumerSports/SportsTrackingTransformer, specifically
``src/models.py::SportsTransformer``. We reproduce the *structure* of their
encoder (batch-norm over features, linear embed, stacked TransformerEncoder
layers) but keep the head pluggable so we can attach different tasks
(co-movement chemistry, two-head P(score)/P(concede), off-ball pattern
quantifiers).

Paper: "Attention Is All You Need, for Sports Tracking Data" (Ranasaria &
Vabishchevich, CMSAC 2024).

LICENSING NOTE: the upstream Sumer repo has no LICENSE file at the time of
writing. Until that is resolved, this module is a clean-room implementation
of the architecture described in the paper, not a copy of Sumer's code.

NOTE: Implementation is a SKELETON.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from torch import Tensor
    from torch import nn as _nn  # noqa: F401


class SoccerTrackingTransformer:
    """Permutation-equivariant encoder over per-frame player + ball tokens.

    Input shape:  ``(batch, num_tokens, feature_len)``
                  with ``num_tokens = NUM_PLAYERS_PER_FRAME + 1`` (ball).
    Output shape: ``(batch, num_tokens, model_dim)`` — per-token embeddings.

    Pooling and task heads are attached separately (see
    :mod:`wc2026_tracking_transformer.tasks`). This separation is the main
    structural change from Sumer's monolithic ``SportsTransformer`` class.

    Args:
        feature_len: Per-token input feature count
            (== ``len(FRAME_FEATURE_COLUMNS)`` for the default schema).
        model_dim: Internal embedding dimension. Sumer's grid sweeps
            {32, 128, 512}; their best NFL model was 512.
        num_layers: Number of stacked transformer encoder layers.
            Sumer's grid sweeps {1, 2, 4, 8}; their best NFL model was 2.
        dropout: Dropout rate applied inside the encoder.
    """

    def __init__(
        self,
        feature_len: int,
        model_dim: int = 128,
        num_layers: int = 2,
        dropout: float = 0.3,
    ) -> None:
        self.feature_len = feature_len
        self.model_dim = model_dim
        self.num_layers = num_layers
        self.dropout = dropout
        # TODO: instantiate
        #   - feature_norm: nn.BatchNorm1d(feature_len)
        #   - feature_embed: nn.Sequential(Linear -> ReLU -> LayerNorm -> Dropout)
        #   - encoder: nn.TransformerEncoder(TransformerEncoderLayer(..., batch_first=True), num_layers)
        # See `paper/Sumer Sports Transformer Simple Arch.jpg` in the Sumer repo for the diagram.

    def forward(self, x: "Tensor") -> "Tensor":  # noqa: F821
        """Encode a batch of frames to per-token contextual embeddings.

        Args:
            x: ``(B, T, F)`` float tensor.

        Returns:
            ``(B, T, model_dim)`` float tensor.

        Raises:
            NotImplementedError: scaffolding only.
        """
        raise NotImplementedError(
            "SoccerTrackingTransformer.forward is a scaffold. See docstring TODOs."
        )

    def attention_weights(self, x: "Tensor") -> "Tensor":  # noqa: F821
        """Return per-layer per-head pair attention weights for analysis.

        Critical for the co-movement chemistry head — pair attention between
        two player tokens is the chemistry signal.

        Args:
            x: ``(B, T, F)`` float tensor.

        Returns:
            ``(B, num_layers, num_heads, T, T)`` float tensor of softmaxed
            attention weights.

        Raises:
            NotImplementedError: scaffolding only.
        """
        raise NotImplementedError(
            "attention_weights is a scaffold. Implement by registering forward hooks "
            "on each TransformerEncoderLayer.self_attn or by re-running attention "
            "with `need_weights=True`."
        )
