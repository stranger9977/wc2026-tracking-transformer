"""Task-specific heads that sit on top of the shared transformer backbone.

Heads:
    * :mod:`.next_event_value`   — supervised P(score|frame), P(concede|frame).
      The two-head soccer analogue of Sumer's single tackle-location head.
    * :mod:`.pair_attention`     — extract pair-attention weights as a
      ball-independent chemistry signal. No new parameters; this is an
      analysis head, not a training target.
"""

from wc2026_tracking_transformer.tasks.next_event_value import NextEventValueHead
from wc2026_tracking_transformer.tasks.pair_attention import PairAttentionHead

__all__ = ["NextEventValueHead", "PairAttentionHead"]
