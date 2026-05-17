"""Shared pytest fixtures.

Real-data fixtures will live here once the PFF loader is implemented. For
now this is mostly empty — see ``tests/test_imports.py`` for the smoke
test that runs without data.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repo root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def raw_pff_dir(repo_root: Path) -> Path:
    """Path to the PFF raw data directory. May not contain data yet."""
    return repo_root / "data" / "raw" / "pff_wc2022"


@pytest.fixture
def has_pff_data(raw_pff_dir: Path) -> bool:
    """True if at least one file lives under raw_pff_dir (excluding ``.gitkeep``)."""
    if not raw_pff_dir.exists():
        return False
    return any(p.name != ".gitkeep" for p in raw_pff_dir.rglob("*") if p.is_file())
