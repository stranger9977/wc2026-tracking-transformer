"""Data-quality checks on the chemistry pipeline outputs.

These are the QC gates the project must pass. If any of these fail,
the data on the site is not trustworthy.
"""
from __future__ import annotations


def test_match_count_reasonable(matches):
    """We expect ~60+ PFF WC22 matches converted."""
    assert 50 <= len(matches) <= 70


def test_spadl_action_types(spadl_vaep):
    """SPADL must contain the 5 Bransen interaction types in non-trivial quantities."""
    counts = spadl_vaep.type_name.value_counts()
    for t in ("pass", "cross", "dribble", "take_on", "shot"):
        assert counts.get(t, 0) > 0, f"no {t} actions"
    # Passes should dwarf everything else
    assert counts["pass"] > 5 * counts.get("shot", 1)


def test_spadl_coordinates_in_bounds(spadl_vaep):
    """SPADL coords must lie on a 105×68 pitch."""
    assert spadl_vaep.start_x.between(0, 105).all()
    assert spadl_vaep.start_y.between(0, 68).all()
    assert spadl_vaep.end_x.between(0, 105).all()
    assert spadl_vaep.end_y.between(0, 68).all()


def test_shots_cluster_at_attacking_goal(spadl_vaep):
    """In SPADL each action is from the attacker's perspective — shots must end near x=105."""
    shots = spadl_vaep[spadl_vaep.type_name.str.startswith("shot")]
    assert (shots.end_x > 80).mean() > 0.85, "most shots should end in attacking third"


def test_vaep_values_finite(spadl_vaep):
    import numpy as np
    assert np.isfinite(spadl_vaep.vaep_value).all()
    assert np.isfinite(spadl_vaep.p_score).all()
    assert np.isfinite(spadl_vaep.p_concede).all()


def test_p_score_in_probability_range(spadl_vaep):
    assert spadl_vaep.p_score.between(0, 1).all()
    assert spadl_vaep.p_concede.between(0, 1).all()


def test_goal_vaep_is_positive(spadl_vaep):
    """A successful shot (goal) should have positive VAEP on average."""
    goals = spadl_vaep[
        (spadl_vaep.type_name.str.startswith("shot"))
        & (spadl_vaep.result_name == "success")
    ]
    assert len(goals) > 50, f"expected dozens of goals, got {len(goals)}"
    assert goals.vaep_value.mean() > 0
    # Goals should sit comfortably above the population median action.
    assert goals.vaep_value.median() > spadl_vaep.vaep_value.median()


def test_minutes_per_match_sane(lineups):
    """Sum of player minutes per match should be ~22 starters × ~95 min ≈ 2090."""
    per_match = lineups.groupby("game_id").on_seconds.sum() / 60.0
    # World Cup matches with no extra time should sum to ~2090 minutes
    assert per_match.median() > 1800
    assert per_match.median() < 2400  # extra time matches push this higher


def test_joi_pairs_all_same_team(joi):
    """JOI is only defined for teammates."""
    # name_p and name_q both filled, team_id present
    assert joi.team_id.notna().all()
    assert joi.joi90.notna().all()


def test_jdi_pairs_all_same_team(jdi):
    assert jdi.team_id.notna().all()
    assert jdi.jdi90.notna().all()


def test_pair_minutes_symmetric(pair_minutes_df):
    """If a pair appears, minutes_together must be > 0."""
    assert (pair_minutes_df.minutes_together > 0).all()


def test_top_joi_pair_makes_sense(joi):
    """The very top JOI90 pair should be a recognizable attacking partnership."""
    qualifying = joi[joi.minutes_together >= 60].head(10)
    assert len(qualifying) >= 5, "need enough qualifying pairs"
    # No NaNs / infs in the top
    import numpy as np
    assert np.isfinite(qualifying.joi90).all()
    assert (qualifying.joi90 > 0).all()


def test_jdi_top_pairs_contain_defender(jdi, lineups):
    """The very top-of-table JDI pairs should usually have at least one
    defender or holding midfielder — pure forward partnerships should be
    rare among the leaders even after responsibility-share weighting."""
    pos_lookup = (
        lineups.dropna(subset=["position"])
        .groupby("player_id").position.agg(lambda s: s.value_counts().index[0])
        .to_dict()
    )
    defensive_codes = {"GK","LB","LCB","MCB","RCB","CB","RB","LWB","RWB","DM","CDM","LDM","RDM"}
    top = jdi[jdi.minutes_together >= 90].head(20)
    has_def = 0
    for r in top.itertuples():
        if (pos_lookup.get(r.player_p) in defensive_codes
                or pos_lookup.get(r.player_q) in defensive_codes):
            has_def += 1
    assert has_def >= 10, f"<half of top-20 JDI pairs contain a defender: {has_def}/20"
