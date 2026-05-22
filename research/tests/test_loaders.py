"""Unit tests for the PFF SPADL converter and grid mapping."""
from __future__ import annotations

import pytest

from chemistry.joint.grid import grid_cell, grid_distance, grid_role
from chemistry.loaders.pff_spadl import events_to_spadl, load_metadata


def test_grid_cell_known_positions():
    assert grid_cell("GK") == (5, 2)
    assert grid_cell("CB") == (4, 2)
    assert grid_cell("CF") == (0, 2)
    assert grid_cell("LB") == (4, 0)
    assert grid_cell("RWB") == (3, 4)


def test_grid_distance_symmetric():
    assert grid_distance("CB", "LB") == grid_distance("LB", "CB")
    assert grid_distance("GK", "CF") > grid_distance("GK", "CB")


def test_grid_role_buckets():
    assert grid_role("GK") == "GK"
    assert grid_role("LCB") == "DEF"
    assert grid_role("CM") == "MID"
    assert grid_role("CF") == "FWD"


def test_spadl_conversion_one_match():
    df, meta = events_to_spadl(10502)
    assert len(df) > 1000, "Netherlands-USA should produce >1000 actions"
    assert meta.home_name == "Netherlands"
    assert meta.away_name == "United States"

    # The match ended 3-1 to Netherlands → 4 goals total
    goals = df[df.type_name.str.startswith("shot") & (df.result_name == "success")]
    assert 3 <= len(goals) <= 5

    # Each goal must be in the attacking third
    assert (goals.start_x > 70).all()


def test_metadata_loads():
    meta = load_metadata(10502)
    assert meta.home_starts_left is True
    assert meta.competition.lower().startswith("fifa")
