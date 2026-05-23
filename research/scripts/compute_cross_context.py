"""Compute per-player OI/90 in each context (PFF WC22 + every StatsBomb competition).

Pipeline
--------
1. Load PFF SPADL + VAEP-enriched parquet (already exists from earlier runs).
2. For each StatsBomb competition parquet, attach VAEP using the existing
   `vaep_bundle.joblib`.
3. Compute per-player OI/90 per competition:
     OI(p) = sum of VAEP over {pass, cross, dribble, take_on, shot}
     minutes(p) = approximate using events seen × (45min / events-per-half-median)
4. Build pff↔statsbomb player crosswalk from PFF roster + StatsBomb lineups.
5. Emit `cross_context.parquet` with columns:
     pff_player_id, name, position_pff, position_sb,
     wc22_oi_per90, wc22_minutes, statsbomb_competitions (list of dicts),
     biggest_drop_vs_wc22, biggest_lift_vs_wc22.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))

from chemistry.loaders.player_match import build_player_match
from chemistry.loaders.statsbomb import fetch_lineups, fetch_matches
from chemistry.vaep.model import attach_vaep


DATA = REPO / "research" / "data"
SB = DATA / "statsbomb"


def _minutes_from_events(spadl: pd.DataFrame) -> pd.DataFrame:
    """Crude per-player minutes proxy: count distinct minute markers seen.

    StatsBomb doesn't ship lineups in the action df, so we approximate
    on-pitch time as the span of minute-marks a player has events in,
    capped at 95 per match. This is an over-estimate but consistent across
    contexts (so the *delta* in OI/90 is what matters).
    """
    spadl = spadl.copy()
    spadl["minute_bin"] = (spadl.time_seconds // 60).astype(int)
    by_match = spadl.groupby(["game_id", "player_id"]).agg(
        first_min=("minute_bin", "min"),
        last_min=("minute_bin", "max"),
        n_actions=("action_id", "count"),
    ).reset_index()
    by_match["minutes_on"] = (by_match.last_min - by_match.first_min + 1).clip(upper=95)
    out = by_match.groupby("player_id").minutes_on.sum().reset_index()
    out.columns = ["player_id", "minutes"]
    return out


def _oi_per_player(spadl_vaep: pd.DataFrame, *, oi_types=("pass", "cross", "dribble", "take_on", "shot")) -> pd.DataFrame:
    off = spadl_vaep[spadl_vaep.type_name.isin(oi_types)]
    out = off.groupby(["player_id", "player_name"], as_index=False).vaep_value.sum()
    out.columns = ["player_id", "player_name", "oi_total"]
    return out


def _attach_and_aggregate(spadl: pd.DataFrame, bundle, label: str,
                          season: str | None = None) -> pd.DataFrame:
    if spadl.empty:
        return pd.DataFrame()
    enriched = attach_vaep(spadl, bundle)
    oi = _oi_per_player(enriched)
    mins = _minutes_from_events(enriched)
    df = oi.merge(mins, on="player_id", how="left")
    df["minutes"] = df.minutes.fillna(0).clip(lower=1.0)
    df["oi_per90"] = df.oi_total * 90.0 / df.minutes
    df["competition"] = label
    df["season"] = season or ""
    return df


def _harvest_player_names_sb() -> pd.DataFrame:
    """Pull a player_id → name map from every StatsBomb match lineup JSON we've cached."""
    rows = []
    seen = set()
    cache = DATA / "raw_statsbomb" / "lineups"
    for p in sorted(cache.glob("*.json")):
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        for team in data:
            for pl in team.get("lineup", []):
                pid = pl.get("player_id")
                name = pl.get("player_name") or pl.get("player_nickname")
                if pid and name and pid not in seen:
                    rows.append({"statsbomb_player_id": int(pid), "name": name})
                    seen.add(pid)
    return pd.DataFrame(rows)


def _harvest_player_names_from_actions() -> pd.DataFrame:
    """Fallback: derive player_id → name from the action parquets (which we have)."""
    rows = []
    seen = set()
    for p in sorted(SB.glob("*.parquet")):
        if p.name.startswith("matches_"):
            continue
        df = pd.read_parquet(p, columns=["player_id", "player_name"])
        for pid, name in zip(df.player_id, df.player_name):
            if pid and name and int(pid) not in seen:
                rows.append({"statsbomb_player_id": int(pid), "name": name})
                seen.add(int(pid))
    return pd.DataFrame(rows)


def main() -> None:
    print(f"Loading VAEP bundle…")
    bundle = joblib.load(DATA / "vaep_bundle.joblib")

    # --- PFF WC22 (the home base) ---
    print("Loading PFF WC22 VAEP …")
    pff = pd.read_parquet(DATA / "spadl_vaep.parquet")
    lineups = pd.read_parquet(DATA / "minutes" / "lineups.parquet")
    pff_oi = (
        pff[pff.type_name.isin(["pass", "cross", "dribble", "take_on", "shot"])]
        .groupby(["player_id", "player_name"], as_index=False)
        .vaep_value.sum()
        .rename(columns={"vaep_value": "oi_total"})
    )
    pff_min = (
        lineups.groupby("player_id", as_index=False).on_seconds.sum()
        .assign(minutes=lambda d: d.on_seconds / 60.0)
        .drop(columns=["on_seconds"])
    )
    pff_ctx = pff_oi.merge(pff_min, on="player_id", how="left")
    pff_ctx["minutes"] = pff_ctx.minutes.fillna(0).clip(lower=1.0)
    pff_ctx["oi_per90"] = pff_ctx.oi_total * 90.0 / pff_ctx.minutes
    pff_ctx["competition"] = "wc_2022_pff"
    pff_ctx["season"] = "2022"
    pff_ctx = pff_ctx.rename(columns={"player_id": "pff_player_id"})

    # --- StatsBomb competitions ---
    sb_frames: list[pd.DataFrame] = []
    for p in sorted(SB.glob("*.parquet")):
        if p.name.startswith("matches_"):
            continue
        label = p.stem
        print(f"  StatsBomb {label} …")
        df = pd.read_parquet(p)
        if df.empty:
            continue
        sb_ctx = _attach_and_aggregate(df, bundle, label=label)
        sb_frames.append(sb_ctx)
    sb_all = pd.concat(sb_frames, ignore_index=True) if sb_frames else pd.DataFrame()
    print(f"StatsBomb player-competition rows: {len(sb_all)}")

    # --- Player crosswalk ---
    pff_players = (
        lineups[["player_id", "player_name"]]
        .drop_duplicates()
        .rename(columns={"player_id": "pff_player_id", "player_name": "name"})
    )
    sb_players = _harvest_player_names_from_actions()
    print(f"crosswalk inputs: pff={len(pff_players)} sb={len(sb_players)}")
    match = build_player_match(pff_players, sb_players)
    match.to_parquet(DATA / "player_match.parquet", index=False)
    matched_pct = 100 * len(match) / max(len(pff_players), 1)
    print(f"matched {len(match)} of {len(pff_players)} PFF players ({matched_pct:.1f}%)")

    # --- Build cross_context: one row per (pff_player, competition) ---
    # Join SB rows to pff via player_match.statsbomb_player_id
    sb_all = sb_all.rename(columns={"player_id": "statsbomb_player_id"})
    sb_joined = sb_all.merge(match[["pff_player_id", "statsbomb_player_id"]],
                             on="statsbomb_player_id", how="inner")
    sb_joined = sb_joined.rename(columns={
        "player_name": "name_in_source",
    })[["pff_player_id", "name_in_source", "competition", "season",
        "oi_total", "minutes", "oi_per90"]]

    all_rows = pd.concat([
        pff_ctx[["pff_player_id", "player_name", "competition", "season",
                 "oi_total", "minutes", "oi_per90"]]
            .rename(columns={"player_name": "name_in_source"}),
        sb_joined,
    ], ignore_index=True)
    all_rows.to_parquet(DATA / "cross_context.parquet", index=False)
    print(f"cross_context.parquet: {len(all_rows)} rows")

    # --- Summary: WC22 vs club / Euro / Copa deltas ---
    wc = all_rows[all_rows.competition == "wc_2022_pff"].set_index("pff_player_id")
    others = all_rows[all_rows.competition != "wc_2022_pff"].copy()
    others["wc22_oi_per90"] = others.pff_player_id.map(wc.oi_per90)
    others["wc22_minutes"] = others.pff_player_id.map(wc.minutes)
    others["delta_per90"] = others.oi_per90 - others.wc22_oi_per90
    others = others.dropna(subset=["wc22_oi_per90"])

    drops = others.sort_values("delta_per90", ascending=False).head(15)  # WC22 < other (over-performed at club)
    lifts = others.sort_values("delta_per90", ascending=True).head(15)   # WC22 > other (over-performed at WC)

    print("\nLargest +Δ (club / Euro > WC22):")
    print(drops[["pff_player_id", "name_in_source", "competition", "minutes",
                 "oi_per90", "wc22_oi_per90", "delta_per90"]].to_string(index=False))
    print("\nLargest -Δ (WC22 > club / Euro):")
    print(lifts[["pff_player_id", "name_in_source", "competition", "minutes",
                 "oi_per90", "wc22_oi_per90", "delta_per90"]].to_string(index=False))


if __name__ == "__main__":
    main()
