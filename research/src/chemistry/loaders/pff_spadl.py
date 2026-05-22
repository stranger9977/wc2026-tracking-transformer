"""Convert PFF FC WC '22 event JSON to SPADL-style action DataFrames.

SPADL spec we target:
    game_id, period_id, time_seconds, team_id, team_name,
    player_id, player_name, type_name, result_name, bodypart_name,
    start_x, start_y, end_x, end_y, action_id, original_event_id

Coordinates are normalized to [0, 105] x [0, 68] from the *acting team's*
attacking perspective (team attacks toward x = 105 in both periods).

Bransen's chemistry only needs 5 offensive action types
(pass, cross, dribble, take_on, shot) but we keep a few more
(tackle/interception/clearance/keeper_save/freekick/corner/throwin/goalkick)
so the VAEP gamestate features have the full picture.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .pff_paths import event_path, metadata_path

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
PFF_HALF_LENGTH = 52.5  # PFF uses meter coords centered on midfield
PFF_HALF_WIDTH = 34.0

# Action type names (SPADL conventions)
ACTION_TYPES = [
    "pass", "cross", "throw_in",
    "freekick_crossed", "freekick_short", "corner_crossed", "corner_short",
    "goalkick", "shot", "shot_penalty", "shot_freekick",
    "dribble", "take_on", "tackle", "interception",
    "keeper_save", "keeper_claim", "keeper_punch", "keeper_pick_up",
    "clearance", "bad_touch", "foul", "non_action",
]
ACTION_INDEX = {n: i for i, n in enumerate(ACTION_TYPES)}

# The 5 Bransen action types that participate in interactions
INTERACTION_TYPES = {"pass", "cross", "dribble", "take_on", "shot"}

BODYPART_FOOT = "foot"
BODYPART_HEAD = "head_other"
BODYPART_OTHER = "other"


@dataclass
class MatchMeta:
    match_id: int
    home_id: str
    home_name: str
    home_short: str
    home_color: str
    away_id: str
    away_name: str
    away_short: str
    away_color: str
    home_starts_left: bool
    period1_start: float
    period1_end: float
    period2_start: float
    period2_end: float
    date: str
    competition: str


def load_metadata(match_id: int | str) -> MatchMeta:
    raw = json.loads(metadata_path(match_id).read_text())
    if isinstance(raw, list):
        raw = raw[0]
    return MatchMeta(
        match_id=int(raw["id"]),
        home_id=raw["homeTeam"]["id"],
        home_name=raw["homeTeam"]["name"],
        home_short=raw["homeTeam"]["shortName"],
        home_color=(raw.get("homeTeamKit") or {}).get("primaryColor", "#888888"),
        away_id=raw["awayTeam"]["id"],
        away_name=raw["awayTeam"]["name"],
        away_short=raw["awayTeam"]["shortName"],
        away_color=(raw.get("awayTeamKit") or {}).get("primaryColor", "#444444"),
        home_starts_left=bool(raw.get("homeTeamStartLeft", True)),
        period1_start=float(raw.get("startPeriod1") or 0),
        period1_end=float(raw.get("endPeriod1") or 0),
        period2_start=float(raw.get("startPeriod2") or 0),
        period2_end=float(raw.get("endPeriod2") or 0),
        date=str(raw.get("date", "")),
        competition=(raw.get("competition") or {}).get("name", "FIFA Men's World Cup"),
    )


def _ball_xy(ev: dict) -> tuple[float | None, float | None]:
    ball = ev.get("ball") or []
    if not ball:
        return None, None
    b = ball[0]
    x, y = b.get("x"), b.get("y")
    if x is None or y is None:
        return None, None
    return float(x), float(y)


def _player_xy(ev: dict, player_id: int) -> tuple[float | None, float | None]:
    for side in ("homePlayers", "awayPlayers"):
        for p in ev.get(side) or []:
            if p.get("playerId") == player_id:
                x, y = p.get("x"), p.get("y")
                if x is not None and y is not None:
                    return float(x), float(y)
                return None, None
    return None, None


def _normalize_pff_coords(
    x: float | None, y: float | None,
    team_attacks_right: bool,
) -> tuple[float, float]:
    """PFF meters -> SPADL meters, from acting team's attacking perspective."""
    if x is None or y is None:
        return 52.5, 34.0  # midpoint fallback
    # PFF -> SPADL absolute pitch coords (left bottom = origin)
    sx = x + PFF_HALF_LENGTH
    sy = y + PFF_HALF_WIDTH
    if not team_attacks_right:
        sx = PITCH_LENGTH - sx
        sy = PITCH_WIDTH - sy
    # Clamp into pitch
    sx = max(0.0, min(PITCH_LENGTH, sx))
    sy = max(0.0, min(PITCH_WIDTH, sy))
    return sx, sy


def _team_attacks_right(meta: MatchMeta, period_id: int, is_home_team: bool) -> bool:
    """Which direction does this team attack in this period (PFF +x)?"""
    home_left_p1 = meta.home_starts_left
    if period_id == 1:
        home_right = not home_left_p1  # if home starts left (goal left), attacks right? PFF: homeTeamStartLeft = home is on left side
        # PFF convention: "homeTeamStartLeft" true => home's goal/own half is on left in period 1, so home attacks to right (+x)
        home_attacks_right = home_left_p1
    else:
        home_attacks_right = not home_left_p1
    if is_home_team:
        return home_attacks_right
    return not home_attacks_right


_PASS_TYPE_TO_ACTION = {
    # PFF passType is only meaningful when possessionEventType == 'PA' or 'CR'
    "S": "pass",
    "C": "cross",
    "T": "throw_in",
    "L": "pass",  # long
    "F": "pass",  # forward?
    "O": "pass",
    "B": "pass",  # back?
}


_SETPIECE_PASS = {
    "O": "open",
    "T": "throw_in",
    "F": "freekick",
    "G": "goalkick",
    "C": "corner",
    "K": "kickoff",
}


def _classify_pass_action(setpiece: str | None, pass_type: str | None) -> str:
    """Map PFF pass + set-piece context to SPADL action name."""
    sp = _SETPIECE_PASS.get(setpiece, "open")
    is_cross = pass_type == "C"
    if sp == "throw_in":
        return "throw_in"
    if sp == "goalkick":
        return "goalkick"
    if sp == "corner":
        return "corner_crossed" if is_cross else "corner_short"
    if sp == "freekick":
        return "freekick_crossed" if is_cross else "freekick_short"
    if sp == "kickoff":
        return "pass"
    return "cross" if is_cross else "pass"


def _pass_result(outcome: str | None) -> str:
    # PFF passOutcomeType: C=complete, D=defended (incomplete), B=blocked, O=out-of-play, S=stoppage?
    if outcome == "C":
        return "success"
    if outcome == "O":
        return "fail"
    return "fail"


def _shot_action(setpiece: str | None) -> str:
    if setpiece == "P":
        return "shot_penalty"
    if setpiece == "F":
        return "shot_freekick"
    return "shot"


def _shot_result(outcome: str | None) -> str:
    # PFF shotOutcomeType: G=goal, S=saved, B=blocked, O=off target, C=cleared off line?, L=hit post?
    if outcome == "G":
        return "success"
    return "fail"


def _bodypart(body_type: str | None) -> str:
    # PFF bodyType: L=left foot, R=right foot, H=head, B=body, A=any?
    if body_type in ("L", "R"):
        return BODYPART_FOOT
    if body_type == "H":
        return BODYPART_HEAD
    return BODYPART_OTHER


def _carry_result(outcome: str | None) -> str:
    return "success" if outcome == "R" else "fail"


def _challenge_result(outcome: str | None, winner_id: int | None, actor_id: int | None) -> str:
    if winner_id is not None and actor_id is not None:
        return "success" if winner_id == actor_id else "fail"
    return "fail"


def _team_id_for_player(ev: dict, player_id: int) -> str | None:
    """Look up player team from the per-event homePlayers/awayPlayers snapshot."""
    for p in ev.get("homePlayers") or []:
        if p.get("playerId") == player_id:
            return "home"
    for p in ev.get("awayPlayers") or []:
        if p.get("playerId") == player_id:
            return "away"
    return None


def events_to_spadl(match_id: int | str) -> tuple[pd.DataFrame, MatchMeta]:
    """Convert one PFF event JSON to a SPADL-style DataFrame."""
    meta = load_metadata(match_id)
    events = json.loads(event_path(match_id).read_text())

    rows: list[dict] = []
    next_ball_lookup: list[tuple[int, float, float]] = []  # (idx_in_rows, sx_raw, sy_raw)

    # First pass: build raw ball-x/y arrays for end-coord interpolation
    ball_xy_by_idx: dict[int, tuple[float, float]] = {}
    for i, ev in enumerate(events):
        x, y = _ball_xy(ev)
        if x is not None:
            ball_xy_by_idx[i] = (x, y)

    def next_ball(after_idx: int) -> tuple[float | None, float | None]:
        for j in range(after_idx + 1, min(after_idx + 6, len(events))):
            if j in ball_xy_by_idx:
                return ball_xy_by_idx[j]
        return None, None

    for i, ev in enumerate(events):
        ge = ev.get("gameEvents") or {}
        pe = ev.get("possessionEvents") or {}
        if pe.get("nonEvent"):
            continue
        pe_type = pe.get("possessionEventType")
        period = int(ge.get("period") or 1)
        if period not in (1, 2):
            continue
        # PFF "gameClock" / "startGameClock" is absolute match-clock seconds
        # (P1 starts at 0, P2 starts at 2700). We keep it as-is and rely on
        # (period_id, time_seconds) sorting for chronological order.
        time_s = float(pe.get("gameClock") or ge.get("startGameClock") or 0)

        # Determine actor + action type
        action_name: str | None = None
        result: str = "fail"
        actor_id: int | None = None
        receiver_id: int | None = None
        bodypart = _bodypart(pe.get("bodyType"))
        setpiece = ge.get("setpieceType")

        if pe_type == "PA":
            actor_id = pe.get("passerPlayerId")
            receiver_id = pe.get("receiverPlayerId") or pe.get("targetPlayerId")
            action_name = _classify_pass_action(setpiece, pe.get("passType"))
            result = _pass_result(pe.get("passOutcomeType"))
        elif pe_type == "CR":
            actor_id = pe.get("crosserPlayerId") or pe.get("passerPlayerId")
            receiver_id = pe.get("receiverPlayerId") or pe.get("targetPlayerId")
            action_name = "cross"
            result = "success" if pe.get("crossOutcomeType") == "C" else "fail"
        elif pe_type == "BC":
            actor_id = pe.get("ballCarrierPlayerId") or pe.get("carrierPlayerId")
            action_name = "dribble"
            result = _carry_result(pe.get("ballCarryOutcome"))
        elif pe_type == "TC":
            actor_id = pe.get("touchPlayerId") or pe.get("carrierPlayerId")
            action_name = "take_on"
            result = "success" if pe.get("touchOutcomeType") in ("R", "C", None) else "fail"
        elif pe_type == "SH":
            actor_id = pe.get("shooterPlayerId")
            action_name = _shot_action(setpiece)
            result = _shot_result(pe.get("shotOutcomeType"))
        elif pe_type == "CH":
            actor_id = pe.get("challengerPlayerId")
            winner = pe.get("challengeWinnerPlayerId")
            outcome = pe.get("challengeOutcomeType")
            # Distinguish tackle vs interception heuristically: in PFF, CH on opponent ball-carrier is tackle/interception
            action_name = "tackle"
            result = _challenge_result(outcome, winner, actor_id)
        elif pe_type == "CL":
            actor_id = pe.get("clearerPlayerId")
            action_name = "clearance"
            result = "success" if pe.get("clearanceOutcomeType") in ("P", "S") else "fail"
        elif pe_type == "RE":
            # Receptions are not standalone SPADL actions; skip
            continue
        elif pe_type == "IT":
            # Initial touch — used elsewhere to attribute to receiver
            continue
        else:
            continue

        if actor_id is None:
            continue
        side = _team_id_for_player(ev, actor_id)
        if side is None:
            continue
        is_home = side == "home"
        team_id = meta.home_id if is_home else meta.away_id
        team_name = meta.home_name if is_home else meta.away_name
        attacks_right = _team_attacks_right(meta, period, is_home)

        # Start = ball location (event start), normalized
        bx, by = _ball_xy(ev)
        if bx is None:
            ax, ay = _player_xy(ev, actor_id)
            bx, by = ax, ay
        sx, sy = _normalize_pff_coords(bx, by, attacks_right)

        # End = receiver location for passes, else next ball location, else start
        ex_raw, ey_raw = None, None
        if receiver_id is not None:
            ex_raw, ey_raw = _player_xy(ev, receiver_id)
        if ex_raw is None:
            ex_raw, ey_raw = next_ball(i)
        if ex_raw is None:
            ex_raw, ey_raw = bx, by
        ex, ey = _normalize_pff_coords(ex_raw, ey_raw, attacks_right)

        rows.append({
            "game_id": meta.match_id,
            "original_event_id": ev.get("gameEventId"),
            "possession_event_id": ev.get("possessionEventId"),
            "period_id": period,
            "time_seconds": time_s,
            "team_id": team_id,
            "team_name": team_name,
            "is_home": is_home,
            "player_id": int(actor_id),
            "player_name": pe.get("passerPlayerName") or pe.get("shooterPlayerName")
                or pe.get("ballCarrierPlayerName") or pe.get("carrierPlayerName")
                or pe.get("challengerPlayerName") or pe.get("clearerPlayerName")
                or pe.get("crosserPlayerName") or pe.get("touchPlayerName"),
            "type_name": action_name,
            "result_name": result,
            "bodypart_name": bodypart,
            "start_x": sx,
            "start_y": sy,
            "end_x": ex,
            "end_y": ey,
            "receiver_id": int(receiver_id) if receiver_id else None,
            "receiver_name": pe.get("receiverPlayerName") or pe.get("targetPlayerName"),
            "setpiece": setpiece,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "game_id", "period_id", "time_seconds", "team_id", "player_id",
            "type_name", "result_name", "start_x", "start_y", "end_x", "end_y",
        ])
        return df, meta
    df = df.sort_values(["period_id", "time_seconds"]).reset_index(drop=True)
    df["action_id"] = range(len(df))
    return df, meta


def write_spadl(match_id: int | str, out_dir: Path) -> Path:
    df, _ = events_to_spadl(match_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{int(match_id)}.parquet"
    df.to_parquet(path, index=False)
    return path
