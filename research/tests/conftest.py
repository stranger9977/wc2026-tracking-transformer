"""Shared test fixtures. Adds research/src to PYTHONPATH."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RESEARCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH / "src"))

DATA = RESEARCH / "data"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA


@pytest.fixture(scope="session")
def matches(data_dir):
    import pandas as pd
    return pd.read_parquet(data_dir / "matches.parquet")


@pytest.fixture(scope="session")
def spadl_vaep(data_dir):
    import pandas as pd
    return pd.read_parquet(data_dir / "spadl_vaep.parquet")


@pytest.fixture(scope="session")
def joi(data_dir):
    import pandas as pd
    return pd.read_parquet(data_dir / "joi.parquet")


@pytest.fixture(scope="session")
def jdi(data_dir):
    import pandas as pd
    return pd.read_parquet(data_dir / "jdi.parquet")


@pytest.fixture(scope="session")
def lineups(data_dir):
    import pandas as pd
    return pd.read_parquet(data_dir / "minutes" / "lineups.parquet")


@pytest.fixture(scope="session")
def pair_minutes_df(data_dir):
    import pandas as pd
    return pd.read_parquet(data_dir / "minutes" / "pair_minutes.parquet")
