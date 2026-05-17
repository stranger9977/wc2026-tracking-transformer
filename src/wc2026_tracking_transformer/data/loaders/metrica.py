"""Metrica Sports sample data loader (DEV FIXTURE).

Dataset: Metrica Sports anonymized sample data.
  * 3 matches (Sample_Game_1, _2, _3). Samples 1 & 2 are 25 Hz full-pitch
    tracking + events. Sample 3 is a different format (anonymized event-only).
  * No formal license file in the repo, but the data is widely used in
    tutorials and is published as "open sample data for educational use".
    Treat as fine for development; flag if shipping anything derivative.
  * Hosted on GitHub: <https://github.com/metrica-sports/sample-data>

**Use case here**: dev fixture for the loader / model. Small enough to
iterate on a laptop CPU. The first real sanity-train run uses Metrica.

kloppy has a native Metrica loader.

NOTE: Implementations here are SKELETONS.
"""

from collections.abc import Iterator
from pathlib import Path

from wc2026_tracking_transformer.data.schema import TrackingFrame


def load_metrica_match(
    match_dir: Path,
    *,
    include_dead_ball: bool = False,
    sampling_rate_hz: float | None = None,
) -> Iterator[TrackingFrame]:
    """Load a single Metrica match as a stream of :class:`TrackingFrame`.

    Args:
        match_dir: Directory containing the Metrica CSV trio for one match
            (``Sample_Game_N_RawTrackingData_Home_Team.csv``,
            ``Sample_Game_N_RawTrackingData_Away_Team.csv``,
            ``Sample_Game_N_RawEventsData.csv``).
        include_dead_ball: If True, yield frames during stoppages.
        sampling_rate_hz: If set, downsample from native 25 Hz.

    Yields:
        :class:`TrackingFrame` instances in chronological order.

    Raises:
        NotImplementedError: scaffolding only.

    Implementation plan:
        1. ``dataset = kloppy.metrica.load_tracking_csv(
               home_data=..., away_data=..., meta_data=...,
               coordinates="kloppy",
           )``
        2. Load events via ``kloppy.metrica.load_event(...)`` and join.
        3. Walk frames; emit :class:`TrackingFrame`.

    Note:
        Metrica Sample 3 is an *event-only* release in a different format —
        this loader handles Samples 1 and 2 only.
    """
    raise NotImplementedError(
        "load_metrica_match is a scaffold. See module docstring for the implementation plan."
    )


def list_metrica_matches(root: Path) -> list[Path]:
    """Return per-match directories under a Metrica sample-data root.

    Args:
        root: Path to ``data/raw/metrica/``.

    Returns:
        Sorted list of per-match directory paths. Expect 2 (Sample_Game_1
        and Sample_Game_2) — Sample_Game_3 is event-only and is excluded.

    Raises:
        NotImplementedError: scaffolding only.
    """
    raise NotImplementedError(
        "list_metrica_matches is a scaffold. See "
        "https://github.com/metrica-sports/sample-data for the canonical layout."
    )
