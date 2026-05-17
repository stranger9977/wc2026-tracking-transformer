"""Tests for the PFF loader scaffold.

These confirm the *contract* (the loader raises NotImplementedError today and
discovers no data when the raw dir is empty). When the loader is implemented,
replace these with real round-trip tests gated on ``has_pff_data``.
"""

from pathlib import Path

import pytest


def test_load_pff_match_is_scaffold(tmp_path: Path) -> None:
    from wc2026_tracking_transformer.data import load_pff_match

    with pytest.raises(NotImplementedError):
        # Materialize the generator (load_pff_match is an Iterator factory).
        next(iter(load_pff_match(tmp_path)))


def test_list_pff_matches_is_scaffold(tmp_path: Path) -> None:
    from wc2026_tracking_transformer.data.pff_loader import list_pff_matches

    with pytest.raises(NotImplementedError):
        list_pff_matches(tmp_path)


@pytest.mark.skip(reason="enable once load_pff_match is implemented")
def test_load_pff_match_roundtrip(raw_pff_dir: Path, has_pff_data: bool) -> None:
    if not has_pff_data:
        pytest.skip("no PFF data present under data/raw/pff_wc2022/")
    # TODO: load one match, assert 22 players per frame, sensible coord ranges.
