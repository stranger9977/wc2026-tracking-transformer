"""Tests against the JSON the site consumes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

SITE_DATA = Path(__file__).resolve().parents[1] / "site" / "data"


@pytest.fixture
def overview():
    return json.loads((SITE_DATA / "overview.json").read_text())


@pytest.fixture
def pairs():
    return json.loads((SITE_DATA / "pairs.json").read_text())


@pytest.fixture
def teams():
    return json.loads((SITE_DATA / "teams.json").read_text())


def test_overview_keys(overview):
    for k in ("n_matches", "n_teams", "n_actions", "n_pairs", "top_joi_pair", "top_jdi_pair", "vaep_metrics"):
        assert k in overview


def test_overview_match_count(overview):
    assert overview["n_matches"] > 30


def test_pairs_have_required_fields(pairs):
    if not pairs:
        pytest.skip("pairs.json empty")
    sample = pairs[0]
    for k in ("team_id", "team_name", "name_p", "name_q", "role_p", "role_q",
              "minutes_together", "joi90", "jdi90"):
        assert k in sample, f"missing field {k}"


def test_pairs_roles_in_known_set(pairs):
    valid = {"GK", "DEF", "MID", "FWD", None}
    for p in pairs[:200]:
        assert p["role_p"] in valid
        assert p["role_q"] in valid


def test_teams_have_color(teams):
    for t in teams:
        assert t["color"].startswith("#"), f"bad color for {t['team_name']}"
        assert t["n_matches"] >= 1


def test_cross_chem_buckets_exist():
    fp = SITE_DATA / "cross_chem.json"
    if not fp.exists():
        pytest.skip("cross_chem.json not exported yet")
    buckets = json.loads(fp.read_text())
    assert len(buckets) >= 3
    for b in buckets:
        assert b["role_a"] in {"GK", "DEF", "MID", "FWD"}
        assert b["role_b"] in {"GK", "DEF", "MID", "FWD"}
        assert b["n_pairs"] > 0
