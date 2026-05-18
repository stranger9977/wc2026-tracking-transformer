"""Parametrized contract tests for the per-source loader scaffolds.

These confirm that every source's `load_match` and `list_matches` are wired
into the unified dispatcher and raise NotImplementedError until implemented.
Once a backend is implemented, drop it from the SCAFFOLDED list and add a
real round-trip test (gated on data presence).
"""

from pathlib import Path

import pytest

# Sources whose loaders are still scaffolds. Metrica is implemented and
# tested separately in test_metrica_loader.py.
SCAFFOLDED = ["dfl", "skillcorner", "pff"]


@pytest.mark.parametrize("source", SCAFFOLDED)
def test_load_match_is_scaffold(source: str, tmp_path: Path) -> None:
    from wc2026_tracking_transformer.data import load_match

    with pytest.raises(NotImplementedError):
        # load_match returns an iterator; materialize to trigger the body.
        next(iter(load_match(source, tmp_path)))  # type: ignore[arg-type]


@pytest.mark.parametrize("source", SCAFFOLDED)
def test_list_matches_is_scaffold(source: str, tmp_path: Path) -> None:
    from wc2026_tracking_transformer.data import list_matches

    with pytest.raises(NotImplementedError):
        list_matches(source, tmp_path)  # type: ignore[arg-type]
