"""Build per-action gamestate features and (scores, concedes) labels.

We follow Decroos et al. (VAEP, 2019): the value of an action equals the
*change* in (P(score in the next K actions) - P(concede)) from before to after.
We compute features that summarize the "state after action i" using the last
three actions {i-2, i-1, i}.

For each action a_i we build:
  - action_type one-hot for {a_i, a_{i-1}, a_{i-2}}
  - start/end coords for the three actions
  - deltas (end-start), distance, angle-to-goal
  - same-team-as-i flags for a_{i-1}, a_{i-2}
  - time_seconds, period
  - result success bool

Labels:
  - scores_next10  = 1 if a_i's team scored within the next 10 actions in the same match
  - concedes_next10 = 1 if a_i's team conceded within the next 10 actions
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..loaders.pff_spadl import ACTION_INDEX

LOOK_AHEAD = 10
GOAL_X = 105.0
GOAL_Y = 34.0


def _xy(df: pd.DataFrame, col: str) -> np.ndarray:
    return df[col].to_numpy(dtype=np.float32)


def build_features(spadl: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Return (X features DataFrame, y_scores Series, y_concedes Series).

    Computes per-game so look-ahead labels don't leak across games.
    """
    feat_parts: list[pd.DataFrame] = []
    score_parts: list[pd.Series] = []
    concede_parts: list[pd.Series] = []
    for game_id, df in spadl.groupby("game_id", sort=False):
        df = df.sort_values(["period_id", "time_seconds"]).reset_index(drop=True)
        f, ys, yc = _features_one_game(df)
        feat_parts.append(f)
        score_parts.append(ys)
        concede_parts.append(yc)
    X = pd.concat(feat_parts, ignore_index=True)
    yS = pd.concat(score_parts, ignore_index=True)
    yC = pd.concat(concede_parts, ignore_index=True)
    return X, yS, yC


def _features_one_game(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    n = len(df)
    type_idx = df["type_name"].map(ACTION_INDEX).fillna(ACTION_INDEX["non_action"]).astype(int).to_numpy()
    sx = _xy(df, "start_x"); sy = _xy(df, "start_y")
    ex = _xy(df, "end_x"); ey = _xy(df, "end_y")
    teams = df["team_id"].to_numpy()
    period = df["period_id"].to_numpy(dtype=np.int32)
    timesec = df["time_seconds"].to_numpy(dtype=np.float32)
    result = (df["result_name"] == "success").astype(np.int8).to_numpy()

    # Distance / angle to goal at end-of-action point
    def dist_goal(x, y):
        return np.sqrt((GOAL_X - x) ** 2 + (GOAL_Y - y) ** 2)

    def angle_goal(x, y):
        dx = GOAL_X - x
        dy = GOAL_Y - y
        return np.arctan2(np.abs(dy), np.maximum(dx, 0.1))

    # Shifted versions for prior actions
    def shifted(arr, k, fill):
        out = np.full_like(arr, fill) if isinstance(arr, np.ndarray) else np.full(n, fill)
        if isinstance(arr, np.ndarray):
            if k > 0:
                out[k:] = arr[:-k]
            return out
        return out

    feat = {}
    feat["type"] = type_idx
    feat["type_lag1"] = shifted(type_idx, 1, ACTION_INDEX["non_action"])
    feat["type_lag2"] = shifted(type_idx, 2, ACTION_INDEX["non_action"])
    feat["start_x"] = sx
    feat["start_y"] = sy
    feat["end_x"] = ex
    feat["end_y"] = ey
    feat["dx"] = ex - sx
    feat["dy"] = ey - sy
    feat["dist_goal"] = dist_goal(ex, ey)
    feat["angle_goal"] = angle_goal(ex, ey)
    feat["start_x_lag1"] = shifted(sx, 1, 52.5)
    feat["start_y_lag1"] = shifted(sy, 1, 34.0)
    feat["end_x_lag1"] = shifted(ex, 1, 52.5)
    feat["end_y_lag1"] = shifted(ey, 1, 34.0)
    feat["dx_lag1"] = shifted(ex - sx, 1, 0.0)
    feat["dy_lag1"] = shifted(ey - sy, 1, 0.0)
    feat["end_x_lag2"] = shifted(ex, 2, 52.5)
    feat["end_y_lag2"] = shifted(ey, 2, 34.0)
    # same team as current?
    same1 = np.zeros(n, dtype=np.int8)
    same2 = np.zeros(n, dtype=np.int8)
    same1[1:] = (teams[1:] == teams[:-1]).astype(np.int8)
    same2[2:] = (teams[2:] == teams[:-2]).astype(np.int8)
    feat["same_team_lag1"] = same1
    feat["same_team_lag2"] = same2
    feat["result"] = result
    feat["period"] = period
    # Time elapsed in the match (seconds, normalized to [0, 1])
    feat["time_norm"] = np.clip(timesec / (95 * 60.0), 0.0, 1.5)

    X = pd.DataFrame(feat)

    # Labels: scores/concedes within actions [i, i+LOOK_AHEAD]. We include
    # action i itself so that a goal-scoring action carries the +1 reward
    # in its own state — otherwise VAEP attribution for goals comes out
    # negative (the "after-goal" state has low P_score).
    yS = np.zeros(n, dtype=np.int8)
    yC = np.zeros(n, dtype=np.int8)
    is_shot = np.isin(type_idx, [ACTION_INDEX[t] for t in ("shot", "shot_penalty", "shot_freekick")])
    is_goal = is_shot & (result == 1)

    for i in range(n):
        end = min(n, i + LOOK_AHEAD + 1)
        for j in range(i, end):
            if is_goal[j]:
                if teams[j] == teams[i]:
                    yS[i] = 1
                else:
                    yC[i] = 1
                break  # stop at first goal in window (including current action)
    return X, pd.Series(yS, name="scores_next10"), pd.Series(yC, name="concedes_next10")
