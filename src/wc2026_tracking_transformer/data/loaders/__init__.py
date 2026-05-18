"""Per-source tracking-data loaders.

All loaders return the same normalized :class:`TrackingFrame` schema (see
:mod:`...data.schema`). Use :func:`...data.tracking_loader.load_match` for
a unified dispatch by source name.

Sources (in priority order):
    * :mod:`.dfl`         — Bassek 2025, CC-BY 4.0, 25 Hz full optical (PRIMARY)
    * :mod:`.skillcorner` — SkillCorner Open Data, MIT, 10 Hz broadcast
    * :mod:`.metrica`     — Metrica sample, dev fixture, 25 Hz
    * :mod:`.pff`         — PFF FC WC '22, registration-gated (OPTIONAL)
"""

from wc2026_tracking_transformer.data.loaders.dfl import (
    list_dfl_matches,
    load_dfl_events,
    load_dfl_match,
)
from wc2026_tracking_transformer.data.loaders.metrica import (
    list_metrica_matches,
    load_metrica_match,
)
from wc2026_tracking_transformer.data.loaders.pff import list_pff_matches, load_pff_match
from wc2026_tracking_transformer.data.loaders.skillcorner import (
    list_skillcorner_matches,
    load_skillcorner_match,
)

__all__ = [
    "list_dfl_matches",
    "list_metrica_matches",
    "list_pff_matches",
    "list_skillcorner_matches",
    "load_dfl_events",
    "load_dfl_match",
    "load_metrica_match",
    "load_pff_match",
    "load_skillcorner_match",
]
