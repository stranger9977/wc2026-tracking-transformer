"""Data ingest, schema, and frame-batching for soccer tracking.

Primary entry points:

  * :func:`load_match` — unified dispatch by source (dfl/skillcorner/metrica/pff)
  * :func:`list_matches` — enumerate available matches per source
  * :class:`SoccerTrackingDataModule` — Lightning DataModule (real + synthetic)
"""

from wc2026_tracking_transformer.data.datamodule import (
    SoccerTrackingDataModule,
    SyntheticFrameDataset,
)
from wc2026_tracking_transformer.data.loaders import (
    list_dfl_matches,
    list_metrica_matches,
    list_pff_matches,
    list_skillcorner_matches,
    load_dfl_match,
    load_metrica_match,
    load_pff_match,
    load_skillcorner_match,
)
from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_PLAYERS_PER_FRAME,
    NUM_TOKENS_PER_FRAME,
    TrackingFrame,
)
from wc2026_tracking_transformer.data.tracking_loader import (
    DEFAULT_ROOTS,
    list_matches,
    load_match,
)

__all__ = [
    "DEFAULT_ROOTS",
    "FRAME_FEATURE_COLUMNS",
    "NUM_PLAYERS_PER_FRAME",
    "NUM_TOKENS_PER_FRAME",
    "SoccerTrackingDataModule",
    "SyntheticFrameDataset",
    "TrackingFrame",
    "list_dfl_matches",
    "list_matches",
    "list_metrica_matches",
    "list_pff_matches",
    "list_skillcorner_matches",
    "load_dfl_match",
    "load_match",
    "load_metrica_match",
    "load_pff_match",
    "load_skillcorner_match",
]
