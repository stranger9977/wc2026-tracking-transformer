"""Combined-corpus training + GIF rendering.

Trains on Metrica match 1 + ALL 10 SkillCorner matches (11 matches total,
~160k frames at 5 Hz) using the dense "thirds" label mode, then renders
the same two GIFs as ``visualize_attention_gif.py`` — buildup + goal-anchored.

Why thirds labels and not events? SkillCorner ships no events; the only way
to use 12× the training data is to fall back on the tracking-derived
target (ball reaches attacking/defensive third in K seconds). Dense and
learnable. Goal-anchored evaluation is still valid because match 2 is
held out untouched.

Outputs:
    output/attention_buildup_combined.gif
    output/attention_goal_combined.gif
    output/training_metrics_combined.json
    output/transformer_combined.ckpt
"""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path

import lightning.pytorch as pl
import numpy as np
import torch
from kloppy import metrica
from torch.utils.data import ConcatDataset, DataLoader, Dataset

warnings.filterwarnings("ignore")

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.metrica import (
    OPEN_DATA_MATCH_IDS as METRICA_IDS,
    load_metrica_match,
)
from wc2026_tracking_transformer.data.loaders.skillcorner import (
    OPEN_DATA_MATCH_IDS as SKILLCORNER_IDS,
    load_skillcorner_match,
)
from wc2026_tracking_transformer.data.schema import PITCH_LENGTH_M, PITCH_WIDTH_M
from wc2026_tracking_transformer.model import NextEventValueLitModule

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUT_DIR.mkdir(exist_ok=True)
BUILDUP_PATH = OUT_DIR / "attention_buildup_combined.gif"
GOAL_PATH = OUT_DIR / "attention_goal_combined.gif"
METRICS_PATH = OUT_DIR / "training_metrics_combined.json"
CKPT_PATH = OUT_DIR / "transformer_combined.ckpt"

# Configuration
K_SECONDS = 10.0
FRAME_RATE_HZ = 5.0
METRICA_STRIDE = 5
SKILLCORNER_STRIDE = 2
THIRD_THRESHOLD = 1.0 / 3.0
FUTURE_WINDOW = int(round(K_SECONDS * FRAME_RATE_HZ))


def thirds_labels(tensors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Build (frames_to_use, labels) with phase-1 thirds targets."""
    n = tensors.shape[0]
    if n <= FUTURE_WINDOW:
        return np.empty((0, *tensors.shape[1:]), dtype=tensors.dtype), np.empty((0, 2), dtype=np.float32)
    ball_x = tensors[:, -1, 0]
    attacks_third = ball_x > THIRD_THRESHOLD
    defends_third = ball_x < -THIRD_THRESHOLD
    usable = n - FUTURE_WINDOW
    labels = np.zeros((usable, 2), dtype=np.float32)
    for i in range(usable):
        w = slice(i + 1, i + 1 + FUTURE_WINDOW)
        labels[i, 0] = float(attacks_third[w].any())
        labels[i, 1] = float(defends_third[w].any())
    return tensors[:usable], labels


class TensorLabelDataset(Dataset):
    def __init__(self, frames: np.ndarray, labels: np.ndarray) -> None:
        self.frames = frames
        self.labels = labels

    def __len__(self) -> int:
        return self.frames.shape[0]

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        return torch.from_numpy(self.frames[idx]), torch.from_numpy(self.labels[idx])


# ---------------------------------------------------------------------------
# 1) Load every match
# ---------------------------------------------------------------------------
print("[1/6] Loading 11 train matches (Metrica 1 + 10 SkillCorner) + Metrica 2 for val …")
train_frames_list: list[np.ndarray] = []
train_labels_list: list[np.ndarray] = []
per_source_stats: dict[str, dict] = {}

t0 = time.time()
# Metrica match 1
frames = list(load_metrica_match("1", sampling_stride=METRICA_STRIDE))
tensors = batch_frames(frames)
f, lbl = thirds_labels(tensors)
train_frames_list.append(f); train_labels_list.append(lbl)
per_source_stats["metrica_1"] = {"frames": int(f.shape[0]), "p_score": float(lbl[:, 0].mean()), "p_concede": float(lbl[:, 1].mean())}
print(f"      metrica_1: {f.shape[0]} usable frames  ({time.time()-t0:.0f}s elapsed)")

# All 10 SkillCorner matches
for mid in SKILLCORNER_IDS:
    t1 = time.time()
    frames = list(load_skillcorner_match(mid, sampling_stride=SKILLCORNER_STRIDE))
    tensors = batch_frames(frames)
    f, lbl = thirds_labels(tensors)
    train_frames_list.append(f); train_labels_list.append(lbl)
    per_source_stats[f"skillcorner_{mid}"] = {"frames": int(f.shape[0]), "p_score": float(lbl[:, 0].mean()), "p_concede": float(lbl[:, 1].mean())}
    print(f"      skillcorner_{mid}: {f.shape[0]} usable frames  ({time.time()-t1:.0f}s)")

# Metrica match 2 → val
frames_val = list(load_metrica_match("2", sampling_stride=METRICA_STRIDE))
tensors_val = batch_frames(frames_val)
f_val, lbl_val = thirds_labels(tensors_val)
per_source_stats["metrica_2_val"] = {"frames": int(f_val.shape[0]), "p_score": float(lbl_val[:, 0].mean()), "p_concede": float(lbl_val[:, 1].mean())}
print(f"      metrica_2 (val): {f_val.shape[0]} usable frames")

train_frames = np.concatenate(train_frames_list, axis=0)
train_labels = np.concatenate(train_labels_list, axis=0)
print(f"\n      TRAIN total: {train_frames.shape[0]} frames")
print(f"      VAL total:   {f_val.shape[0]} frames")
print(f"      Total load time: {time.time()-t0:.0f}s")

# ---------------------------------------------------------------------------
# 2) Train
# ---------------------------------------------------------------------------
print("\n[2/6] Training transformer on combined corpus (6 epochs, CPU) …")
torch.manual_seed(0)
train_ds = TensorLabelDataset(train_frames, train_labels)
val_ds   = TensorLabelDataset(f_val, lbl_val)
train_loader = DataLoader(train_ds, batch_size=256, shuffle=True, num_workers=0)
val_loader   = DataLoader(val_ds,   batch_size=256, shuffle=False, num_workers=0)

lit = NextEventValueLitModule(feature_len=7, model_dim=64, num_heads=4, num_layers=2,
                              learning_rate=5e-4)
trainer = pl.Trainer(
    accelerator="cpu", devices=1, max_epochs=6,
    enable_progress_bar=False, logger=False, enable_checkpointing=False,
    log_every_n_steps=50,
)
trainer.fit(lit, train_loader, val_loader)
lit.eval()

# ---------------------------------------------------------------------------
# 3) Final metrics
# ---------------------------------------------------------------------------
print("\n[3/6] Computing metrics …")
with torch.no_grad():
    all_p, all_y = [], []
    for x, y in val_loader:
        all_p.append(torch.sigmoid(lit(x)))
        all_y.append(y)
    P = torch.cat(all_p).numpy()
    Y = torch.cat(all_y).numpy()


def quick_auc(scores, labels):
    n = len(labels); pos = labels > 0.5
    if pos.sum() == 0 or pos.sum() == n: return float("nan")
    ranks = scores.argsort().argsort() + 1
    return float((ranks[pos].mean() - (pos.sum() + 1) / 2) / (n - pos.sum()))


metrics = {
    "train_frames_total": int(train_frames.shape[0]),
    "val_frames_total": int(f_val.shape[0]),
    "matches_train": list(per_source_stats.keys()),
    "per_source_stats": per_source_stats,
    "val_loss": float(trainer.callback_metrics.get("val_loss", torch.tensor(float("nan"))).item()),
    "val_acc": float(trainer.callback_metrics.get("val_acc", torch.tensor(float("nan"))).item()),
    "val_auc_head0_atk_third": quick_auc(P[:, 0], Y[:, 0]),
    "val_auc_head1_def_third": quick_auc(P[:, 1], Y[:, 1]),
}
with METRICS_PATH.open("w") as fp:
    json.dump(metrics, fp, indent=2)
print(f"      val_loss = {metrics['val_loss']:.3f}  val_acc = {metrics['val_acc']:.3f}")
print(f"      val_AUC(head0/atk-third) = {metrics['val_auc_head0_atk_third']:.3f}")
print(f"      val_AUC(head1/def-third) = {metrics['val_auc_head1_def_third']:.3f}")

torch.save(lit.state_dict(), CKPT_PATH)
print(f"      Checkpoint saved → {CKPT_PATH}")

# ---------------------------------------------------------------------------
# 4) Score Metrica match 2 for clip picking
# ---------------------------------------------------------------------------
print("\n[4/6] Scoring Metrica match 2 frames …")
m2_torch = torch.from_numpy(tensors_val)  # full sequence including last frames
with torch.no_grad():
    encoded, attn = lit.backbone.encode_with_attention(m2_torch)
    logits = lit.head(encoded)
    probs = torch.sigmoid(logits).numpy()
p_attack = probs[:, 0]  # P(ball reaches attacking third in K seconds)
p_defend = probs[:, 1]

sampled_native_frames = np.array([tf.frame_id for tf in frames_val], dtype=np.int64)
raw_m2 = metrica.load_open_data(match_id="2")
frame_meta: dict[int, tuple[list, list]] = {}
for rf in raw_m2.frames:
    items = list(rf.players_data.items())
    frame_meta[int(rf.frame_id)] = (
        [p.jersey_no for p, _ in items],
        [p.team.team_id for p, _ in items],
    )


def gather_window(start: int, end: int):
    ct = m2_torch[start:end]
    cattn = attn[start:end]
    cchem = cattn.mean(dim=(1, 2)).numpy()
    cps = p_attack[start:end]
    cpg = p_defend[start:end]
    cj, ct_ = [], []
    for tf in frames_val[start:end]:
        j, t = frame_meta[tf.frame_id]
        cj.append(j); ct_.append(t)
    return ct, cchem, cps, cpg, cj, ct_


# Buildup
print("\n[5/6] Rendering buildup clip …")
W_BUILD = 60  # 12 s at 5 Hz
score_seq = p_attack + 0.5 * p_defend
peak_idx = int(np.argmax(score_seq))
best_start = max(0, peak_idx - W_BUILD + 1)
b_end = best_start + W_BUILD
print(f"      buildup window: frames {best_start}-{b_end}, peak P(atk_third)={p_attack[peak_idx]:.2f}")
ct, cchem, cps, cpg, cj, ct_ = gather_window(best_start, b_end)


# Goal-anchored
print("\n[6/6] Picking a real goal and rendering …")
from wc2026_tracking_transformer.data.loaders.metrica import load_metrica_events
events = load_metrica_events("2")
goal_rows = events[
    (events["Type"] == "SHOT") & events["Subtype"].astype(str).str.contains("GOAL", na=False)
]
W_GOAL = 75
PRE_FRAMES, POST_FRAMES = 55, W_GOAL - 55
chosen_start = chosen_end = chosen_goal_idx = None
chosen_goal = None
for _, g in goal_rows.iterrows():
    native_goal_f = int(g["Start Frame"])
    diffs = sampled_native_frames - native_goal_f
    post_mask = diffs >= 0
    if not post_mask.any():
        continue
    goal_idx = int(np.where(post_mask)[0].min())
    s = goal_idx - PRE_FRAMES
    e = goal_idx + POST_FRAMES
    if s >= 0 and e < len(frames_val):
        chosen_start, chosen_end = s, e
        chosen_goal_idx = goal_idx
        chosen_goal = g
        break

if chosen_start is not None:
    print(f"      goal @ native frame {int(chosen_goal['Start Frame'])} "
          f"team={chosen_goal['Team']} subtype={chosen_goal['Subtype']}")
    ct_g, cchem_g, cps_g, cpg_g, cj_g, ct_g_ = gather_window(chosen_start, chosen_end)


# Reuse the rendering function
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from clip_renderer import render_clip  # type: ignore

# Re-label the two heads for this combined-thirds model
# (head 0 = ball reaches attacking third, head 1 = defensive third)
render_clip(
    out_path=BUILDUP_PATH,
    clip_tensors=ct, clip_chem=cchem,
    clip_p_shot=cps, clip_p_goal=cpg,
    clip_jerseys=cj, clip_teams=ct_,
    top_banner=f"COMBINED model (11 matches, {train_frames.shape[0]:,} train frames)  ·  12s buildup peak",
    fps=6,
)
print(f"      wrote {BUILDUP_PATH}  ({BUILDUP_PATH.stat().st_size / 1024:.0f} KB)")

if chosen_start is not None:
    render_clip(
        out_path=GOAL_PATH,
        clip_tensors=ct_g, clip_chem=cchem_g,
        clip_p_shot=cps_g, clip_p_goal=cpg_g,
        clip_jerseys=cj_g, clip_teams=ct_g_,
        top_banner=(f"COMBINED model · 11s + 4s around a real goal "
                    f"({chosen_goal['Team']} · {chosen_goal['Subtype']})"),
        fps=6,
        goal_frame_in_clip=chosen_goal_idx - chosen_start,
    )
    print(f"      wrote {GOAL_PATH}  ({GOAL_PATH.stat().st_size / 1024:.0f} KB)")
