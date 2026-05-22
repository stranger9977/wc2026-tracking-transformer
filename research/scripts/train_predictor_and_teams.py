"""Train chemistry predictor and run team builder for every WC22 squad."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chemistry.loaders.pff_paths import players_csv
from chemistry.prediction.features import build_pair_features, load_player_meta
from chemistry.prediction.model import predict_for_pairs, save, train_predictor
from chemistry.teambuilder.builder import best_xi
from chemistry.joint.grid import grid_role


def main() -> None:
    data = Path(__file__).resolve().parents[1] / "data"
    joi = pd.read_parquet(data / "joi.parquet")
    jdi = pd.read_parquet(data / "jdi.parquet")
    pm = pd.read_parquet(data / "minutes" / "pair_minutes.parquet")
    ln = pd.read_parquet(data / "minutes" / "lineups.parquet")
    matches = pd.read_parquet(data / "matches.parquet")
    meta = load_player_meta(players_csv())

    pair_df = build_pair_features(joi, jdi, pm, ln, matches, meta)
    print(f"Pair training rows: {len(pair_df)}")
    pair_df.to_parquet(data / "pair_features.parquet", index=False)

    predictor = train_predictor(pair_df)
    save(predictor, data / "predictor.joblib")
    print("Prediction metrics:")
    for k, v in predictor.metrics.items():
        print(f"  {k}: {v}")

    # Run TeamBuilder for every WC22 squad
    # Build candidates per team: union of starters/subs across this team's matches
    ln["role"] = ln.position.map(grid_role)
    team_candidates = (
        ln[ln.on_seconds > 0]
        .groupby(["team_id", "team_name"], as_index=False)
        .apply(lambda g: g[["player_id", "player_name", "role"]].drop_duplicates(), include_groups=False)
        .reset_index(level=0, drop=True)
    )
    # Quick & dirty: keep a flat dataframe (team_id, team_name, player_id, name, role) one row per player
    flat = ln[ln.on_seconds > 0].copy()
    flat["role"] = flat.position.map(grid_role)
    cand = flat.groupby(["team_id", "team_name", "player_id", "player_name"], as_index=False).agg(
        role=("role", lambda s: s.value_counts().index[0]),
        minutes=("on_seconds", lambda s: s.sum() / 60.0),
    )

    teams_out = []
    for (tid, tname), grp in cand.groupby(["team_id", "team_name"]):
        sub = grp.rename(columns={"player_name": "name"})
        team_joi = joi[joi.team_id == tid]
        team_jdi = jdi[jdi.team_id == tid]
        if len(team_joi) < 5 or len(sub) < 11:
            continue
        try:
            result = best_xi(sub, team_joi, team_jdi, alpha=0.5)
        except Exception as e:
            print(f"skip {tname}: {e}")
            continue
        if result is None:
            continue
        # Resolve names
        names = sub.set_index("player_id").name.to_dict()
        roles = sub.set_index("player_id").role.to_dict()
        # Attach the player's most-common PFF position (LCB / CM / CF / …)
        pos_lookup = (
            ln[ln.team_id == tid].dropna(subset=["position"])
            .groupby("player_id").position
            .agg(lambda s: s.value_counts().index[0])
            .to_dict()
        )
        from chemistry.teams_meta import flag_code as _flag
        teams_out.append({
            "team_id": tid, "team_name": tname,
            "formation": result["formation"], "score": result["score"],
            "flag_code": _flag(tname),
            "players": [
                {"player_id": pid, "name": names.get(pid),
                 "role": roles.get(pid), "position": pos_lookup.get(pid)}
                for pid in result["players"]
            ],
        })

    (data / "team_builder.json").write_text(json.dumps(teams_out, indent=2))
    print(f"\nWrote team_builder.json with {len(teams_out)} teams")
    if teams_out:
        sample = teams_out[0]
        print(f"\nSample: {sample['team_name']} ({sample['formation']}, score={sample['score']:.3f})")
        for p in sample['players']:
            print(f"  {p['role']:>3}  {p['name']}")


if __name__ == "__main__":
    main()
