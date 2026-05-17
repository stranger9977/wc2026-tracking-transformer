"""DFL / Bassek 2025 loader (PRIMARY data source).

Dataset: Bassek et al., "An integrated dataset of synchronized tracking and
event data for elite football matches", *Scientific Data* (2025).

  * 7 matches: 2 Bundesliga + 5 2. Bundesliga, 2022/23 season.
  * 25 Hz optical tracking (full pitch, all players, ball).
  * Synchronized events.
  * **License: CC-BY 4.0** — fully open. Cite the paper if you use it.
  * Hosted on figshare: <https://www.nature.com/articles/s41597-025-04505-y>
    follow the figshare link from the paper for the tarball.

The data is in **Sportec / DFL XML format**. kloppy has a native loader for
Sportec tracking + events; this module wraps it.

NOTE: Implementations here are SKELETONS.
"""

from collections.abc import Iterator
from pathlib import Path

from wc2026_tracking_transformer.data.schema import TrackingFrame


def load_dfl_match(
    match_dir: Path,
    *,
    include_dead_ball: bool = False,
    sampling_rate_hz: float | None = None,
) -> Iterator[TrackingFrame]:
    """Load a single DFL match as a stream of :class:`TrackingFrame` objects.

    Args:
        match_dir: Directory containing the per-match Sportec XML bundle
            (positions, events, meta). Typically named by DFL match ID under
            ``data/raw/dfl_bassek/``.
        include_dead_ball: If True, yield frames during stoppages.
        sampling_rate_hz: If set, downsample from native 25 Hz to this rate
            (5 / 10 Hz are reasonable choices for trading data volume for
            training speed). ``None`` keeps native 25 Hz.

    Yields:
        :class:`TrackingFrame` instances in chronological order.

    Raises:
        NotImplementedError: scaffolding only.

    Implementation plan:
        1. Discover the trio of XML files in ``match_dir``:
           ``positions.xml`` (tracking), ``events.xml`` (events),
           ``meta.xml`` (rosters + match metadata). Exact filenames depend
           on how figshare ships the release — adapt the glob.
        2. ``dataset = kloppy.sportec.load_tracking(
                meta_data=..., raw_data=...,
                coordinates="kloppy",  # pitch-centered, meters
                only_alive=not include_dead_ball,
                sample_rate=sampling_rate_hz,
           )``
        3. Load events with ``kloppy.sportec.load_event(...)`` and join on
           the kloppy frame id for the in-possession team.
        4. Walk frames; for each, pull the 22 player records + ball, then
           emit a :class:`TrackingFrame` per the schema in
           :mod:`...data.schema`.
        5. kloppy frames expose ``Frame.players_coordinates`` and
           ``Frame.ball_coordinates`` (or ``ball_state`` for possession).
           Velocities sometimes need finite differencing — see
           ``compute_velocities`` helper to be added.
    """
    raise NotImplementedError(
        "load_dfl_match is a scaffold. See module docstring for the implementation plan."
    )


def list_dfl_matches(root: Path) -> list[Path]:
    """Return the per-match directories under a DFL release root.

    Args:
        root: Path to ``data/raw/dfl_bassek/``.

    Returns:
        Sorted list of per-match directory paths. The Bassek release ships
        7 matches; expect 7 returned paths once data is in place.

    Raises:
        NotImplementedError: scaffolding only.
    """
    raise NotImplementedError(
        "list_dfl_matches is a scaffold. Confirm figshare layout after download, "
        "then implement directory globbing."
    )
