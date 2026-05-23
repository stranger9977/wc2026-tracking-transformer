"""Per-frame binary labels for the frame-level VAEP transformer.

Given a list of tracking frames and the match's goal events, produce two
binary labels per frame:

    p_score_label   = 1 if the team currently in possession scores
                      within K seconds.
    p_concede_label = 1 if the team currently in possession concedes
                      within K seconds.

If no team is currently in possession (`in_possession_team_id is None`,
e.g. dead ball), both labels are zero.

This replaces the xT-regression target (`max xT in next K seconds`).
Conceptually it lifts Decroos et al.'s **event-level VAEP** to the
**frame level** — same P-score / P-concede framework, but with the
tracking transformer's 22-player view as input instead of the 3-action
event window.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wc2026_tracking_transformer.data.schema import TrackingFrame


@dataclass(frozen=True, slots=True)
class GoalEvent:
    """A goal that occurred at a known absolute timestamp."""
    period: int
    abs_ms: int          # absolute milliseconds from period 1 kickoff (P2 offset added)
    scoring_team_id: str


def build_labels(
    frames: list[TrackingFrame],
    goals: list[GoalEvent],
    *,
    k_seconds: float = 10.0,
    period1_length_ms: int = 47 * 60 * 1000,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (p_score_label, p_concede_label) arrays of length len(frames).

    Per frame, look ahead `k_seconds` for any goal:
        * If the scoring team == in_possession_team_id of this frame → p_score = 1
        * If the scoring team != in_possession_team_id (and frame has a possession team) → p_concede = 1
        * Otherwise both 0.

    Frames late in the match where the look-ahead overflows the match end
    simply look at whatever goals fall within the remaining window.
    """
    n = len(frames)
    p_score = np.zeros(n, dtype=np.float32)
    p_concede = np.zeros(n, dtype=np.float32)
    if not goals:
        return p_score, p_concede

    # Sort goals by absolute time for binary search.
    goals_sorted = sorted(goals, key=lambda g: g.abs_ms)
    goal_times = np.asarray([g.abs_ms for g in goals_sorted], dtype=np.int64)
    goal_teams = [g.scoring_team_id for g in goals_sorted]
    k_ms = int(k_seconds * 1000)

    for i, f in enumerate(frames):
        if f.in_possession_team_id is None:
            continue
        abs_t = f.timestamp_ms if f.period == 1 else period1_length_ms + f.timestamp_ms
        end_t = abs_t + k_ms
        # Find the first goal at time >= abs_t
        idx_lo = int(np.searchsorted(goal_times, abs_t, side="left"))
        idx_hi = int(np.searchsorted(goal_times, end_t, side="right"))
        if idx_lo >= idx_hi:
            continue
        # Check the next goal(s) in the window — first one decides.
        # If multiple goals (rare in 10s), first determines.
        scoring_team = goal_teams[idx_lo]
        if scoring_team == f.in_possession_team_id:
            p_score[i] = 1.0
        else:
            p_concede[i] = 1.0
    return p_score, p_concede


def goals_from_pff_events(events: list[dict],
                          *, period1_length_ms: int = 47 * 60 * 1000) -> list[GoalEvent]:
    """Extract goals from a PFF event JSON.

    Returns absolute-time goal events. PFF's `startGameClock` is wall-clock
    seconds from kickoff (P2 starts at 2700 = 45:00 on the displayed clock);
    we convert to absolute ms-since-period1-kickoff using the same period1
    length the labeler uses (~47 min including stoppage).
    """
    out: list[GoalEvent] = []
    for ev in events:
        ge = ev.get("gameEvents") or {}
        pe = ev.get("possessionEvents") or {}
        if pe.get("possessionEventType") != "SH":
            continue
        if pe.get("shotOutcomeType") != "G":
            continue
        period = int(ge.get("period") or 1)
        clock = float(pe.get("gameClock") or ge.get("startGameClock") or 0)
        # `clock` in PFF is already match-clock seconds (0..~2800 in P1,
        # 2700..~5600 in P2). Convert to absolute ms from P1 kickoff.
        abs_ms = int(clock * 1000) if period == 1 else int(
            (clock - 2700) * 1000 + period1_length_ms
        )
        team_id = str(ge.get("teamId")) if ge.get("teamId") is not None else None
        if team_id is None:
            continue
        out.append(GoalEvent(period=period, abs_ms=abs_ms, scoring_team_id=team_id))
    return out
