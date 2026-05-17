"""SkillCorner Open Data loader (SECONDARY).

Dataset: SkillCorner Open Data, A-League sample.
  * 10 A-League matches.
  * Broadcast tracking at 10 fps (so partial pitch coverage — only what's
    on-screen). This is *coarser* than DFL's 25 Hz full-optical, but it's
    closer in nature to PFF's broadcast-tracking style and useful as a
    second source.
  * **License: MIT** — fully open.
  * Hosted on GitHub: <https://github.com/SkillCorner/opendata>

kloppy has a first-class SkillCorner loader.

NOTE: Implementations here are SKELETONS.
"""

from collections.abc import Iterator
from pathlib import Path

from wc2026_tracking_transformer.data.schema import TrackingFrame


def load_skillcorner_match(
    match_dir: Path,
    *,
    include_dead_ball: bool = False,
    sampling_rate_hz: float | None = None,
) -> Iterator[TrackingFrame]:
    """Load a single SkillCorner match as a stream of :class:`TrackingFrame`.

    Args:
        match_dir: Directory containing ``structured_data.json`` and
            ``match_data.json`` for one match, under
            ``data/raw/skillcorner_aleague/``.
        include_dead_ball: If True, yield frames during stoppages.
        sampling_rate_hz: If set, downsample from native 10 Hz; ``None``
            keeps native rate.

    Yields:
        :class:`TrackingFrame` instances in chronological order.

    Raises:
        NotImplementedError: scaffolding only.

    Implementation plan:
        1. ``dataset = kloppy.skillcorner.load(
               meta_data=match_dir / "match_data.json",
               raw_data=match_dir / "structured_data.json",
               coordinates="kloppy",
               only_alive=not include_dead_ball,
           )``
        2. Walk frames. **Important**: SkillCorner broadcast frames have
           variable player counts (only on-screen players are tracked).
           For our 22-player schema, we'll need to either:
             a. Pad missing players with NaN tokens + an attention mask, or
             b. Skip frames with fewer than N visible players.
           Default to (a); see ``data/schema.py`` for the padding contract
           we'll define when implementing.
        3. Convert and yield as :class:`TrackingFrame`.
    """
    raise NotImplementedError(
        "load_skillcorner_match is a scaffold. See module docstring for the implementation plan."
    )


def list_skillcorner_matches(root: Path) -> list[Path]:
    """Return per-match directories under a SkillCorner Open Data root.

    Args:
        root: Path to ``data/raw/skillcorner_aleague/``.

    Returns:
        Sorted list of per-match directory paths.

    Raises:
        NotImplementedError: scaffolding only.
    """
    raise NotImplementedError(
        "list_skillcorner_matches is a scaffold. See "
        "https://github.com/SkillCorner/opendata for the canonical layout."
    )
