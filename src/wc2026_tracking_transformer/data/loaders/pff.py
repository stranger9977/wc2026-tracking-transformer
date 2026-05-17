"""PFF FC 2022 World Cup loader, via kloppy.

This is the *tertiary / optional* data source for this project. Prefer DFL
(``loaders/dfl.py``) and SkillCorner (``loaders/skillcorner.py``); use PFF
only if you specifically need WC '22 data and have completed PFF's
registration step.

kloppy (https://kloppy.pysport.org) ships a first-class PFF loader, which
gives us format normalization (consistent pitch coordinates, period
handling, player IDs) and event/tracking alignment for free.

NOTE: Implementations here are SKELETONS.
"""

from collections.abc import Iterator
from pathlib import Path

from wc2026_tracking_transformer.data.schema import TrackingFrame


def load_pff_match(
    match_dir: Path,
    *,
    include_dead_ball: bool = False,
    sampling_rate_hz: float | None = None,
) -> Iterator[TrackingFrame]:
    """Load a single PFF match as a stream of normalized :class:`TrackingFrame` objects.

    Args:
        match_dir: Directory containing the PFF tracking + events + metadata
            bundle for a single match (under ``data/raw/pff_wc2022/``).
        include_dead_ball: If True, yield frames during stoppages.
        sampling_rate_hz: If set, downsample to this rate. PFF native is
            ~10Hz; ``None`` keeps native rate.

    Yields:
        :class:`TrackingFrame` instances in chronological order.

    Raises:
        NotImplementedError: scaffolding only.

    Implementation plan:
        1. ``kloppy.pff.load_tracking(...)`` + ``kloppy.pff.load_event(...)``
           against the match directory. Use ``Orientation.STATIC_HOME_AWAY``
           or similar to lock the attacking direction.
        2. Walk the kloppy ``TrackingDataset`` frame-by-frame.
        3. For each frame, identify the 22 outfield players, the ball, and
           the in-possession team (from the ``EventDataset``).
        4. Convert kloppy coordinates (meters, pitch-centered after
           orientation normalization) into the schema in
           :mod:`...data.schema`.
        5. Compute velocities from successive positions if kloppy doesn't
           expose them directly.
        6. Yield a :class:`TrackingFrame`.
    """
    raise NotImplementedError(
        "load_pff_match is a scaffold. See module docstring for the implementation plan."
    )


def list_pff_matches(root: Path) -> list[Path]:
    """Return the per-match directories under a PFF release root.

    Args:
        root: Path to ``data/raw/pff_wc2022/``.

    Returns:
        Sorted list of per-match directory paths.

    Raises:
        NotImplementedError: scaffolding only.
    """
    raise NotImplementedError(
        "list_pff_matches is a scaffold. Inspect the actual PFF release layout, "
        "then implement directory globbing here."
    )
