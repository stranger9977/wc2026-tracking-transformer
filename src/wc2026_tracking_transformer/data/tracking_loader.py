"""Unified dispatcher across per-source tracking loaders.

Use :func:`load_match` to load a single match in the normalized
:class:`TrackingFrame` schema regardless of provider, and
:func:`list_matches` to enumerate what's available locally.

Sources (priority order):

  * ``"dfl"``         — Bassek 2025, CC-BY 4.0 (PRIMARY)
  * ``"skillcorner"`` — SkillCorner Open Data, MIT
  * ``"metrica"``     — Metrica sample (dev fixture)
  * ``"pff"``         — PFF FC WC '22, registration-gated (OPTIONAL)
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Literal

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
from wc2026_tracking_transformer.data.schema import TrackingFrame

Source = Literal["dfl", "skillcorner", "metrica", "pff"]

_LOAD = {
    "dfl": load_dfl_match,
    "skillcorner": load_skillcorner_match,
    "metrica": load_metrica_match,
    "pff": load_pff_match,
}
_LIST = {
    "dfl": list_dfl_matches,
    "skillcorner": list_skillcorner_matches,
    "metrica": list_metrica_matches,
    "pff": list_pff_matches,
}

DEFAULT_ROOTS: dict[str, Path] = {
    "dfl": Path("data/raw/dfl_bassek"),
    "skillcorner": Path("data/raw/skillcorner_aleague"),
    "metrica": Path("data/raw/metrica"),
    "pff": Path("data/raw/pff_wc2022"),
}


def load_match(source: Source, match_path: Path, **kwargs: object) -> Iterator[TrackingFrame]:
    """Load a single match from any supported source.

    Args:
        source: One of ``"dfl"``, ``"skillcorner"``, ``"metrica"``, ``"pff"``.
        match_path: Per-match directory or file appropriate to the source.
            Use the paths returned by :func:`list_matches`.
        **kwargs: Passed through to the per-source loader.

    Yields:
        :class:`TrackingFrame` objects in chronological order.

    Raises:
        ValueError: If ``source`` is unknown.
    """
    if source not in _LOAD:
        raise ValueError(f"Unknown source {source!r}. Pick from {sorted(_LOAD)}.")
    return _LOAD[source](match_path, **kwargs)  # type: ignore[arg-type]


def list_matches(source: Source, root: Path | None = None) -> list[Path]:
    """List available matches for a source, in deterministic order.

    Args:
        source: One of ``"dfl"``, ``"skillcorner"``, ``"metrica"``, ``"pff"``.
        root: Override the default data root. If ``None``, uses
            :data:`DEFAULT_ROOTS` for the source.

    Returns:
        Sorted list of per-match paths.

    Raises:
        ValueError: If ``source`` is unknown.
    """
    if source not in _LIST:
        raise ValueError(f"Unknown source {source!r}. Pick from {sorted(_LIST)}.")
    if root is None:
        root = DEFAULT_ROOTS[source]
    return _LIST[source](root)


__all__ = ["DEFAULT_ROOTS", "Source", "list_matches", "load_match"]
