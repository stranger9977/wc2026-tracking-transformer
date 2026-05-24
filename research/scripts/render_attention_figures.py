"""Render per-team attention-chemistry pitch figures + write a site index.

Reads:
    research/data/attention_chemistry.parquet  (per-match pair attention sums)
    research/data/minutes/lineups.parquet      (player → team mapping)
    research/data/matches.parquet              (team names + colors)
Writes:
    research/site/assets/figures/team_<id>_attention.png  (one per team)
    research/site/data/attention_figures_index.json       (path list for the site)
    research/site/data/attention_pairs.json               (top pairs for the page table)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))

from chemistry.attention.networks import aggregate_team_attention
from chemistry.joint.grid import grid_role
from chemistry.teams_meta import flag_code
from chemistry.viz.attention_pitch import render_all_teams_attention, pair_category


def main() -> None:
    data = REPO / "research" / "data"
    out_dir = REPO / "research" / "site" / "assets" / "figures"
    site_data = REPO / "research" / "site" / "data"
    site_data.mkdir(parents=True, exist_ok=True)

    ac = pd.read_parquet(data / "attention_chemistry.parquet")
    pm = pd.read_parquet(data / "minutes" / "pair_minutes.parquet")
    ln = pd.read_parquet(data / "minutes" / "lineups.parquet")
    matches = pd.read_parquet(data / "matches.parquet")

    print(f"attention_chemistry rows: {len(ac)}, lineups rows: {len(ln)}")

    # Aggregate to per-pair per-90
    agg = aggregate_team_attention(ac, pm, ln, min_minutes=60.0)
    print(f"aggregated pairs (≥60min): {len(agg)}")

    # Render
    metas = render_all_teams_attention(agg, ln, matches, out_dir=out_dir, min_pairs=5)
    print(f"rendered {len(metas)} team figures")

    # Path normalize + attach team_name & flag
    color = matches.set_index("home_id").home_color.to_dict()
    color.update(matches.set_index("away_id").away_color.to_dict())
    tname = ln.drop_duplicates("team_id").set_index("team_id").team_name.to_dict()
    site_root = REPO / "research" / "site"
    index_rows = []
    for m in metas:
        try:
            rel = Path(m["path"]).resolve().relative_to(site_root.resolve())
            rel_path = str(rel)
        except ValueError:
            rel_path = m["path"]
        team_name = tname.get(m["team_id"]) or m["team_name"]
        index_rows.append({
            "team_id": m["team_id"],
            "team_name": team_name,
            "flag_code": flag_code(team_name),
            "color": color.get(m["team_id"], "#666"),
            "n_pairs": m["n_pairs"],
            "path": rel_path,
        })
    (site_data / "attention_figures_index.json").write_text(json.dumps(index_rows, indent=2))
    print(f"wrote attention_figures_index.json with {len(index_rows)} teams")

    # Top pairs across the tournament for the table on the page
    pos = ln.dropna(subset=["position"]).groupby("player_id").position.agg(lambda s: s.value_counts().index[0]).to_dict()
    agg["pos_p"] = agg.player_p.map(pos)
    agg["pos_q"] = agg.player_q.map(pos)
    agg["role_p"] = agg.pos_p.apply(grid_role)
    agg["role_q"] = agg.pos_q.apply(grid_role)
    agg["category"] = agg.apply(lambda r: pair_category(r.pos_p, r.pos_q), axis=1)
    agg["team_name"] = agg.team_id.map(tname)
    agg["flag_code"] = agg.team_name.map(flag_code)

    # Join goals/assists together (event-level VAEP framework, so consistent
    # with the JOI/JDI leaderboards on other tabs).
    pg_path = data / "pair_goals.parquet"
    if pg_path.exists():
        pg = pd.read_parquet(pg_path).copy()
        pg["lo"] = pg[["player_p", "player_q"]].min(axis=1)
        pg["hi"] = pg[["player_p", "player_q"]].max(axis=1)
        pg = pg.groupby(["lo", "hi"], as_index=False).agg(
            goals_together=("goals_together", "sum"),
            assists_together=("assists_together", "sum"),
        )
        agg = agg.merge(pg, left_on=["player_p", "player_q"],
                        right_on=["lo", "hi"], how="left").drop(columns=["lo", "hi"])
        agg["goals_together"] = agg.goals_together.fillna(0).astype(int)
        agg["assists_together"] = agg.assists_together.fillna(0).astype(int)
    else:
        agg["goals_together"] = 0
        agg["assists_together"] = 0

    # Normalize attention to a team-level baseline. The raw per90 number is
    # dominated by who's on the pitch the most + GK-attacker pairings that the
    # attention always covers. We want pairs the model attends to MORE than its
    # average pair within the same team — the chemistry signal, not the
    # "everybody attends to the goalkeeper" baseline.
    team_baseline = (agg.groupby("team_id", as_index=False)
                       .attention_per90.median()
                       .rename(columns={"attention_per90": "team_baseline_per90"}))
    agg = agg.merge(team_baseline, on="team_id", how="left")
    agg["attention_lift"] = agg.attention_per90 / agg.team_baseline_per90.clip(lower=1e-6)

    top = agg.sort_values("attention_lift", ascending=False).head(300).copy()
    top = top[[
        "team_id", "team_name", "flag_code", "player_p", "name_p", "pos_p", "role_p",
        "player_q", "name_q", "pos_q", "role_q",
        "category", "minutes_together",
        "goals_together", "assists_together",
        "attention_total", "attention_per90", "team_baseline_per90", "attention_lift",
    ]]
    (site_data / "attention_pairs.json").write_text(
        json.dumps(top.to_dict(orient="records"), indent=2, default=float)
    )
    print(f"wrote attention_pairs.json with {len(top)} rows "
          f"(off={(top.category=='off').sum()} "
          f"def={(top.category=='def').sum()} "
          f"cross={(top.category=='cross').sum()})")

    # Multi-player group chemistry — top sub-networks of 3 and 4 players per
    # team. Score = sum of within-group pair-attention, normalized by what a
    # random K-player subset would average for the same team.
    from itertools import combinations

    groups: list[dict] = []
    # Lookup: (team, pid_lo, pid_hi) -> attention_per90 + names
    pair_lookup: dict[tuple[str, int, int], dict] = {}
    for r in agg.itertuples(index=False):
        key = (r.team_id, min(r.player_p, r.player_q), max(r.player_p, r.player_q))
        pair_lookup[key] = {
            "attn": float(r.attention_per90),
            "lift": float(r.attention_lift),
        }

    for team_id, team_df in agg.groupby("team_id"):
        team_name = (tname.get(team_id) or "")
        flag = flag_code(team_name)
        # Top-12 players in this team by total attention involvement (limits the
        # search space; C(12,4) = 495).
        player_attn = pd.concat([
            team_df[["player_p", "name_p", "pos_p", "role_p", "attention_per90"]]
                .rename(columns={"player_p": "pid", "name_p": "name",
                                  "pos_p": "pos", "role_p": "role"}),
            team_df[["player_q", "name_q", "pos_q", "role_q", "attention_per90"]]
                .rename(columns={"player_q": "pid", "name_q": "name",
                                  "pos_q": "pos", "role_q": "role"}),
        ]).groupby(["pid", "name", "pos", "role"], as_index=False).attention_per90.sum()
        player_attn = player_attn.sort_values("attention_per90", ascending=False).head(12)
        players = player_attn.to_dict("records")
        if len(players) < 4:
            continue

        team_baseline_v = float(team_df.attention_per90.median())

        for size in (3, 4):
            scored = []
            for combo in combinations(players, size):
                pids = sorted(p["pid"] for p in combo)
                pair_attns = []
                for i in range(size):
                    for j in range(i + 1, size):
                        a, b = sorted([pids[i], pids[j]])
                        k = (team_id, a, b)
                        if k in pair_lookup:
                            pair_attns.append(pair_lookup[k]["attn"])
                if len(pair_attns) < size * (size - 1) // 2 * 0.5:
                    continue  # too few intra-group pairs measured
                avg_pair = sum(pair_attns) / len(pair_attns)
                lift = avg_pair / max(team_baseline_v, 1e-9)
                roles = {p["role"] for p in combo}
                if roles.issubset({"FWD", "MID"}):
                    cat = "off"
                elif roles.issubset({"DEF", "GK"}):
                    cat = "def"
                elif roles & {"FWD", "MID"} and roles & {"DEF", "GK"}:
                    cat = "cross"
                else:
                    cat = "mixed"
                scored.append({
                    "team_id": team_id,
                    "team_name": team_name,
                    "flag_code": flag,
                    "size": size,
                    "category": cat,
                    "members": [{"player_id": int(p["pid"]), "name": p["name"],
                                 "position": p["pos"], "role": p["role"]} for p in combo],
                    "avg_pair_attention_per90": avg_pair,
                    "attention_lift": lift,
                    "n_pairs_observed": len(pair_attns),
                })
            scored.sort(key=lambda x: x["attention_lift"], reverse=True)
            groups.extend(scored[:5])  # top-5 per team per size

    groups.sort(key=lambda x: x["attention_lift"], reverse=True)
    (site_data / "attention_groups.json").write_text(json.dumps(groups, indent=2, default=float))
    print(f"wrote attention_groups.json with {len(groups)} groups "
          f"(size 3: {sum(1 for g in groups if g['size']==3)} "
          f"size 4: {sum(1 for g in groups if g['size']==4)})")


if __name__ == "__main__":
    main()
