"""Train VAEP (P-score / P-concede) on PFF SPADL and attach VAEP per action."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chemistry.vaep.model import attach_vaep, save_bundle, train


def main() -> None:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    spadl = pd.read_parquet(data_dir / "spadl_all.parquet")
    print(f"Loaded {len(spadl)} actions from {spadl.game_id.nunique()} matches")
    bundle = train(spadl)
    print("Metrics (5-fold by-game):")
    for k, v in bundle.metrics.items():
        print(f"  {k}: {v}")
    save_bundle(bundle, data_dir / "vaep_bundle.joblib")

    enriched = attach_vaep(spadl, bundle)
    enriched.to_parquet(data_dir / "spadl_vaep.parquet", index=False)

    # Sanity: top VAEP actions
    top = enriched.sort_values("vaep_value", ascending=False).head(15)[
        ["game_id", "period_id", "time_seconds", "team_name", "player_name", "type_name", "result_name", "p_score", "p_concede", "vaep_value"]
    ]
    print("\nTop 15 VAEP actions:")
    print(top.to_string(index=False))

    (data_dir / "vaep_metrics.json").write_text(json.dumps(bundle.metrics, indent=2))


if __name__ == "__main__":
    main()
