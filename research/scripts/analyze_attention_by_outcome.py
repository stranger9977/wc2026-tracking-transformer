"""Outcome-conditional attention analysis.

Reads ``research/data/attention_by_outcome.parquet`` (per-game per-pair
attention sums + frame counts across score/concede/neutral buckets),
joins with positions / team names / minutes-together, and produces:

1. The 3x3 category x bucket mean-attention-per-frame table.
2. Top off-off pairs by score-frame lift ratio.
3. Top def-def pairs by concede-frame lift ratio.
4. Cross-team pair patterns.
5. JSON for the site at ``research/site/data/attention_by_outcome.json``.

The findings markdown is written to
``research/notes/conditional_attention_findings.md``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))

from chemistry.joint.grid import grid_role
from chemistry.teams_meta import flag_code
from chemistry.viz.attention_pitch import pair_category

DATA = REPO / "research" / "data"
SHARD_DIR = DATA / "attention_by_outcome_shards"
COMBINED = DATA / "attention_by_outcome.parquet"
SITE_JSON = REPO / "research" / "site" / "data" / "attention_by_outcome.json"
NOTES_MD = REPO / "research" / "notes" / "conditional_attention_findings.md"

MIN_MINUTES = 60.0
MIN_FRAMES_SCORE = 50      # require pair to have at least this many score-frames co-active
MIN_FRAMES_CONCEDE = 50    # ditto for concede
TOP_N = 20


def combine_shards() -> pd.DataFrame:
    if COMBINED.exists():
        return pd.read_parquet(COMBINED)
    shards = sorted(SHARD_DIR.glob("*.parquet"))
    if not shards:
        raise FileNotFoundError(f"no shards in {SHARD_DIR}")
    df = pd.concat([pd.read_parquet(p) for p in shards], ignore_index=True)
    COMBINED.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(COMBINED, index=False)
    print(f"[combine] {len(shards)} shards -> {COMBINED} ({len(df)} rows)")
    return df


def main() -> int:
    df = combine_shards()
    print(f"loaded {len(df)} per-(game, pair) rows from {df.game_id.nunique()} matches")

    # Sum over matches per unordered pair, same-team only.
    df_same = df[df.same_team].copy()
    df_same["lo"] = df_same[["player_p", "player_q"]].min(axis=1)
    df_same["hi"] = df_same[["player_p", "player_q"]].max(axis=1)

    pair_agg = df_same.groupby(["lo", "hi"], as_index=False).agg(
        team_id=("team_id", "first"),
        name_p=("name_p", "first"),
        name_q=("name_q", "first"),
        attn_score_sum=("attn_score_sum", "sum"),
        attn_score_n=("attn_score_n", "sum"),
        attn_concede_sum=("attn_concede_sum", "sum"),
        attn_concede_n=("attn_concede_n", "sum"),
        attn_neutral_sum=("attn_neutral_sum", "sum"),
        attn_neutral_n=("attn_neutral_n", "sum"),
    ).rename(columns={"lo": "player_p", "hi": "player_q"})

    # Cross-team pairs (one row per (pi, pj) but team_p != team_q).
    df_cross = df[~df.same_team].copy()
    df_cross["lo"] = df_cross[["player_p", "player_q"]].min(axis=1)
    df_cross["hi"] = df_cross[["player_p", "player_q"]].max(axis=1)
    cross_agg = df_cross.groupby(["lo", "hi"], as_index=False).agg(
        name_p=("name_p", "first"),
        name_q=("name_q", "first"),
        attn_score_sum=("attn_score_sum", "sum"),
        attn_score_n=("attn_score_n", "sum"),
        attn_concede_sum=("attn_concede_sum", "sum"),
        attn_concede_n=("attn_concede_n", "sum"),
        attn_neutral_sum=("attn_neutral_sum", "sum"),
        attn_neutral_n=("attn_neutral_n", "sum"),
    ).rename(columns={"lo": "player_p", "hi": "player_q"})

    # Per-frame attention.
    for d in (pair_agg, cross_agg):
        d["attn_score_per_frame"] = d.attn_score_sum / d.attn_score_n.clip(lower=1)
        d["attn_concede_per_frame"] = d.attn_concede_sum / d.attn_concede_n.clip(lower=1)
        d["attn_neutral_per_frame"] = d.attn_neutral_sum / d.attn_neutral_n.clip(lower=1)

    # Minutes together.
    pm = pd.read_parquet(DATA / "minutes" / "pair_minutes.parquet")
    pm_same = pm[pm.same_team].copy()
    pm_same["lo"] = pm_same[["player_p", "player_q"]].min(axis=1)
    pm_same["hi"] = pm_same[["player_p", "player_q"]].max(axis=1)
    pm_agg = pm_same.groupby(["lo", "hi"], as_index=False).minutes_together.sum().rename(
        columns={"lo": "player_p", "hi": "player_q"})
    pair_agg = pair_agg.merge(pm_agg, on=["player_p", "player_q"], how="left")
    pair_agg["minutes_together"] = pair_agg.minutes_together.fillna(0)

    pm_cross = pm[~pm.same_team].copy()
    pm_cross["lo"] = pm_cross[["player_p", "player_q"]].min(axis=1)
    pm_cross["hi"] = pm_cross[["player_p", "player_q"]].max(axis=1)
    pm_cross_agg = pm_cross.groupby(["lo", "hi"], as_index=False).minutes_together.sum().rename(
        columns={"lo": "player_p", "hi": "player_q"})
    cross_agg = cross_agg.merge(pm_cross_agg, on=["player_p", "player_q"], how="left")
    cross_agg["minutes_together"] = cross_agg.minutes_together.fillna(0)

    # Positions / roles / team names / flags / category.
    ln = pd.read_parquet(DATA / "minutes" / "lineups.parquet")
    pos_lookup = (ln.dropna(subset=["position"])
                  .groupby("player_id").position
                  .agg(lambda s: s.value_counts().index[0]).to_dict())
    team_name = ln.drop_duplicates("team_id").set_index("team_id").team_name.to_dict()
    player_team = ln.drop_duplicates("player_id").set_index("player_id").team_id.to_dict()

    for d in (pair_agg, cross_agg):
        d["pos_p"] = d.player_p.map(pos_lookup)
        d["pos_q"] = d.player_q.map(pos_lookup)
        d["role_p"] = d.pos_p.apply(grid_role)
        d["role_q"] = d.pos_q.apply(grid_role)
        d["category"] = d.apply(lambda r: pair_category(r.pos_p, r.pos_q), axis=1)

    pair_agg["team_name"] = pair_agg.team_id.map(team_name)
    pair_agg["flag_code"] = pair_agg.team_name.map(flag_code)
    # Cross-team: capture both teams.
    cross_agg["team_p_id"] = cross_agg.player_p.map(player_team)
    cross_agg["team_q_id"] = cross_agg.player_q.map(player_team)
    cross_agg["team_p_name"] = cross_agg.team_p_id.map(team_name)
    cross_agg["team_q_name"] = cross_agg.team_q_id.map(team_name)

    # Filter to qualifying pairs.
    qual = pair_agg[
        (pair_agg.minutes_together >= MIN_MINUTES)
        & (pair_agg.attn_score_n >= MIN_FRAMES_SCORE)
        & (pair_agg.attn_neutral_n >= MIN_FRAMES_SCORE)
    ].copy()
    qual_concede = pair_agg[
        (pair_agg.minutes_together >= MIN_MINUTES)
        & (pair_agg.attn_concede_n >= MIN_FRAMES_CONCEDE)
        & (pair_agg.attn_neutral_n >= MIN_FRAMES_CONCEDE)
    ].copy()

    qual["lift_score"] = qual.attn_score_per_frame / qual.attn_neutral_per_frame.clip(lower=1e-9)
    qual_concede["lift_concede"] = qual_concede.attn_concede_per_frame / qual_concede.attn_neutral_per_frame.clip(lower=1e-9)

    # ============== Q1: 3x3 mean-attn-per-frame by category x bucket ==============
    # Weighted mean per category: sum of per-frame attention across pairs,
    # weighted by number of frames per pair (so a pair with 10000 frames in
    # neutral but 5 in score doesn't dominate).
    rows_q1 = []
    qual_all = pair_agg[pair_agg.minutes_together >= MIN_MINUTES].copy()
    for cat in ("off", "def", "cross"):
        sub = qual_all[qual_all.category == cat]
        for bucket in ("score", "concede", "neutral"):
            tot_sum = sub[f"attn_{bucket}_sum"].sum()
            tot_n = sub[f"attn_{bucket}_n"].sum()
            mean = float(tot_sum / tot_n) if tot_n > 0 else float("nan")
            rows_q1.append({"category": cat, "bucket": bucket,
                            "mean_attn_per_frame": mean,
                            "n_pair_frames": int(tot_n),
                            "n_pairs": int(len(sub))})
    df_q1 = pd.DataFrame(rows_q1)
    pivot_q1 = df_q1.pivot(index="category", columns="bucket", values="mean_attn_per_frame")[
        ["score", "concede", "neutral"]
    ].reindex(["off", "def", "cross"])

    print("\n=== Q1: Mean attention per frame, category x bucket (same-team pairs) ===")
    print(pivot_q1.to_string(float_format=lambda v: f"{v:.4f}"))

    # ============== Q2: top off-off by score lift ==============
    off_q = qual[qual.category == "off"].sort_values("lift_score", ascending=False).head(TOP_N).copy()
    print(f"\n=== Q2: Top {TOP_N} off-off pairs by score-frame lift (attn_score / attn_neutral) ===")
    print(f"{'#':>2}  {'team':<14} {'pair':<55} {'min':>5}  {'score/f':>7}  {'neutral/f':>9}  {'lift':>5}")
    for i, r in enumerate(off_q.itertuples(index=False), 1):
        pair_str = f"{r.name_p} + {r.name_q}"
        print(f"{i:>2}  {(r.team_name or '')[:14]:<14} {pair_str[:55]:<55} "
              f"{r.minutes_together:>5.0f}  {r.attn_score_per_frame:>7.4f}  "
              f"{r.attn_neutral_per_frame:>9.4f}  {r.lift_score:>5.2f}x")

    # ============== Q3: top def-def by concede lift ==============
    def_q = qual_concede[qual_concede.category == "def"].sort_values(
        "lift_concede", ascending=False).head(TOP_N).copy()
    print(f"\n=== Q3: Top {TOP_N} def-def pairs by concede-frame lift ===")
    print(f"{'#':>2}  {'team':<14} {'pair':<55} {'min':>5}  {'concede/f':>9}  {'neutral/f':>9}  {'lift':>5}")
    for i, r in enumerate(def_q.itertuples(index=False), 1):
        pair_str = f"{r.name_p} + {r.name_q}"
        print(f"{i:>2}  {(r.team_name or '')[:14]:<14} {pair_str[:55]:<55} "
              f"{r.minutes_together:>5.0f}  {r.attn_concede_per_frame:>9.4f}  "
              f"{r.attn_neutral_per_frame:>9.4f}  {r.lift_concede:>5.2f}x")

    # ============== Q4: cross-team patterns ==============
    cross_qual = cross_agg[
        (cross_agg.minutes_together >= MIN_MINUTES)
        & (cross_agg.attn_score_n >= MIN_FRAMES_SCORE)
        & (cross_agg.attn_neutral_n >= MIN_FRAMES_SCORE)
    ].copy()
    cross_qual["lift_score"] = cross_qual.attn_score_per_frame / cross_qual.attn_neutral_per_frame.clip(lower=1e-9)
    cross_top = cross_qual.sort_values("lift_score", ascending=False).head(15).copy()
    print(f"\n=== Q4: Top 15 cross-team pairs by score-frame lift ===")
    print(f"{'#':>2}  {'pair':<55} {'teams':<28} {'min':>5}  {'lift':>5}")
    for i, r in enumerate(cross_top.itertuples(index=False), 1):
        teams = f"{(r.team_p_name or '')[:13]}/{(r.team_q_name or '')[:13]}"
        print(f"{i:>2}  {f'{r.name_p} + {r.name_q}'[:55]:<55} {teams:<28} "
              f"{r.minutes_together:>5.0f}  {r.lift_score:>5.2f}x")

    # ============== Write site JSON ==============
    # Site needs: same-team pairs with category, lift_score, attn_*_per_frame,
    # minutes, names, flag. Sort by lift_score desc.
    site_qual = qual.copy()
    site_qual["lift_concede"] = site_qual.attn_concede_per_frame / site_qual.attn_neutral_per_frame.clip(lower=1e-9)
    site_qual = site_qual.sort_values("lift_score", ascending=False).head(500).copy()
    site_cols = [
        "team_id", "team_name", "flag_code",
        "player_p", "name_p", "pos_p", "role_p",
        "player_q", "name_q", "pos_q", "role_q",
        "category", "minutes_together",
        "attn_score_per_frame", "attn_concede_per_frame", "attn_neutral_per_frame",
        "attn_score_n", "attn_concede_n", "attn_neutral_n",
        "lift_score", "lift_concede",
    ]
    site_rows = []
    for r in site_qual[site_cols].itertuples(index=False):
        d = r._asdict()
        # Cast numpy → python
        for k, v in list(d.items()):
            if isinstance(v, (np.integer,)):
                d[k] = int(v)
            elif isinstance(v, (np.floating,)):
                d[k] = float(v) if np.isfinite(v) else None
            elif v is pd.NA:
                d[k] = None
        site_rows.append(d)
    SITE_JSON.parent.mkdir(parents=True, exist_ok=True)
    SITE_JSON.write_text(json.dumps(site_rows, indent=1))
    print(f"\nwrote {len(site_rows)} pairs -> {SITE_JSON}")

    # ============== Write findings markdown ==============
    md_lines = [
        "# Conditional attention findings",
        "",
        "Per-pair attention from the frame-VAEP transformer (2 layers x 4 heads, "
        "mean over layers + heads), bucketed by frame outcome label:",
        "- **score**: y_score == 1 (team in possession scores within 10 s)",
        "- **concede**: y_concede == 1",
        "- **neutral**: both labels 0",
        "",
        f"Filters: same-team pairs with minutes_together >= {MIN_MINUTES} and "
        f">= {MIN_FRAMES_SCORE} bucket-frames in both numerator and denominator.",
        "",
        "## Q1 - Mean attention per frame, category x bucket (same-team)",
        "",
        "| Category | score | concede | neutral |",
        "|---|---:|---:|---:|",
    ]
    for cat in ("off", "def", "cross"):
        row = pivot_q1.loc[cat]
        md_lines.append(
            f"| {cat} | {row['score']:.4f} | {row['concede']:.4f} | {row['neutral']:.4f} |"
        )
    md_lines += [
        "",
        f"## Q2 - Top {TOP_N} off-off pairs by score-frame lift",
        "",
        "These are off-off pairs the model attends to above its own neutral baseline "
        "specifically when scoring is imminent.",
        "",
        "| # | Team | Pair | Min | score/f | neutral/f | Lift |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(off_q.itertuples(index=False), 1):
        md_lines.append(
            f"| {i} | {r.team_name or ''} | {r.name_p} + {r.name_q} | "
            f"{r.minutes_together:.0f} | {r.attn_score_per_frame:.4f} | "
            f"{r.attn_neutral_per_frame:.4f} | **{r.lift_score:.2f}x** |"
        )

    md_lines += [
        "",
        f"## Q3 - Top {TOP_N} def-def pairs by concede-frame lift",
        "",
        "Sanity check: defensive pairs SHOULD fire above baseline when conceding is imminent.",
        "",
        "| # | Team | Pair | Min | concede/f | neutral/f | Lift |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(def_q.itertuples(index=False), 1):
        md_lines.append(
            f"| {i} | {r.team_name or ''} | {r.name_p} + {r.name_q} | "
            f"{r.minutes_together:.0f} | {r.attn_concede_per_frame:.4f} | "
            f"{r.attn_neutral_per_frame:.4f} | **{r.lift_concede:.2f}x** |"
        )

    md_lines += [
        "",
        "## Q4 - Top 15 cross-team pairs by score-frame lift",
        "",
        "| # | Pair | Teams | Min | Lift |",
        "|---:|---|---|---:|---:|",
    ]
    for i, r in enumerate(cross_top.itertuples(index=False), 1):
        md_lines.append(
            f"| {i} | {r.name_p} + {r.name_q} | "
            f"{r.team_p_name} / {r.team_q_name} | "
            f"{r.minutes_together:.0f} | **{r.lift_score:.2f}x** |"
        )

    NOTES_MD.parent.mkdir(parents=True, exist_ok=True)
    NOTES_MD.write_text("\n".join(md_lines) + "\n")
    print(f"wrote findings -> {NOTES_MD}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
