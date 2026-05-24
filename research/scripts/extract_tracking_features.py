"""Per-action tracking-derived features built from PFF event JSON snapshots.

Each PFF event embeds a `homePlayers` / `awayPlayers` array with x/y/speed
for every player at the event's timestamp — i.e. we already have a tracking
snapshot at every event, no separate tracking-file read needed.

Output features (per SPADL action):
    f_nearest_opp_dist     — meters from actor to nearest opponent
    f_n_opp_within_5m      — count of opponents within 5m of actor
    f_n_teammates_within_5m — count of teammates within 5m
    f_dist_to_opp_goal     — meters from actor to opponent goal (105, 34)
    f_dist_to_own_goal     — meters from actor to own goal (0, 34)
    f_actor_speed          — actor's speed (m/s) per PFF
    f_nearest_opp_speed    — speed of nearest opponent
    f_ball_actor_dist      — meters from ball to actor
    f_n_opp_in_lane        — opponents in a 10m-wide lane between actor and opp goal
    f_n_teammates_in_lane  — teammates in that lane

Output: research/data/tracking_features.parquet keyed by (game_id, action_id).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))

from chemistry.loaders.pff_paths import event_path, event_files
from chemistry.loaders.pff_spadl import _normalize_pff_coords, _team_attacks_right, load_metadata


def _player_xy(ev: dict, pid: int):
    for side in ("homePlayers", "awayPlayers"):
        for p in ev.get(side) or []:
            if p.get("playerId") == pid and p.get("x") is not None and p.get("y") is not None:
                return float(p["x"]), float(p["y"]), float(p.get("speed") or 0.0), side == "homePlayers"
    return None, None, None, None


def _features_for_event(ev: dict, actor_id: int, attacks_right: bool, is_actor_home: bool
                       ) -> dict | None:
    ax, ay, aspeed, actor_home_side = _player_xy(ev, actor_id)
    if ax is None:
        return None
    home_pls = ev.get("homePlayers") or []
    away_pls = ev.get("awayPlayers") or []
    teammates = home_pls if is_actor_home else away_pls
    opponents = away_pls if is_actor_home else home_pls

    def d_to(p):
        if p.get("x") is None or p.get("y") is None:
            return None
        return math.hypot(p["x"] - ax, p["y"] - ay)

    # Opponent distances
    opp_dists = []
    opp_speeds = []
    for p in opponents:
        d = d_to(p)
        if d is not None:
            opp_dists.append(d)
            opp_speeds.append(float(p.get("speed") or 0.0))
    if not opp_dists:
        return None
    near_opp_dist = min(opp_dists)
    near_opp_idx = opp_dists.index(near_opp_dist)
    near_opp_speed = opp_speeds[near_opp_idx]
    n_opp_5 = sum(1 for d in opp_dists if d <= 5.0)
    n_team_5 = sum(1 for p in teammates
                   if p.get("playerId") != actor_id
                   and (d_to(p) or 1e9) <= 5.0)

    # Distance to goals (always to opponent goal in PFF coords)
    # In PFF coords, the home team attacks the +x end if home_starts_left=True in P1.
    # Goal y-center ≈ 0, goal x at ±52.5. For "opp goal" we need the side they attack.
    opp_goal_x = 52.5 if attacks_right else -52.5
    own_goal_x = -opp_goal_x
    d_opp = math.hypot(opp_goal_x - ax, 0.0 - ay)
    d_own = math.hypot(own_goal_x - ax, 0.0 - ay)

    # Ball position from this event
    ball = (ev.get("ball") or [{}])[0]
    bx = ball.get("x"); by = ball.get("y")
    ball_actor_dist = math.hypot(bx - ax, by - ay) if (bx is not None and by is not None) else float("nan")

    # Lane analysis: count opp/teammates between actor and opp goal within 10m of the line
    dx = opp_goal_x - ax
    dy = 0.0 - ay
    seg_len2 = dx * dx + dy * dy or 1.0
    def in_lane(p):
        if p.get("x") is None or p.get("y") is None:
            return False
        ex = p["x"] - ax
        ey = p["y"] - ay
        t = (ex * dx + ey * dy) / seg_len2
        if not (0.0 < t < 1.0):
            return False
        # perpendicular distance to the line
        proj_x = ax + t * dx; proj_y = ay + t * dy
        perp = math.hypot(p["x"] - proj_x, p["y"] - proj_y)
        return perp <= 10.0
    n_opp_lane = sum(1 for p in opponents if in_lane(p))
    n_team_lane = sum(1 for p in teammates if p.get("playerId") != actor_id and in_lane(p))

    return {
        "f_nearest_opp_dist": near_opp_dist,
        "f_n_opp_within_5m": n_opp_5,
        "f_n_teammates_within_5m": n_team_5,
        "f_dist_to_opp_goal": d_opp,
        "f_dist_to_own_goal": d_own,
        "f_actor_speed": aspeed,
        "f_nearest_opp_speed": near_opp_speed,
        "f_ball_actor_dist": ball_actor_dist,
        "f_n_opp_in_lane": n_opp_lane,
        "f_n_teammates_in_lane": n_team_lane,
    }


def main() -> None:
    spadl = pd.read_parquet(REPO / "research" / "data" / "spadl_vaep.parquet")
    out: list[dict] = []
    files = event_files()
    print(f"Processing {len(files)} matches…")
    for fp in tqdm(files):
        match_id = int(fp.stem)
        try:
            meta = load_metadata(match_id)
        except Exception as e:
            print(f"  skip {match_id}: {e}")
            continue
        events = json.loads(fp.read_text())
        # SPADL rows for this match — keyed by possession_event_id for join
        sm = spadl[spadl.game_id == match_id]
        if sm.empty:
            continue
        sm_by_pid = sm.set_index("possession_event_id")
        for ev in events:
            pe_id = ev.get("possessionEventId")
            if pe_id not in sm_by_pid.index:
                continue
            row = sm_by_pid.loc[pe_id]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            actor_id = int(row.player_id)
            period = int(row.period_id)
            is_home = bool(row.is_home) if "is_home" in row else None
            if is_home is None:
                _, _, _, ahome = _player_xy(ev, actor_id)
                if ahome is None:
                    continue
                is_home = ahome
            attacks_right = _team_attacks_right(meta, period, is_home)
            feats = _features_for_event(ev, actor_id, attacks_right, is_home)
            if feats is None:
                continue
            feats["game_id"] = match_id
            feats["action_id"] = int(row.action_id)
            out.append(feats)
    df = pd.DataFrame(out)
    out_path = REPO / "research" / "data" / "tracking_features.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()
