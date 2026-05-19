"""Pretrain-then-finetune pipeline for real event prediction.

1. Load the combined-corpus backbone checkpoint (trained on 171k frames from
   11 matches with thirds labels). The backbone has learned generic soccer
   structure — which player is where, who's running, what's a defensive
   shape vs. an attacking one.
2. Fine-tune the head on **Metrica's real shot/goal events** from match 1.
   The backbone gets a low LR so its representations don't drift; the head
   gets a higher LR to specialize.
3. Score Metrica match 2 frames with the fine-tuned model.
4. Render the same buildup + goal-anchored GIFs, but now with real
   P(shot) / P(goal) instead of P(ball-reaches-third).

This is the right architecture for the small-event-data problem: get the
representational lift from the big tracking corpus, get the right
objective from the small event corpus.

Outputs:
    output/attention_buildup_finetuned.gif
    output/attention_goal_finetuned.gif
    output/finetune_metrics.json
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import torch
from kloppy import metrica
from torch.utils.data import DataLoader, Dataset

warnings.filterwarnings("ignore")

import lightning.pytorch as pl

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.metrica import (
    goal_and_shot_labels_from_events,
    load_metrica_events,
    load_metrica_match,
)
from wc2026_tracking_transformer.model import NextEventValueLitModule

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUT_DIR.mkdir(exist_ok=True)
CKPT_PATH = OUT_DIR / "transformer_combined.ckpt"
BUILDUP_PATH = OUT_DIR / "attention_buildup_finetuned.gif"
GOAL_PATH = OUT_DIR / "attention_goal_finetuned.gif"
METRICS_PATH = OUT_DIR / "finetune_metrics.json"

K_SECONDS = 15.0
SAMPLING_STRIDE = 5
FRAME_RATE_HZ = 5.0
FUTURE_WINDOW = int(round(K_SECONDS * FRAME_RATE_HZ))


def quick_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    n = len(labels); pos = labels > 0.5
    if pos.sum() == 0 or pos.sum() == n: return float("nan")
    ranks = scores.argsort().argsort() + 1
    return float((ranks[pos].mean() - (pos.sum() + 1) / 2) / (n - pos.sum()))


class EventDataset(Dataset):
    def __init__(self, frames: np.ndarray, labels: np.ndarray) -> None:
        self.frames = frames; self.labels = labels
    def __len__(self) -> int: return self.frames.shape[0]
    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        return torch.from_numpy(self.frames[idx]), torch.from_numpy(self.labels[idx])


def build_event_set(match_id: str) -> tuple[np.ndarray, np.ndarray]:
    frames = list(load_metrica_match(match_id, sampling_stride=SAMPLING_STRIDE))
    if len(frames) <= FUTURE_WINDOW:
        raise RuntimeError(f"too few frames for {match_id}")
    tensors = batch_frames(frames)
    events = load_metrica_events(match_id)
    labels_full = goal_and_shot_labels_from_events(
        events, n_frames_sampled=len(frames),
        k_seconds=K_SECONDS, sampling_stride=SAMPLING_STRIDE,
    )
    usable = len(frames) - FUTURE_WINDOW
    return tensors[:usable], labels_full[:usable]


# ---------------------------------------------------------------------------
# 1) Load checkpoint
# ---------------------------------------------------------------------------
print("[1/6] Loading combined-corpus checkpoint as starting point …")
if not CKPT_PATH.exists():
    print(f"      ERROR: {CKPT_PATH} not found.")
    print(f"      Run scripts/visualize_attention_combined.py first to create it.")
    sys.exit(1)

torch.manual_seed(0)
lit = NextEventValueLitModule(feature_len=7, model_dim=64, num_heads=4, num_layers=2,
                              learning_rate=2e-4)
state = torch.load(CKPT_PATH, map_location="cpu")
lit.load_state_dict(state)
print(f"      loaded {CKPT_PATH}")

# Pre-finetune baseline: how does the combined-only model do on Metrica events?
print("\n[2/6] Pre-finetune baseline on Metrica match 2 events …")
val_frames, val_labels = build_event_set("2")
print(f"      val frames: {val_frames.shape[0]}, "
      f"P(shot)={val_labels[:,0].mean():.4f}, P(goal)={val_labels[:,1].mean():.4f}")

lit.eval()
with torch.no_grad():
    val_x = torch.from_numpy(val_frames)
    val_p_pre = torch.sigmoid(lit(val_x)).numpy()
pre_auc_shot = quick_auc(val_p_pre[:, 0], val_labels[:, 0])
pre_auc_goal = quick_auc(val_p_pre[:, 1], val_labels[:, 1])
print(f"      PRE-finetune AUC: shot={pre_auc_shot:.3f}, goal={pre_auc_goal:.3f}")

# ---------------------------------------------------------------------------
# 3) Fine-tune
# ---------------------------------------------------------------------------
print("\n[3/6] Fine-tuning on Metrica match 1 events …")
train_frames, train_labels = build_event_set("1")
print(f"      train frames: {train_frames.shape[0]}, "
      f"P(shot)={train_labels[:,0].mean():.4f}, P(goal)={train_labels[:,1].mean():.4f}")

train_loader = DataLoader(EventDataset(train_frames, train_labels), batch_size=128, shuffle=True)
val_loader = DataLoader(EventDataset(val_frames, val_labels), batch_size=128, shuffle=False)

# Lower learning rate to preserve backbone representations.
lit.hparams.learning_rate = 1e-4
trainer = pl.Trainer(
    accelerator="cpu", devices=1, max_epochs=8,
    enable_progress_bar=False, logger=False, enable_checkpointing=False,
    log_every_n_steps=50,
)
trainer.fit(lit, train_loader, val_loader)
lit.eval()

# ---------------------------------------------------------------------------
# 4) Post-finetune metrics
# ---------------------------------------------------------------------------
print("\n[4/6] Post-finetune evaluation …")
with torch.no_grad():
    val_p_post = torch.sigmoid(lit(val_x)).numpy()
post_auc_shot = quick_auc(val_p_post[:, 0], val_labels[:, 0])
post_auc_goal = quick_auc(val_p_post[:, 1], val_labels[:, 1])
print(f"      POST-finetune AUC: shot={post_auc_shot:.3f}, goal={post_auc_goal:.3f}")
print(f"      Lift over pre:       shot+{post_auc_shot-pre_auc_shot:+.3f}, goal+{post_auc_goal-pre_auc_goal:+.3f}")

# Cold-start baseline numbers from the original Metrica-only training
COLD_START_AUC_SHOT = 0.569
COLD_START_AUC_GOAL = 0.540

metrics = {
    "approach": "pretrain combined corpus (171k frames, 11 matches), finetune on Metrica match 1 events",
    "val_frames": int(val_frames.shape[0]),
    "val_pos_rate_shot": float(val_labels[:, 0].mean()),
    "val_pos_rate_goal": float(val_labels[:, 1].mean()),
    "pre_finetune_auc_shot": float(pre_auc_shot),
    "pre_finetune_auc_goal": float(pre_auc_goal),
    "post_finetune_auc_shot": float(post_auc_shot),
    "post_finetune_auc_goal": float(post_auc_goal),
    "cold_start_baseline_auc_shot": COLD_START_AUC_SHOT,
    "cold_start_baseline_auc_goal": COLD_START_AUC_GOAL,
    "lift_over_cold_start_shot": float(post_auc_shot - COLD_START_AUC_SHOT),
    "lift_over_cold_start_goal": float(post_auc_goal - COLD_START_AUC_GOAL),
}
with METRICS_PATH.open("w") as fp:
    json.dump(metrics, fp, indent=2)

# ---------------------------------------------------------------------------
# 5) Score match 2 and pick clips
# ---------------------------------------------------------------------------
print("\n[5/6] Scoring all match-2 frames for clip picking …")
m2_frames = list(load_metrica_match("2", sampling_stride=SAMPLING_STRIDE))
m2_torch = torch.from_numpy(batch_frames(m2_frames))
with torch.no_grad():
    encoded, attn = lit.backbone.encode_with_attention(m2_torch)
    probs = torch.sigmoid(lit.head(encoded)).numpy()
p_shot = probs[:, 0]; p_goal = probs[:, 1]
print(f"      P(shot) max = {p_shot.max():.3f}, > 0.30 in {(p_shot>0.30).sum()} frames")
print(f"      P(goal) max = {p_goal.max():.3f}, > 0.10 in {(p_goal>0.10).sum()} frames")

sampled_native_frames = np.array([tf.frame_id for tf in m2_frames], dtype=np.int64)
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
    cps = p_shot[start:end]
    cpg = p_goal[start:end]
    cj, ct_ = [], []
    for tf in m2_frames[start:end]:
        j, t = frame_meta[tf.frame_id]
        cj.append(j); ct_.append(t)
    return ct, cchem, cps, cpg, cj, ct_


# Buildup
W_BUILD = 60
score_seq = p_shot + 2.0 * p_goal
peak_idx = int(np.argmax(score_seq))
b_start = max(0, peak_idx - W_BUILD + 1); b_end = b_start + W_BUILD
print(f"      buildup window: frames {b_start}-{b_end}, peak P(shot)={p_shot[peak_idx]:.2f}")
ct, cchem, cps, cpg, cj, ct_ = gather_window(b_start, b_end)

# Goal-anchored
events = load_metrica_events("2")
goal_rows = events[
    (events["Type"] == "SHOT") & events["Subtype"].astype(str).str.contains("GOAL", na=False)
]
W_GOAL = 75; PRE_FRAMES = 55; POST_FRAMES = W_GOAL - 55
chosen_start = chosen_end = chosen_goal_idx = None
chosen_goal = None
for _, g in goal_rows.iterrows():
    native_goal_f = int(g["Start Frame"])
    diffs = sampled_native_frames - native_goal_f
    post_mask = diffs >= 0
    if not post_mask.any(): continue
    goal_idx = int(np.where(post_mask)[0].min())
    s = goal_idx - PRE_FRAMES; e = goal_idx + POST_FRAMES
    if s >= 0 and e < len(m2_frames):
        chosen_start, chosen_end, chosen_goal_idx, chosen_goal = s, e, goal_idx, g
        break
print(f"      goal anchor: native={int(chosen_goal['Start Frame'])} team={chosen_goal['Team']} {chosen_goal['Subtype']}")

# ---------------------------------------------------------------------------
# 6) Render
# ---------------------------------------------------------------------------
print("\n[6/6] Rendering GIFs …")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from clip_renderer import render_clip  # type: ignore

banner_b = (f"Pretrain→Finetune model · 12s buildup (peak P(shot)={p_shot[peak_idx]:.2f}, "
            f"AUC shot={post_auc_shot:.2f}, goal={post_auc_goal:.2f})")
render_clip(
    out_path=BUILDUP_PATH,
    clip_tensors=ct, clip_chem=cchem,
    clip_p_shot=cps, clip_p_goal=cpg,
    clip_jerseys=cj, clip_teams=ct_,
    top_banner=banner_b,
    fps=6,
)

ct, cchem, cps, cpg, cj, ct_ = gather_window(chosen_start, chosen_end)
banner_g = (f"Pretrain→Finetune model · 11s + 4s around a real goal "
            f"({chosen_goal['Team']} · {chosen_goal['Subtype']})")
render_clip(
    out_path=GOAL_PATH,
    clip_tensors=ct, clip_chem=cchem,
    clip_p_shot=cps, clip_p_goal=cpg,
    clip_jerseys=cj, clip_teams=ct_,
    top_banner=banner_g,
    fps=6,
    goal_frame_in_clip=chosen_goal_idx - chosen_start,
)
print(f"      wrote both GIFs.")
print(f"\nFINAL: pre-finetune AUC shot={pre_auc_shot:.3f}, "
      f"post={post_auc_shot:.3f}  ·  "
      f"goal pre={pre_auc_goal:.3f}, post={post_auc_goal:.3f}")
print(f"       Cold-start (Metrica-events-only) baseline was 0.57/0.54.")
