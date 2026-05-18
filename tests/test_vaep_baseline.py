"""Tests for the VAEP baseline.

Verifies action conversion on a hand-crafted toy events DataFrame and that
the trained classifier pair returns sensibly-shaped predictions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from wc2026_tracking_transformer.baselines.vaep import (
    DEFAULT_K_ACTIONS,
    events_to_actions,
    label_actions,
    predict_vaep,
    train_vaep,
)


def _toy_events() -> pd.DataFrame:
    """A minimal Metrica-shaped events frame covering the main paths.

    Eight rows exercise:
        * normal PASS, PASS with HEAD subtype
        * CROSS pass (Subtype="CROSS")
        * SHOT off-target, SHOT goal (success=1)
        * RECOVERY, BALL LOST
        * CARD (should be filtered out)
    """
    rows = [
        # team, type, subtype, period, sf, ef, from, to, sx, sy, ex, ey
        ("Home", "PASS", None,         1,   1,   5, "P1", "P2", 0.30, 0.50, 0.40, 0.50),
        ("Home", "PASS", "HEAD",       1,   6,  10, "P2", "P3", 0.40, 0.50, 0.50, 0.55),
        ("Home", "PASS", "CROSS",      1,  11,  18, "P3", "P4", 0.85, 0.30, 0.95, 0.55),
        ("Home", "SHOT", "ON TARGET-GOAL", 1, 19, 25, "P4", None, 0.95, 0.55, 1.00, 0.50),
        ("Away", "RECOVERY", None,    1,  30,  30, "P11", None, 0.50, 0.40, 0.50, 0.40),
        ("Away", "PASS", None,         1,  31,  40, "P11", "P12", 0.50, 0.40, 0.60, 0.45),
        ("Away", "BALL LOST", None,    1,  41,  41, "P12", None, 0.60, 0.45, 0.60, 0.45),
        ("Home", "CARD", "YELLOW",     1,  42,  42, "P3", None,  np.nan, np.nan, np.nan, np.nan),
    ]
    cols = ["Team", "Type", "Subtype", "Period", "Start Frame", "End Frame",
            "From", "To", "Start X", "Start Y", "End X", "End Y"]
    return pd.DataFrame(rows, columns=cols)


def test_events_to_actions_filters_and_classifies() -> None:
    events = _toy_events()
    actions = events_to_actions(events)

    # CARD is dropped; everything else stays. 7 events kept.
    assert len(actions) == 7
    assert list(actions.columns) == [
        "action_id", "period", "start_frame", "end_frame", "team", "type",
        "body_part", "start_x", "start_y", "end_x", "end_y", "dx", "dy",
        "success_or_not", "from_player", "to_player",
    ]

    # First two rows are passes: foot then head body part.
    assert actions.loc[0, "type"] == "pass"
    assert actions.loc[0, "body_part"] == "foot"
    assert actions.loc[1, "type"] == "pass"
    assert actions.loc[1, "body_part"] == "head"

    # The CROSS subtype gets its own action type.
    assert actions.loc[2, "type"] == "cross"

    # SHOT with GOAL subtype: success=1.
    assert actions.loc[3, "type"] == "shot"
    assert actions.loc[3, "success_or_not"] == 1

    # dx/dy computed properly.
    np.testing.assert_allclose(actions.loc[0, "dx"], 0.10)
    np.testing.assert_allclose(actions.loc[0, "dy"], 0.00)

    # Action IDs are contiguous 0..n-1.
    assert actions["action_id"].tolist() == list(range(len(actions)))


def test_label_actions_scores_and_concedes_window() -> None:
    events = _toy_events()
    actions = events_to_actions(events)
    scores, concedes = label_actions(actions, k_actions=DEFAULT_K_ACTIONS)
    assert scores.shape == (len(actions),)
    assert concedes.shape == (len(actions),)

    # Action 3 is a Home goal. Home actions 0..2 should be labeled "scores".
    assert scores[0] == 1
    assert scores[1] == 1
    assert scores[2] == 1
    # The goal itself isn't labeled scores (it's the action *during* the goal).
    assert scores[3] == 0

    # No Away goals in the window — concedes should be all-zero for Home rows.
    assert int(concedes[0]) == 0
    assert int(concedes[3]) == 0


def test_train_vaep_and_predict_returns_well_shaped_probs() -> None:
    """Training on the toy frame should yield (p_score, p_concede, vaep_value)
    columns in [0,1] (for probs) of the right length."""
    events = _toy_events()
    actions = events_to_actions(events)
    scores, concedes = label_actions(actions, k_actions=DEFAULT_K_ACTIONS)

    model = train_vaep(actions, scores, concedes, n_estimators=10, max_depth=2)
    preds = predict_vaep(model, actions)

    assert list(preds.columns) == ["p_score", "p_concede", "vaep_value"]
    assert len(preds) == len(actions)
    assert (preds["p_score"] >= 0).all() and (preds["p_score"] <= 1).all()
    assert (preds["p_concede"] >= 0).all() and (preds["p_concede"] <= 1).all()
    # vaep_value is the signed diff and lives in [-1, 1].
    assert (preds["vaep_value"] >= -1).all() and (preds["vaep_value"] <= 1).all()


def test_events_to_actions_handles_empty_input() -> None:
    """An events frame with no actionable rows yields an empty result with
    the correct column schema."""
    cols = ["Team", "Type", "Subtype", "Period", "Start Frame", "End Frame",
            "From", "To", "Start X", "Start Y", "End X", "End Y"]
    empty = pd.DataFrame({c: [] for c in cols})
    out = events_to_actions(empty)
    assert len(out) == 0
    assert "action_id" in out.columns
    assert "type" in out.columns
