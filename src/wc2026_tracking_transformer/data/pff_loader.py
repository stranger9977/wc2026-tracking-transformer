"""PFF FC 2022 World Cup loader, via kloppy.

kloppy (https://kloppy.pysport.org) ships a first-class PFF loader. Using it
gives us format normalization (consistent pitch coordinates, period handling,
player IDs) and event/tracking alignment essentially for free.

This module wraps kloppy's loader and converts its output to the project's
own :class:`TrackingFrame` schema.

NOTE: Implementations here are SKELETONS. They define the public surface but
raise ``NotImplementedError`` so that downstream callers and tests can stub
them out.
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
        include_dead_ball: If True, yield frames during stoppages (ball out of
            play, fouls, etc.). Defaults to False — most tasks want active play
            only and dead-ball frames dilute the signal.
        sampling_rate_hz: If set, downsample to this rate. PFF native is ~10Hz,
            so 5Hz halves the frame count. ``None`` keeps native rate.

    Yields:
        :class:`TrackingFrame` instances in chronological order.

    Raises:
        NotImplementedError: scaffolding only.

    Implementation plan:
        1. Call ``kloppy.pff.load_tracking(...)`` and ``kloppy.pff.load_event(...)``
           against the match directory. Use ``Orientation.STATIC_HOME_AWAY`` or
           similar to lock the attacking direction; see kloppy docs.
        2. Walk the kloppy ``TrackingDataset`` frame-by-frame.
        3. For each frame, identify the 22 outfield players + 2 GKs, the ball,
           and the in-possession team (from the corresponding ``EventDataset``).
        4. Convert kloppy coordinates (meters, pitch-centered after orientation
           normalization) into the schema in :mod:`...data.schema`.
        5. Compute velocities from successive positions (kloppy doesn't always
           expose them directly — see ``compute_velocities`` helper to be added).
        6. Yield a :class:`TrackingFrame`.
    """
    raise NotImplementedError(
        "load_pff_match is a scaffold. See module docstring for the implementation plan."
    )


def list_pff_matches(root: Path) -> list[Path]:
    """Return the per-match directories under a PFF release root.

    The exact directory layout depends on how PFF zips the release; this
    helper centralizes that knowledge so the loader stays decoupled.

    Args:
        root: Path to ``data/raw/pff_wc2022/`` (or wherever the release lives).

    Returns:
        Sorted list of per-match directory paths.

    Raises:
        NotImplementedError: scaffolding only.
    """
    raise NotImplementedError(
        "list_pff_matches is a scaffold. Inspect the actual PFF release layout, "
        "then implement directory globbing here."
    )
