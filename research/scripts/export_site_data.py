"""Export site-consumable JSON from the parquet artifacts.

Writes everything the static HTML site needs to research/site/data/.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chemistry.joint.grid import grid_role
from chemistry.loaders.pff_paths import players_csv
from chemistry.prediction.features import load_player_meta
from chemistry.teams_meta import flag_code


def _to_dict_records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe records — handles numpy ints/floats."""
    out = []
    for r in df.to_dict(orient="records"):
        out.append({k: (None if (isinstance(v, float) and np.isnan(v)) else (v.item() if hasattr(v, "item") else v))
                    for k, v in r.items()})
    return out


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    site_data = root / "site" / "data"
    site_data.mkdir(parents=True, exist_ok=True)

    matches = pd.read_parquet(data / "matches.parquet")
    joi = pd.read_parquet(data / "joi.parquet")
    jdi = pd.read_parquet(data / "jdi.parquet")
    lineups = pd.read_parquet(data / "minutes" / "lineups.parquet")
    pm = pd.read_parquet(data / "minutes" / "pair_minutes.parquet")
    spadl_vaep = pd.read_parquet(data / "spadl_vaep.parquet")
    vaep_metrics = json.loads((data / "vaep_metrics.json").read_text())

    # ------------------------------- pairs.json -------------------------------
    # Merge JOI + JDI on canonical pair key
    j = joi.rename(columns={"minutes_together": "minutes_j"})
    j["lo"] = j[["player_p", "player_q"]].min(axis=1)
    j["hi"] = j[["player_p", "player_q"]].max(axis=1)
    d = jdi.rename(columns={"minutes_together": "minutes_d"})
    d["lo"] = d[["player_p", "player_q"]].min(axis=1)
    d["hi"] = d[["player_p", "player_q"]].max(axis=1)
    merged = j.merge(
        d[["lo", "hi", "jdi", "jdi90", "minutes_d"]],
        on=["lo", "hi"], how="outer",
    )
    merged["player_p"] = merged.lo
    merged["player_q"] = merged.hi
    merged = merged.drop(columns=["lo", "hi"])
    # Drop rows without any team information (shouldn't happen, but defensive)
    merged = merged.dropna(subset=["team_id"], how="all") if "team_id" in merged.columns else merged
    # Attach roles from lineups: most-frequent position per player
    pos_lookup = (
        lineups.dropna(subset=["position"])
        .groupby("player_id").position.agg(lambda s: s.value_counts().index[0])
        .to_dict()
    )
    teamname = lineups.drop_duplicates("team_id").set_index("team_id").team_name.to_dict()
    color = matches.set_index("home_id").home_color.to_dict()
    color.update(matches.set_index("away_id").away_color.to_dict())

    merged["minutes_together"] = merged["minutes_j"].fillna(merged["minutes_d"])
    merged["pos_p"] = merged.player_p.map(pos_lookup)
    merged["pos_q"] = merged.player_q.map(pos_lookup)
    merged["role_p"] = merged.pos_p.map(grid_role)
    merged["role_q"] = merged.pos_q.map(grid_role)
    merged["team_name"] = merged.team_id.map(teamname)
    merged["team_color"] = merged.team_id.map(color)
    merged["flag_code"] = merged.team_name.map(flag_code)

    # Merge in goals + assists per pair
    gp_path = root / "data" / "pair_goals.parquet"
    if gp_path.exists():
        gp = pd.read_parquet(gp_path)
        # canonicalize same as merged
        merged = merged.merge(
            gp.rename(columns={"player_p": "_lop", "player_q": "_hip"})[
                ["_lop", "_hip", "goals_together", "assists_together", "assists_pq", "assists_qp"]
            ],
            left_on=["player_p", "player_q"], right_on=["_lop", "_hip"], how="left",
        ).drop(columns=["_lop", "_hip"])
        for col in ("goals_together", "assists_together", "assists_pq", "assists_qp"):
            merged[col] = merged[col].fillna(0).astype(int)
    # Fill numeric NaNs
    for col in ["joi", "joi90", "jdi", "jdi90", "n_interactions", "minutes_together"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
    # Filter to same-team pairs (cross-team rows shouldn't be here in JOI/JDI, but defensive)
    keep = [
        "team_id", "team_name", "team_color", "flag_code",
        "player_p", "name_p", "pos_p", "role_p",
        "player_q", "name_q", "pos_q", "role_q",
        "minutes_together", "n_interactions",
        "joi", "joi90", "jdi", "jdi90",
        "goals_together", "assists_together", "assists_pq", "assists_qp",
    ]
    keep = [c for c in keep if c in merged.columns]
    pairs_out = merged[keep].sort_values("joi90", ascending=False).reset_index(drop=True)
    (site_data / "pairs.json").write_text(json.dumps(_to_dict_records(pairs_out)))
    print(f"pairs.json: {len(pairs_out)} pairs")

    # ------------------------------- teams.json -------------------------------
    teams = []
    for tid, grp in lineups.groupby("team_id"):
        tname = grp.team_name.iloc[0]
        tcolor = color.get(tid, "#888")
        team_joi = joi[joi.team_id == tid]
        team_jdi = jdi[jdi.team_id == tid]
        n_matches = grp.game_id.nunique()
        teams.append({
            "team_id": tid,
            "team_name": tname,
            "color": tcolor,
            "flag_code": flag_code(tname),
            "n_matches": int(n_matches),
            "players_used": int(grp.player_id.nunique()),
            "qualifying_pairs_joi": int(len(team_joi[team_joi.minutes_together >= 60])),
            "qualifying_pairs_jdi": int(len(team_jdi[team_jdi.minutes_together >= 60])),
            "best_joi_pair": (
                team_joi[team_joi.minutes_together >= 60].sort_values("joi90", ascending=False).head(1)[["name_p","name_q","joi90"]].iloc[0].to_dict()
                if len(team_joi[team_joi.minutes_together >= 60]) else None
            ),
            "best_jdi_pair": (
                team_jdi[team_jdi.minutes_together >= 60].sort_values("jdi90", ascending=False).head(1)[["name_p","name_q","jdi90"]].iloc[0].to_dict()
                if len(team_jdi[team_jdi.minutes_together >= 60]) else None
            ),
        })
    teams = sorted(teams, key=lambda t: -t["n_matches"])
    (site_data / "teams.json").write_text(json.dumps(teams, indent=2))
    print(f"teams.json: {len(teams)} teams")

    # ------------------------------- matches.json -------------------------------
    matches_out = matches.copy()
    matches_out["date"] = matches_out.date.astype(str)
    (site_data / "matches.json").write_text(json.dumps(_to_dict_records(matches_out)))

    # ------------------------------- overview.json ------------------------------
    pred_metrics_path = data / "predictor.joblib"
    pred_metrics: dict = {}
    try:
        import joblib
        pred_metrics = joblib.load(pred_metrics_path).metrics
    except Exception as e:
        pred_metrics = {"error": str(e)}

    top_joi = joi[joi.minutes_together >= 90].head(1).iloc[0]
    top_jdi = jdi[jdi.minutes_together >= 90].head(1).iloc[0]
    overview = {
        "n_matches": int(matches.shape[0]),
        "n_teams": int(len(teams)),
        "n_actions": int(len(spadl_vaep)),
        "n_pairs": int(len(pairs_out)),
        "n_goals": int(((spadl_vaep.type_name.str.startswith("shot")) & (spadl_vaep.result_name == "success")).sum()),
        "top_joi_pair": {
            "team": teamname.get(top_joi.team_id), "p": top_joi.name_p, "q": top_joi.name_q,
            "joi90": float(top_joi.joi90), "minutes": float(top_joi.minutes_together),
        },
        "top_jdi_pair": {
            "team": teamname.get(top_jdi.team_id), "p": top_jdi.name_p, "q": top_jdi.name_q,
            "jdi90": float(top_jdi.jdi90), "minutes": float(top_jdi.minutes_together),
        },
        "vaep_metrics": vaep_metrics,
        "predictor_metrics": pred_metrics,
    }
    (site_data / "overview.json").write_text(json.dumps(overview, indent=2))
    print(f"overview.json: {overview['n_matches']} matches, {overview['n_actions']} actions")

    # ------------------------------- team_builder.json --------------------------
    tb = data / "team_builder.json"
    if tb.exists():
        shutil.copy(tb, site_data / "team_builder.json")
        print("team_builder.json copied")

    # ------------------------------- model artifacts ----------------------------
    for fname in ("vaep_bundle.joblib", "predictor.joblib"):
        fp = data / fname
        if fp.exists():
            shutil.copy(fp, site_data / fname)
            print(f"{fname} copied")

    # ------------------------------- cross_chem.json ----------------------------
    # Cross-chemistry: bucket pairs by role-pair combination
    buckets = []
    role_combos = [("FWD","FWD"), ("MID","MID"), ("DEF","DEF"),
                   ("FWD","MID"), ("FWD","DEF"), ("MID","DEF"), ("GK","DEF")]
    for a, b in role_combos:
        mask = ((pairs_out.role_p == a) & (pairs_out.role_q == b)) | \
               ((pairs_out.role_p == b) & (pairs_out.role_q == a))
        sub = pairs_out[mask & (pairs_out.minutes_together >= 60)]
        if sub.empty:
            continue
        buckets.append({
            "role_a": a, "role_b": b, "n_pairs": int(len(sub)),
            "median_joi90": float(sub.joi90.median()), "median_jdi90": float(sub.jdi90.median()),
            "mean_joi90": float(sub.joi90.mean()), "mean_jdi90": float(sub.jdi90.mean()),
            "top_pairs": _to_dict_records(sub.sort_values("joi90", ascending=False).head(5)[
                ["team_name","name_p","name_q","minutes_together","joi90","jdi90"]
            ]),
        })
    (site_data / "cross_chem.json").write_text(json.dumps(buckets, indent=2))
    print(f"cross_chem.json: {len(buckets)} role buckets")

    # ------------------------------- downloads.json -----------------------------
    # CSV exports of the canonical tables for the Downloads tab
    csv_dir = root / "site" / "assets" / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    pairs_out.to_csv(csv_dir / "pairs.csv", index=False)
    joi.to_csv(csv_dir / "joi.csv", index=False)
    jdi.to_csv(csv_dir / "jdi.csv", index=False)
    lineups.to_csv(csv_dir / "lineups.csv", index=False)
    spadl_vaep.to_csv(csv_dir / "spadl_vaep.csv", index=False)
    downloads = [
        {"name": "All chemistry pairs (CSV)", "path": "assets/csv/pairs.csv"},
        {"name": "Joint Offensive Impact (JOI) per pair", "path": "assets/csv/joi.csv"},
        {"name": "Joint Defensive Impact (JDI) per pair", "path": "assets/csv/jdi.csv"},
        {"name": "Lineup table (player × match)", "path": "assets/csv/lineups.csv"},
        {"name": "VAEP-enriched SPADL actions", "path": "assets/csv/spadl_vaep.csv"},
    ]
    (site_data / "downloads.json").write_text(json.dumps(downloads, indent=2))
    print(f"downloads.json + {len(downloads)} CSVs at site/assets/csv/")


if __name__ == "__main__":
    main()
