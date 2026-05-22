"""Train P(score) and P(concede) models and compute per-action VAEP.

VAEP(a) = [V_score(s_i) - V_score(s_{i-1} | team_i)]
        + [V_concede(s_{i-1} | team_i) - V_concede(s_i | team_i)]

where V_x(s_{i-1} | team_i) means the predicted value of state s_{i-1} as
seen from team_i's perspective. Since our model is trained from the
*acting team's* perspective (it always treats the acting team as "us"),
when the previous action was by the opposing team we swap the score/concede
predictions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

from .features import build_features


@dataclass
class VaepBundle:
    score_model: HistGradientBoostingClassifier
    concede_model: HistGradientBoostingClassifier
    feature_cols: list[str]
    metrics: dict


def train(spadl: pd.DataFrame, *, n_splits: int = 5, random_state: int = 0) -> VaepBundle:
    X, yS, yC = build_features(spadl)
    cols = list(X.columns)

    # Out-of-fold predictions for calibration check
    groups = spadl.sort_values(["game_id", "period_id", "time_seconds"])["game_id"].to_numpy()
    pS = np.zeros(len(X), dtype=np.float32)
    pC = np.zeros(len(X), dtype=np.float32)
    gkf = GroupKFold(n_splits=n_splits)
    for fold, (tr, te) in enumerate(gkf.split(X, yS, groups=groups)):
        mS = HistGradientBoostingClassifier(
            max_depth=6, max_iter=300, learning_rate=0.05, random_state=random_state
        ).fit(X.iloc[tr], yS.iloc[tr])
        mC = HistGradientBoostingClassifier(
            max_depth=6, max_iter=300, learning_rate=0.05, random_state=random_state
        ).fit(X.iloc[tr], yC.iloc[tr])
        pS[te] = mS.predict_proba(X.iloc[te])[:, 1]
        pC[te] = mC.predict_proba(X.iloc[te])[:, 1]

    metrics = {
        "score_brier": float(brier_score_loss(yS, pS)),
        "score_logloss": float(log_loss(yS, np.clip(pS, 1e-6, 1 - 1e-6))),
        "score_auc": float(roc_auc_score(yS, pS)) if yS.sum() > 0 else None,
        "concede_brier": float(brier_score_loss(yC, pC)),
        "concede_logloss": float(log_loss(yC, np.clip(pC, 1e-6, 1 - 1e-6))),
        "concede_auc": float(roc_auc_score(yC, pC)) if yC.sum() > 0 else None,
        "n_actions": int(len(X)),
        "n_scores": int(yS.sum()),
        "n_concedes": int(yC.sum()),
    }
    # Final models trained on all data
    score_model = HistGradientBoostingClassifier(
        max_depth=6, max_iter=400, learning_rate=0.05, random_state=random_state
    ).fit(X, yS)
    concede_model = HistGradientBoostingClassifier(
        max_depth=6, max_iter=400, learning_rate=0.05, random_state=random_state
    ).fit(X, yC)

    return VaepBundle(score_model, concede_model, cols, metrics)


def attach_vaep(spadl: pd.DataFrame, bundle: VaepBundle) -> pd.DataFrame:
    """Return a copy of spadl with vaep_score, vaep_concede, vaep_value columns."""
    out_parts: list[pd.DataFrame] = []
    for game_id, df in spadl.groupby("game_id", sort=False):
        df = df.sort_values(["period_id", "time_seconds"]).reset_index(drop=True)
        X, _, _ = _features_one(df)
        pS = bundle.score_model.predict_proba(X[bundle.feature_cols])[:, 1]
        pC = bundle.concede_model.predict_proba(X[bundle.feature_cols])[:, 1]
        df = df.copy()
        df["p_score"] = pS
        df["p_concede"] = pC
        df["state_value"] = pS - pC

        # Compute deltas. The previous state's value in the current team's
        # perspective. If prior action was by same team, prior state value
        # is just prior_state_value. If by opposing team, flip score/concede.
        teams = df["team_id"].to_numpy()
        prev_team = np.roll(teams, 1)
        prev_team[0] = teams[0]
        prev_pS = np.roll(pS, 1); prev_pS[0] = pS[0]
        prev_pC = np.roll(pC, 1); prev_pC[0] = pC[0]
        same = (teams == prev_team)
        prev_value_self_persp = np.where(same, prev_pS - prev_pC, prev_pC - prev_pS)
        df["vaep_score"] = pS - np.where(same, prev_pS, prev_pC)
        df["vaep_concede"] = np.where(same, prev_pC, prev_pS) - pC
        df["vaep_value"] = (pS - pC) - prev_value_self_persp
        out_parts.append(df)
    return pd.concat(out_parts, ignore_index=True)


def _features_one(df: pd.DataFrame):
    from .features import _features_one_game
    return _features_one_game(df)


def save_bundle(bundle: VaepBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load_bundle(path: Path) -> VaepBundle:
    return joblib.load(path)
