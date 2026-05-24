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
from chemistry.viz.attention_pitch import render_all_teams_attention


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
    agg["team_name"] = agg.team_id.map(tname)
    agg["flag_code"] = agg.team_name.map(flag_code)
    top = agg.sort_values("attention_per90", ascending=False).head(200).copy()
    top = top[[
        "team_id", "team_name", "flag_code", "player_p", "name_p", "pos_p",
        "player_q", "name_q", "pos_q", "minutes_together",
        "attention_total", "attention_per90",
    ]]
    (site_data / "attention_pairs.json").write_text(
        json.dumps(top.to_dict(orient="records"), indent=2, default=float)
    )
    print(f"wrote attention_pairs.json with {len(top)} rows")


if __name__ == "__main__":
    main()
