"""Per-pair goals + assists at WC22.

Definitions
-----------
- **goals_together(p, q)**: count of goals where *both* p and q touched the
  ball within the last K possession-actions leading up to the shot. This
  captures "they built it together," not just the final pass.
- **assists_pq(p, q)**: count of goals where p's pass/cross was the
  immediately preceding action by a teammate before q's scoring shot.
  (Direct assist credit.)
- **assists_together(p, q)** = assists_pq + assists_qp.

Both metrics use only `spadl_vaep.parquet` so they share the same SPADL
ordering as JOI/JDI.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd


# Action types that count as "touching the ball during a buildup".
BUILDUP_TYPES = {"pass", "cross", "dribble", "take_on", "shot",
                 "freekick_short", "freekick_crossed", "corner_short", "corner_crossed"}

# A direct assist must be one of these immediately preceding actions.
ASSIST_TYPES = {"pass", "cross", "freekick_short", "freekick_crossed",
                "corner_short", "corner_crossed"}


def compute_goal_pair_stats(spadl_vaep: pd.DataFrame, *, buildup_window: int = 5) -> pd.DataFrame:
    """Walk every goal, attribute it to the K-action buildup.

    Returns a DataFrame indexed by canonical pair (player_p < player_q) with
    columns:
        goals_together, assists_together,
        assists_pq, assists_qp  (directional)
    """
    pair_goals: dict[tuple[int, int], int] = defaultdict(int)
    pair_assists_pq: dict[tuple[int, int], int] = defaultdict(int)

    for game_id, df in spadl_vaep.groupby("game_id", sort=False):
        df = df.sort_values(["period_id", "time_seconds"]).reset_index(drop=True)
        types = df["type_name"].to_numpy()
        teams = df["team_id"].to_numpy()
        players = df["player_id"].to_numpy()
        results = df["result_name"].to_numpy()
        n = len(df)

        for i in range(n):
            if not (str(types[i]).startswith("shot") and results[i] == "success"):
                continue
            scorer = int(players[i])
            scorer_team = teams[i]

            # Buildup: look backward up to `buildup_window` actions, all by same team
            involved: set[int] = {scorer}
            assister: int | None = None
            for j in range(i - 1, max(-1, i - buildup_window - 1), -1):
                if teams[j] != scorer_team:
                    break
                if types[j] in BUILDUP_TYPES:
                    involved.add(int(players[j]))
                # Direct assist = first preceding completed pass-type teammate action
                if assister is None and types[j] in ASSIST_TYPES and results[j] == "success":
                    if int(players[j]) != scorer:
                        assister = int(players[j])

            # Goals together for every unordered pair in `involved`
            inv = sorted(involved)
            for a in range(len(inv)):
                for b in range(a + 1, len(inv)):
                    pair_goals[(inv[a], inv[b])] += 1

            # Directional assist (assister, scorer)
            if assister is not None:
                lo, hi = (assister, scorer) if assister < scorer else (scorer, assister)
                if assister < scorer:
                    pair_assists_pq[(lo, hi)] += 1  # p assisted q
                else:
                    pair_assists_pq[(lo, hi)] -= 0  # noop — recorded as qp below

    # We tracked direction by checking p < scorer; but we actually want both
    # directions countable. Recompute cleanly:
    pair_assists_pq.clear()
    pair_assists_qp: dict[tuple[int, int], int] = defaultdict(int)
    for game_id, df in spadl_vaep.groupby("game_id", sort=False):
        df = df.sort_values(["period_id", "time_seconds"]).reset_index(drop=True)
        types = df["type_name"].to_numpy()
        teams = df["team_id"].to_numpy()
        players = df["player_id"].to_numpy()
        results = df["result_name"].to_numpy()
        n = len(df)
        for i in range(n):
            if not (str(types[i]).startswith("shot") and results[i] == "success"):
                continue
            scorer = int(players[i])
            scorer_team = teams[i]
            for j in range(i - 1, max(-1, i - 4), -1):
                if teams[j] != scorer_team:
                    break
                if types[j] in ASSIST_TYPES and results[j] == "success":
                    assister = int(players[j])
                    if assister != scorer:
                        lo, hi = (assister, scorer) if assister < scorer else (scorer, assister)
                        if assister < scorer:
                            pair_assists_pq[(lo, hi)] += 1  # p assisted q
                        else:
                            pair_assists_qp[(lo, hi)] += 1  # q assisted p
                    break

    keys = set(pair_goals.keys()) | set(pair_assists_pq.keys()) | set(pair_assists_qp.keys())
    rows = []
    for (lo, hi) in sorted(keys):
        pq = pair_assists_pq.get((lo, hi), 0)
        qp = pair_assists_qp.get((lo, hi), 0)
        rows.append({
            "player_p": lo, "player_q": hi,
            "goals_together": pair_goals.get((lo, hi), 0),
            "assists_pq": pq,
            "assists_qp": qp,
            "assists_together": pq + qp,
        })
    return pd.DataFrame(rows)
