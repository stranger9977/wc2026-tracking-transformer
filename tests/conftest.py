"""Shared pytest fixtures."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repo root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def raw_data_root(repo_root: Path) -> Path:
    """Path to ``data/raw/`` (parent of per-source dirs)."""
    return repo_root / "data" / "raw"


def _has_data(directory: Path) -> bool:
    if not directory.exists():
        return False
    return any(p.name != ".gitkeep" for p in directory.rglob("*") if p.is_file())


@pytest.fixture
def has_dfl_data(raw_data_root: Path) -> bool:
    return _has_data(raw_data_root / "dfl_bassek")


@pytest.fixture
def has_skillcorner_data(raw_data_root: Path) -> bool:
    return _has_data(raw_data_root / "skillcorner_aleague")


@pytest.fixture
def has_metrica_data(raw_data_root: Path) -> bool:
    return _has_data(raw_data_root / "metrica")


@pytest.fixture
def has_pff_data(raw_data_root: Path) -> bool:
    return _has_data(raw_data_root / "pff_wc2022")
