"""Compare our 22-player transformer against Karun Singh's xT baseline.

Setup mirrors :mod:`scripts.visualize_attention_gif`: 8 epochs on Metrica
match 1 with shot+goal event labels at 5 Hz, validate on match 2. The xT
baseline scores each frame purely from the ball's normalized (x, y) — no
players, no velocity, no history.

Outputs:
    output/baseline_xt_comparison.json   - AUC summary + positive counts.
    output/xt_vs_ours.png                - 60 s overlay of both score streams.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import lightning.pytorch as pl
import matplotlib.pyplot as plt
import numpy as np
import torch
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")

from wc2026_tracking_transformer.baselines.xt import xt_per_frame
from wc2026_tracking_transformer.data import SoccerTrackingDataModule
from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.metrica import (
    goal_and_shot_labels_from_events,
    load_metrica_events,
    load_metrica_match,
)
from wc2026_tracking_transformer.model import NextEventValueLitModule

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(exist_ok=True)
JSON_PATH = OUT_DIR / "baseline_xt_comparison.json"
PLOT_PATH = OUT_DIR / "xt_vs_ours.png"


# ---------------------------------------------------------------------------
# 1) Train on match 1 (same recipe as visualize_attention_gif.py)
# ---------------------------------------------------------------------------
print("[1/4] Training the transformer on Metrica match 1 (8 epochs, CPU)...")
torch.manual_seed(0)
dm = SoccerTrackingDataModule(
    source="metrica",
    batch_size=128,
    metrica_sampling_stride=5,
    metrica_k_seconds=15.0,
    metrica_label_mode="events",
)
lit = NextEventValueLitModule(
    feature_len=7, model_dim=64, num_heads=4, num_layers=2,
    learning_rate=5e-4,
)
trainer = pl.Trainer(
    accelerator="cpu", devices=1, max_epochs=8,
    enable_progress_bar=False, logger=False, enable_checkpointing=False,
    log_every_n_steps=50,
)
trainer.fit(lit, datamodule=dm)
lit.eval()

# ---------------------------------------------------------------------------
# 2) Build val tensors + ground-truth labels for match 2
# ---------------------------------------------------------------------------
print("[2/4] Scoring match 2 with both models...")
SAMPLING_STRIDE = 5
K_SECONDS = 15.0
NATIVE_HZ = 25
EFFECTIVE_HZ = NATIVE_HZ / SAMPLING_STRIDE   # 5.0

match2_frames = list(load_metrica_match("2", sampling_stride=SAMPLING_STRIDE))
m2_tensors = batch_frames(match2_frames)             # (N, 23, 7)
n_total = m2_tensors.shape[0]
future_window = int(round(K_SECONDS * EFFECTIVE_HZ))  # 75 sampled frames

events_m2 = load_metrica_events("2")
labels_full = goal_and_shot_labels_from_events(
    events_m2,
    n_frames_sampled=n_total,
    k_seconds=K_SECONDS,
    sampling_stride=SAMPLING_STRIDE,
)
# Trim trailing frames whose 15 s look-ahead spills past the match.
usable = n_total - future_window
val_tensors = m2_tensors[:usable]
val_labels = labels_full[:usable]                    # (usable, 2): [shot, goal]
y_shot = val_labels[:, 0]
y_goal = val_labels[:, 1]
print(
    f"      n_val_frames={usable}  shot positives={int(y_shot.sum())}  "
    f"goal positives={int(y_goal.sum())}"
)

# Our model
with torch.no_grad():
    probs_chunks = []
    BATCH = 256
    for i in range(0, usable, BATCH):
        x = torch.from_numpy(val_tensors[i:i + BATCH])
        probs_chunks.append(torch.sigmoid(lit(x)).numpy())
    ours_probs = np.concatenate(probs_chunks, axis=0)  # (usable, 2)
ours_p_shot = ours_probs[:, 0]
ours_p_goal = ours_probs[:, 1]

# xT baseline (same score for both heads — xT is a single scalar field)
xt_scores = xt_per_frame(val_tensors)

# ---------------------------------------------------------------------------
# 3) AUCs
# ---------------------------------------------------------------------------
print("[3/4] Computing ROC-AUCs...")


def _safe_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """ROC-AUC, returning NaN if labels are degenerate."""
    if labels.sum() == 0 or labels.sum() == labels.size:
        return float("nan")
    return float(roc_auc_score(labels, scores))


our_auc_shot = _safe_auc(ours_p_shot, y_shot)
our_auc_goal = _safe_auc(ours_p_goal, y_goal)
xt_auc_shot = _safe_auc(xt_scores, y_shot)
xt_auc_goal = _safe_auc(xt_scores, y_goal)

results = {
    "our_auc_shot": our_auc_shot,
    "our_auc_goal": our_auc_goal,
    "xt_auc_shot": xt_auc_shot,
    "xt_auc_goal": xt_auc_goal,
    "n_val_frames": int(usable),
    "n_positives_shot": int(y_shot.sum()),
    "n_positives_goal": int(y_goal.sum()),
}
JSON_PATH.write_text(json.dumps(results, indent=2))
print(f"      saved {JSON_PATH}")
for k, v in results.items():
    if isinstance(v, float):
        print(f"      {k:>20s}: {v:.4f}")
    else:
        print(f"      {k:>20s}: {v}")

# ---------------------------------------------------------------------------
# 4) Overlay plot: 60 s window where our model peaks
# ---------------------------------------------------------------------------
print("[4/4] Rendering 60 s overlay plot...")
W = int(round(60 * EFFECTIVE_HZ))   # 300 frames at 5 Hz
score_seq = ours_p_shot + 2.0 * ours_p_goal
peak_idx = int(np.argmax(score_seq))
start = max(0, peak_idx - W // 2)
end = min(usable, start + W)
start = max(0, end - W)

t = np.arange(end - start) / EFFECTIVE_HZ  # seconds

fig, ax_left = plt.subplots(figsize=(11, 4.5), facecolor="#0b1220")
ax_left.set_facecolor("#0b1220")
for s in ax_left.spines.values():
    s.set_color("#94a3b8")
ax_left.tick_params(colors="#94a3b8")
ax_left.set_xlabel("Seconds within 60 s window", color="#94a3b8")
ax_left.set_ylabel("Our model probability", color="#fde047")

ax_left.plot(t, ours_p_shot[start:end], color="#fde047", lw=1.8,
             label="Ours · P(shot in 15s)")
ax_left.plot(t, ours_p_goal[start:end], color="#f87171", lw=1.8,
             label="Ours · P(goal in 15s)")

# Mark where shot/goal labels are positive (ground truth) along the bottom
y0 = ax_left.get_ylim()[0]
shot_marks = np.where(y_shot[start:end] > 0.5)[0]
goal_marks = np.where(y_goal[start:end] > 0.5)[0]
ax_left.scatter(t[shot_marks], np.full_like(shot_marks, y0, dtype=float),
                marker="|", color="#fde047", s=120, label="GT shot in 15s")
ax_left.scatter(t[goal_marks], np.full_like(goal_marks, y0, dtype=float),
                marker="|", color="#f87171", s=120, label="GT goal in 15s")

ax_right = ax_left.twinx()
ax_right.set_facecolor("#0b1220")
for s in ax_right.spines.values():
    s.set_color("#94a3b8")
ax_right.tick_params(colors="#94a3b8")
ax_right.set_ylabel("xT (ball position only)", color="#5eead4")
ax_right.plot(t, xt_scores[start:end], color="#5eead4", lw=1.6, ls="--",
              label="xT · ball position only")

lines_l, labels_l = ax_left.get_legend_handles_labels()
lines_r, labels_r = ax_right.get_legend_handles_labels()
leg = ax_left.legend(
    lines_l + lines_r, labels_l + labels_r,
    loc="upper left", framealpha=0.0, fontsize=8.5,
)
for txt in leg.get_texts():
    txt.set_color("#e9f0ff")

ax_left.set_title(
    f"Ours (22 players) vs xT (ball only) — Metrica match 2 · 60 s window @ peak"
    f"\nAUC shot: ours={our_auc_shot:.3f} vs xT={xt_auc_shot:.3f}   "
    f"AUC goal: ours={our_auc_goal:.3f} vs xT={xt_auc_goal:.3f}",
    color="white", fontsize=11,
)
fig.tight_layout()
fig.savefig(PLOT_PATH, dpi=110, facecolor="#0b1220")
plt.close(fig)
print(f"      saved {PLOT_PATH}")
print("done.")
