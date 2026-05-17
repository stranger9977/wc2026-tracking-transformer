"""Transformer backbone + soccer-specific token embedding.

The backbone is intentionally a faithful port of Sumer's :class:`SportsTransformer`
from ``src/models.py`` (https://github.com/SumerSports/SportsTrackingTransformer).
That class is small and architecturally clean — input norm, linear embed,
``nn.TransformerEncoder`` stack, optional pool, task head. We replicate the
shape but keep our own code so the soccer-specific token spec and prediction
heads live cleanly together.

LICENSING NOTE: the upstream Sumer repo does not currently ship a LICENSE
file. **Verify the licensing situation with SumerSports before copying any
code wholesale from their repository.** Architectural ideas (the unordered-
token formulation, the encoder-pool-head structure) are not themselves
copyrightable, but specific code is. Until clarified, treat any code we
write here as our own implementation of the *idea*, citing the paper:

    Ranasaria, U. & Vabishchevich, P. "Attention Is All You Need, for Sports
    Tracking Data." CMSAC Workshop, 2024.
"""

from wc2026_tracking_transformer.model.transformer import SoccerTrackingTransformer

__all__ = ["SoccerTrackingTransformer"]
