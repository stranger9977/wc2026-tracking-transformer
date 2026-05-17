"""Soccer tracking transformer backbone.

Adapted from SumerSports/SportsTrackingTransformer (used with permission from
SumerSports — they're open to community reuse of their open-source code).
Original: https://github.com/SumerSports/SportsTrackingTransformer
Paper: "Attention Is All You Need, for Sports Tracking Data" (CMSAC 2024).

The encoder structure (BatchNorm over features, linear embed, stacked
TransformerEncoder layers, mean-pool readout) mirrors Sumer's `SportsTransformer`.
The soccer-specific bits are: 22 player tokens + 1 ball token, soccer feature
schema (see `schema.py`), and a pluggable head (vs. Sumer's fused tackle-location
regressor).
"""

from __future__ import annotations

import torch
from torch import Tensor, nn


class SoccerTrackingTransformer(nn.Module):
    """Permutation-equivariant encoder over per-frame player + ball tokens.

    Input shape:  ``(batch, num_tokens, feature_len)``
                  with ``num_tokens = NUM_PLAYERS_PER_FRAME + 1`` (ball).
    Output shape: ``(batch, num_tokens, model_dim)`` per-token embeddings.

    Heads are attached separately (see :mod:`...tasks`) so the same backbone
    can drive next-event-value training or pair-attention chemistry extraction.
    """

    def __init__(
        self,
        feature_len: int = 7,
        model_dim: int = 128,
        num_heads: int = 4,
        num_layers: int = 2,
        dropout: float = 0.1,
        ff_multiplier: int = 4,
    ) -> None:
        super().__init__()
        self.feature_len = feature_len
        self.model_dim = model_dim
        self.num_heads = num_heads
        self.num_layers = num_layers
        self.dropout_p = dropout

        # BatchNorm over the feature dim; applied per-token (we reshape).
        self.feature_norm = nn.BatchNorm1d(feature_len)
        self.feature_embed = nn.Sequential(
            nn.Linear(feature_len, model_dim),
            nn.ReLU(),
            nn.LayerNorm(model_dim),
            nn.Dropout(dropout),
        )
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=model_dim,
            nhead=num_heads,
            dim_feedforward=model_dim * ff_multiplier,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

    def forward(self, x: Tensor) -> Tensor:
        """Encode a batch of frames to per-token contextual embeddings.

        Args:
            x: ``(B, T, F)`` float tensor.

        Returns:
            ``(B, T, model_dim)`` float tensor.
        """
        b, t, f = x.shape
        # BatchNorm1d expects (N, F); reshape (B, T, F) -> (B*T, F) -> back.
        x = self.feature_norm(x.reshape(b * t, f)).reshape(b, t, f)
        x = self.feature_embed(x)  # (B, T, model_dim)
        x = self.encoder(x)
        return x

    def encode_with_attention(self, x: Tensor) -> tuple[Tensor, Tensor]:
        """Run forward and capture per-layer per-head attention weights.

        Manually steps through encoder layers with ``need_weights=True`` so we
        can extract pair attention for the co-movement chemistry head.

        Args:
            x: ``(B, T, F)`` float tensor.

        Returns:
            Tuple of (encoded, attn_weights):
                encoded: ``(B, T, model_dim)``
                attn_weights: ``(B, num_layers, num_heads, T, T)``.
        """
        b, t, f = x.shape
        h = self.feature_norm(x.reshape(b * t, f)).reshape(b, t, f)
        h = self.feature_embed(h)
        attns = []
        for layer in self.encoder.layers:
            # norm_first=True path: x = x + sa(norm1(x)); x = x + ffn(norm2(x))
            normed = layer.norm1(h)
            sa_out, attn = layer.self_attn(
                normed, normed, normed,
                need_weights=True,
                average_attn_weights=False,
            )
            h = h + layer.dropout1(sa_out)
            ffn_in = layer.norm2(h)
            ffn_out = layer.linear2(
                layer.dropout(layer.activation(layer.linear1(ffn_in)))
            )
            h = h + layer.dropout2(ffn_out)
            attns.append(attn)  # (B, num_heads, T, T)
        attn_weights = torch.stack(attns, dim=1)  # (B, num_layers, num_heads, T, T)
        return h, attn_weights
