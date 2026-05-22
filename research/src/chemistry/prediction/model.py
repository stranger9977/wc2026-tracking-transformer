"""Train and serve JOI90 / JDI90 predictors.

Uses sklearn's HistGradientBoostingRegressor — gradient boosted trees that
handle missing values natively. The paper used CatBoost; for our purposes
the choice of GBM is irrelevant since the result is a learned mapping
(feature vector → predicted chemistry).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import KFold

from .features import feature_columns


@dataclass
class ChemistryPredictor:
    joi_model: HistGradientBoostingRegressor
    jdi_model: HistGradientBoostingRegressor
    feature_cols: list[str]
    metrics: dict


def train_predictor(pair_df: pd.DataFrame, *, n_splits: int = 5, random_state: int = 0) -> ChemistryPredictor:
    cols = feature_columns()
    X = pair_df[cols].astype(float)
    y_joi = pair_df.joi90.astype(float).to_numpy()
    y_jdi = pair_df.jdi90.astype(float).to_numpy()

    # Baseline = predict mean
    baseline_joi = float(np.mean(y_joi))
    baseline_jdi = float(np.mean(y_jdi))
    base_rmse_joi = float(np.sqrt(((y_joi - baseline_joi) ** 2).mean()))
    base_rmse_jdi = float(np.sqrt(((y_jdi - baseline_jdi) ** 2).mean()))

    kf = KFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    pred_joi = np.zeros_like(y_joi)
    pred_jdi = np.zeros_like(y_jdi)
    for tr, te in kf.split(X):
        m_j = HistGradientBoostingRegressor(max_iter=400, max_depth=5, learning_rate=0.05, random_state=random_state)
        m_d = HistGradientBoostingRegressor(max_iter=1000, max_depth=4, learning_rate=0.05, random_state=random_state)
        m_j.fit(X.iloc[tr], y_joi[tr])
        m_d.fit(X.iloc[tr], y_jdi[tr])
        pred_joi[te] = m_j.predict(X.iloc[te])
        pred_jdi[te] = m_d.predict(X.iloc[te])

    metrics = {
        "n_pairs": int(len(X)),
        "joi_baseline_rmse": base_rmse_joi,
        "joi_model_rmse": float(np.sqrt(mean_squared_error(y_joi, pred_joi))),
        "joi_r2": float(r2_score(y_joi, pred_joi)),
        "jdi_baseline_rmse": base_rmse_jdi,
        "jdi_model_rmse": float(np.sqrt(mean_squared_error(y_jdi, pred_jdi))),
        "jdi_r2": float(r2_score(y_jdi, pred_jdi)),
    }
    # Final
    joi_model = HistGradientBoostingRegressor(max_iter=500, max_depth=5, learning_rate=0.05, random_state=random_state).fit(X, y_joi)
    jdi_model = HistGradientBoostingRegressor(max_iter=1000, max_depth=4, learning_rate=0.05, random_state=random_state).fit(X, y_jdi)
    return ChemistryPredictor(joi_model, jdi_model, cols, metrics)


def predict_for_pairs(predictor: ChemistryPredictor, pair_features: pd.DataFrame) -> pd.DataFrame:
    X = pair_features[predictor.feature_cols].astype(float)
    out = pair_features[["player_p", "player_q"]].copy()
    out["pred_joi90"] = predictor.joi_model.predict(X)
    out["pred_jdi90"] = predictor.jdi_model.predict(X)
    return out


def save(p: ChemistryPredictor, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(p, path)


def load(path: Path) -> ChemistryPredictor:
    return joblib.load(path)
