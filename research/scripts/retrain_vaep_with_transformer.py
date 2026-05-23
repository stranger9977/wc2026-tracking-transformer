"""Re-train VAEP with transformer-derived features and report AUC lift.

Reads:
    research/data/spadl_vaep.parquet      (existing event-only SPADL)
    research/data/transformer_features.parquet  (new features keyed by game_id+action_id)

Writes:
    research/data/vaep_bundle_transformer.joblib
    research/data/vaep_metrics_transformer.json

Reports the score/concede AUC, brier, log-loss vs the baseline bundle.
Target: ≥ 15% relative AUC lift on score and concede.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))

from chemistry.vaep.features import build_features


def main() -> None:
    data = REPO / "research" / "data"
    spadl = pd.read_parquet(data / "spadl_vaep.parquet")
    feat_path = data / "transformer_features.parquet"
    if not feat_path.exists():
        print("transformer_features.parquet not yet built — run "
              "research/scripts/extract_transformer_features.py first.")
        return
    tf = pd.read_parquet(feat_path)

    # Build the existing event-only features + labels
    Xev, yS, yC = build_features(spadl)
    base_cols = list(Xev.columns)
    print(f"Event-only features: {len(base_cols)} cols, {len(Xev)} rows")

    # Join transformer features by (game_id, action_id)
    key = spadl.sort_values(["game_id", "period_id", "time_seconds"]).reset_index(drop=True)[
        ["game_id", "action_id"]
    ]
    Xev_with_key = pd.concat([key.reset_index(drop=True), Xev.reset_index(drop=True)], axis=1)
    merged = Xev_with_key.merge(tf, on=["game_id", "action_id"], how="left")

    new_cols = [c for c in tf.columns if c not in {"game_id", "action_id"}]
    # NaN-fill: if a transformer feature is missing for an action, use the
    # population mean (the GBM handles NaN natively too, but mean-filling
    # keeps the comparison fair).
    for c in new_cols:
        if merged[c].isna().any():
            merged[c] = merged[c].fillna(merged[c].mean())

    feature_cols = base_cols + new_cols
    print(f"Augmented features: {len(feature_cols)} cols ({len(new_cols)} from transformer)")

    X = merged[feature_cols]
    groups = merged["game_id"].to_numpy()

    def cv_metrics(X_: pd.DataFrame, y: pd.Series) -> tuple[float, float, float]:
        gkf = GroupKFold(n_splits=5)
        preds = np.zeros(len(y), dtype=np.float32)
        for tr, te in gkf.split(X_, y, groups=groups):
            m = HistGradientBoostingClassifier(
                max_depth=6, max_iter=300, learning_rate=0.05, random_state=0
            ).fit(X_.iloc[tr], y.iloc[tr])
            preds[te] = m.predict_proba(X_.iloc[te])[:, 1]
        return (
            float(roc_auc_score(y, preds)) if y.sum() > 0 else float("nan"),
            float(brier_score_loss(y, preds)),
            float(log_loss(y, np.clip(preds, 1e-6, 1 - 1e-6))),
        )

    print("\n-- Baseline (event-only) ---------------------------------")
    auc_s_b, brier_s_b, ll_s_b = cv_metrics(X[base_cols], yS)
    auc_c_b, brier_c_b, ll_c_b = cv_metrics(X[base_cols], yC)
    print(f"  score   AUC={auc_s_b:.4f}  brier={brier_s_b:.5f}  logloss={ll_s_b:.5f}")
    print(f"  concede AUC={auc_c_b:.4f}  brier={brier_c_b:.5f}  logloss={ll_c_b:.5f}")

    print("\n-- Augmented (event + transformer) ----------------------")
    auc_s_a, brier_s_a, ll_s_a = cv_metrics(X[feature_cols], yS)
    auc_c_a, brier_c_a, ll_c_a = cv_metrics(X[feature_cols], yC)
    print(f"  score   AUC={auc_s_a:.4f}  brier={brier_s_a:.5f}  logloss={ll_s_a:.5f}")
    print(f"  concede AUC={auc_c_a:.4f}  brier={brier_c_a:.5f}  logloss={ll_c_a:.5f}")

    s_lift = (auc_s_a - auc_s_b) / max(auc_s_b - 0.5, 1e-6) * 100  # lift over random baseline
    c_lift = (auc_c_a - auc_c_b) / max(auc_c_b - 0.5, 1e-6) * 100
    print(f"\n  score   AUC lift over random baseline: {s_lift:+.1f}%")
    print(f"  concede AUC lift over random baseline: {c_lift:+.1f}%")
    abs_s_lift = (auc_s_a - auc_s_b) / auc_s_b * 100
    abs_c_lift = (auc_c_a - auc_c_b) / auc_c_b * 100
    print(f"  score   relative AUC lift: {abs_s_lift:+.2f}%")
    print(f"  concede relative AUC lift: {abs_c_lift:+.2f}%")

    # Train final models on full data
    score_model = HistGradientBoostingClassifier(
        max_depth=6, max_iter=400, learning_rate=0.05, random_state=0
    ).fit(X[feature_cols], yS)
    concede_model = HistGradientBoostingClassifier(
        max_depth=6, max_iter=400, learning_rate=0.05, random_state=0
    ).fit(X[feature_cols], yC)

    bundle = {
        "score_model": score_model,
        "concede_model": concede_model,
        "feature_cols": feature_cols,
        "base_cols": base_cols,
        "transformer_cols": new_cols,
    }
    joblib.dump(bundle, data / "vaep_bundle_transformer.joblib")

    metrics = {
        "baseline": {
            "score": {"auc": auc_s_b, "brier": brier_s_b, "logloss": ll_s_b},
            "concede": {"auc": auc_c_b, "brier": brier_c_b, "logloss": ll_c_b},
        },
        "augmented": {
            "score": {"auc": auc_s_a, "brier": brier_s_a, "logloss": ll_s_a},
            "concede": {"auc": auc_c_a, "brier": brier_c_a, "logloss": ll_c_a},
        },
        "relative_lift_pct": {
            "score": abs_s_lift,
            "concede": abs_c_lift,
        },
        "n_actions": int(len(X)),
        "n_features_base": len(base_cols),
        "n_features_augmented": len(feature_cols),
        "transformer_cols": new_cols,
    }
    (data / "vaep_metrics_transformer.json").write_text(json.dumps(metrics, indent=2))
    print(f"\nWrote bundle + metrics to {data}")


if __name__ == "__main__":
    main()
