"""Compare VAEP (action-anchored) vs. transformer (frame-anchored) values.

What this script does:

    1. Trains the transformer briefly on Metrica match 1 with shot/goal
       labels (same pattern as ``scripts/visualize_attention_gif.py``).
    2. Trains a VAEP baseline (gradient-boosted score/concede pair) on
       match-1 events.
    3. For every match-2 action, looks up VAEP's value AND the
       transformer's P(shot) at the tracking frame matching the action's
       start_frame.
    4. Reports Spearman correlation and a handful of "disagreement"
       actions (high VAEP / low transformer, and vice versa). These are
       the actions where the transformer's "all 22 players visible"
       advantage either helps or doesn't.
    5. Saves results to ``output/baseline_vaep_comparison.json`` and a
       scatter plot ``output/vaep_vs_ours.png``.

Designed to finish on CPU in a couple of minutes — small model, short
training, all of match 2 fits in memory.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import lightning.pytorch as pl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")

from wc2026_tracking_transformer.baselines.vaep import (
    DEFAULT_K_ACTIONS,
    events_to_actions,
    label_actions,
    predict_vaep,
    train_vaep,
)
from wc2026_tracking_transformer.data import SoccerTrackingDataModule
from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.metrica import (
    load_metrica_events,
    load_metrica_match,
)
from wc2026_tracking_transformer.model import NextEventValueLitModule

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUT_DIR.mkdir(exist_ok=True)
JSON_PATH = OUT_DIR / "baseline_vaep_comparison.json"
PNG_PATH = OUT_DIR / "vaep_vs_ours.png"

SAMPLING_STRIDE = 5            # Metrica 25 Hz → 5 Hz
NATIVE_FRAME_RATE = 25
K_SECONDS = 15.0
MAX_EPOCHS = 8


# ---------------------------------------------------------------------------
# 1) Train transformer on match 1
# ---------------------------------------------------------------------------
print("[1/6] Training transformer on Metrica match 1 (shot+goal labels) …")
torch.manual_seed(0)
dm = SoccerTrackingDataModule(
    source="metrica",
    batch_size=128,
    metrica_sampling_stride=SAMPLING_STRIDE,
    metrica_k_seconds=K_SECONDS,
    metrica_label_mode="events",
)
lit = NextEventValueLitModule(
    feature_len=7, model_dim=64, num_heads=4, num_layers=2,
    learning_rate=5e-4,
)
trainer = pl.Trainer(
    accelerator="cpu", devices=1, max_epochs=MAX_EPOCHS,
    enable_progress_bar=False, logger=False, enable_checkpointing=False,
    log_every_n_steps=50,
)
trainer.fit(lit, datamodule=dm)
lit.eval()
print("      done.")


# ---------------------------------------------------------------------------
# 2) Train VAEP on match 1 events
# ---------------------------------------------------------------------------
print("[2/6] Training VAEP on Metrica match 1 events …")
m1_events = load_metrica_events("1")
m1_actions = events_to_actions(m1_events)
m1_scores, m1_concedes = label_actions(m1_actions, k_actions=DEFAULT_K_ACTIONS)
print(f"      match 1: {len(m1_actions)} actions, "
      f"scores rate={m1_scores.mean():.3f}, concedes rate={m1_concedes.mean():.3f}")
vaep_model = train_vaep(m1_actions, m1_scores, m1_concedes)
print("      done.")


# ---------------------------------------------------------------------------
# 3) Build match 2 actions + VAEP predictions
# ---------------------------------------------------------------------------
print("[3/6] Scoring match 2 actions with VAEP …")
m2_events = load_metrica_events("2")
m2_actions = events_to_actions(m2_events)
m2_scores, m2_concedes = label_actions(m2_actions, k_actions=DEFAULT_K_ACTIONS)
m2_vaep_preds = predict_vaep(vaep_model, m2_actions)
print(f"      match 2: {len(m2_actions)} actions; "
      f"p_score mean={m2_vaep_preds['p_score'].mean():.3f}, "
      f"p_concede mean={m2_vaep_preds['p_concede'].mean():.3f}")


# ---------------------------------------------------------------------------
# 4) Score every match-2 tracking frame with the transformer
# ---------------------------------------------------------------------------
print("[4/6] Scoring all match-2 tracking frames with transformer …")
m2_frames = list(load_metrica_match("2", sampling_stride=SAMPLING_STRIDE))
m2_tensors = batch_frames(m2_frames)
with torch.no_grad():
    logits = lit(torch.from_numpy(m2_tensors))
    probs = torch.sigmoid(logits).numpy()
p_shot_frame = probs[:, 0]
p_goal_frame = probs[:, 1]
# Map sampled idx -> native frame id (1-based, as in events)
sampled_native = np.array([tf.frame_id for tf in m2_frames], dtype=np.int64)
print(f"      {len(m2_frames)} sampled frames; "
      f"P(shot) mean={p_shot_frame.mean():.3f}, "
      f"P(goal) mean={p_goal_frame.mean():.3f}")


def _nearest_sampled_idx(native_frame: int) -> int | None:
    """Find the sampled-frame index whose native frame is closest to (but
    not later than) ``native_frame``."""
    diff = sampled_native - native_frame
    pre_mask = diff <= 0
    if not pre_mask.any():
        return None
    return int(np.where(pre_mask)[0].max())


# ---------------------------------------------------------------------------
# 5) Pair VAEP value with transformer P(shot) per action
# ---------------------------------------------------------------------------
print("[5/6] Pairing VAEP values with transformer scores per action …")
paired_rows: list[dict] = []
for i, action in m2_actions.iterrows():
    sf = int(action["start_frame"])
    idx = _nearest_sampled_idx(sf)
    if idx is None:
        continue
    paired_rows.append({
        "action_id": int(action["action_id"]),
        "period": int(action["period"]),
        "start_frame": sf,
        "team": str(action["team"]),
        "type": str(action["type"]),
        "from_player": str(action["from_player"]) if action["from_player"] is not None else "",
        "to_player": str(action["to_player"]) if action["to_player"] is not None else "",
        "start_x": float(action["start_x"]),
        "start_y": float(action["start_y"]),
        "end_x": float(action["end_x"]),
        "end_y": float(action["end_y"]),
        "p_score_vaep": float(m2_vaep_preds["p_score"].iloc[i]),
        "p_concede_vaep": float(m2_vaep_preds["p_concede"].iloc[i]),
        "vaep_value": float(m2_vaep_preds["vaep_value"].iloc[i]),
        "p_shot_ours": float(p_shot_frame[idx]),
        "p_goal_ours": float(p_goal_frame[idx]),
        "ended_in_goal_next_k": int(m2_scores[i]),
    })
paired = pd.DataFrame(paired_rows)
print(f"      paired {len(paired)} match-2 actions to tracking frames.")


# ---------------------------------------------------------------------------
# 6) Correlations + disagreement examples + scatter plot
# ---------------------------------------------------------------------------
print("[6/6] Correlations + disagreement examples + figure …")

rho_value, p_value = spearmanr(paired["vaep_value"], paired["p_shot_ours"])
rho_pscore, p_pscore = spearmanr(paired["p_score_vaep"], paired["p_shot_ours"])
rho_pgoal,  p_pgoal  = spearmanr(paired["p_score_vaep"], paired["p_goal_ours"])

print(f"      Spearman(vaep_value, ours P(shot)) = {rho_value:.3f}  (p={p_value:.2e})")
print(f"      Spearman(p_score_vaep, ours P(shot)) = {rho_pscore:.3f}")
print(f"      Spearman(p_score_vaep, ours P(goal)) = {rho_pgoal:.3f}")


# Rank-normalize each so "high in A but low in B" is a clean cross-quantile
# disagreement, not just a difference in scale.
def _rankpct(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


paired["rank_vaep"] = _rankpct(paired["vaep_value"])
paired["rank_ours"] = _rankpct(paired["p_shot_ours"])
paired["disagree"] = paired["rank_ours"] - paired["rank_vaep"]


def _format_example(row: pd.Series) -> dict:
    return {
        "action_id": int(row["action_id"]),
        "period": int(row["period"]),
        "start_frame": int(row["start_frame"]),
        "team": row["team"],
        "type": row["type"],
        "from_player": row["from_player"],
        "to_player": row["to_player"],
        "ball_start_xy": [round(row["start_x"], 3), round(row["start_y"], 3)],
        "ball_end_xy": [round(row["end_x"], 3), round(row["end_y"], 3)],
        "vaep_value": round(float(row["vaep_value"]), 4),
        "p_score_vaep": round(float(row["p_score_vaep"]), 4),
        "p_shot_ours": round(float(row["p_shot_ours"]), 4),
        "p_goal_ours": round(float(row["p_goal_ours"]), 4),
        "rank_vaep": round(float(row["rank_vaep"]), 3),
        "rank_ours": round(float(row["rank_ours"]), 3),
        "ended_in_goal_next_k": int(row["ended_in_goal_next_k"]),
    }


# High-VAEP-value actions (top by VAEP, regardless of ours).
top_vaep = paired.sort_values("vaep_value", ascending=False).head(3)
# Transformer sees something VAEP doesn't: high P(shot) but low VAEP rank.
ours_high_vaep_low = paired[paired["rank_vaep"] < 0.5].sort_values(
    "rank_ours", ascending=False
).head(3)
# Inverse: high VAEP, low transformer P(shot).
vaep_high_ours_low = paired[paired["rank_ours"] < 0.5].sort_values(
    "rank_vaep", ascending=False
).head(3)

result = {
    "n_paired_actions": int(len(paired)),
    "n_train_actions": int(len(m1_actions)),
    "k_actions_window": DEFAULT_K_ACTIONS,
    "transformer_train_epochs": MAX_EPOCHS,
    "transformer_train_label_window_seconds": K_SECONDS,
    "spearman_vaep_value_vs_p_shot": {
        "rho": float(rho_value), "p_value": float(p_value),
    },
    "spearman_p_score_vaep_vs_p_shot_ours": {
        "rho": float(rho_pscore), "p_value": float(p_pscore),
    },
    "spearman_p_score_vaep_vs_p_goal_ours": {
        "rho": float(rho_pgoal), "p_value": float(p_pgoal),
    },
    "examples_top_vaep": [_format_example(r) for _, r in top_vaep.iterrows()],
    "examples_ours_high_vaep_low": [_format_example(r) for _, r in ours_high_vaep_low.iterrows()],
    "examples_vaep_high_ours_low": [_format_example(r) for _, r in vaep_high_ours_low.iterrows()],
}

JSON_PATH.write_text(json.dumps(result, indent=2))
print(f"      wrote {JSON_PATH}")


# Scatter plot: x = VAEP value, y = transformer P(shot), colored by whether
# the action ended in a goal in next K.
fig, ax = plt.subplots(figsize=(8, 6), facecolor="#0b1220")
ax.set_facecolor("#0b1220")
goal_mask = paired["ended_in_goal_next_k"].to_numpy() == 1
nogoal_mask = ~goal_mask
ax.scatter(
    paired.loc[nogoal_mask, "vaep_value"],
    paired.loc[nogoal_mask, "p_shot_ours"],
    s=10, alpha=0.35, c="#94a3b8", label="no goal in next K",
)
ax.scatter(
    paired.loc[goal_mask, "vaep_value"],
    paired.loc[goal_mask, "p_shot_ours"],
    s=28, alpha=0.85, c="#fde047", edgecolor="#0b1220", lw=0.6,
    label="goal in next K actions",
)
ax.set_xlabel("VAEP value (P(score) − P(concede))", color="#e9f0ff")
ax.set_ylabel("Transformer P(shot in next 15s)", color="#e9f0ff")
ax.set_title(
    f"VAEP vs Transformer (Metrica match 2)  ·  Spearman ρ = {rho_value:.3f}",
    color="#e9f0ff",
)
ax.tick_params(colors="#94a3b8")
for s in ax.spines.values():
    s.set_color("#94a3b8")
ax.grid(True, color="#1f2c44", lw=0.5)
leg = ax.legend(loc="upper left", framealpha=0.0, labelcolor="#e9f0ff")
fig.tight_layout()
fig.savefig(PNG_PATH, dpi=120, facecolor="#0b1220")
plt.close(fig)
print(f"      wrote {PNG_PATH}")

print()
print("=" * 70)
print(f"Spearman(VAEP value, our P(shot)) on match 2: {rho_value:.3f}")
print(f"n actions paired: {len(paired)}")
print("=" * 70)
