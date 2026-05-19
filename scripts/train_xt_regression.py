"""Train the xT-regression model on a chosen corpus and compare to xT-lookup.

Default: 1 SkillCorner match for train, Metrica match 2 for val. Pass
``--corpus full`` to use the 11-match combined corpus (Metrica 1 + 10
SkillCorner). The "start small, scale up" path the user asked for.

Outputs:
    output/transformer_xt_regression.ckpt
    output/training_metrics_xt.json
    output/attention_buildup_xt.gif
    output/attention_goal_xt.gif
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import lightning.pytorch as pl
import numpy as np
import torch
from kloppy import metrica
from torch.utils.data import DataLoader, Dataset

warnings.filterwarnings("ignore")

from wc2026_tracking_transformer.baselines.xt import (
    future_xt_labels,
    xt_now,
)
from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.metrica import (
    load_metrica_events,
    load_metrica_match,
)
from wc2026_tracking_transformer.data.loaders.pff import (
    list_pff_matches,
    load_pff_match,
)
from wc2026_tracking_transformer.data.loaders.skillcorner import (
    OPEN_DATA_MATCH_IDS as SKILLCORNER_IDS,
    load_skillcorner_match,
)
from wc2026_tracking_transformer.model import XTRegressionLitModule

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUT_DIR.mkdir(exist_ok=True)
CKPT_PATH = OUT_DIR / "transformer_xt_regression.ckpt"
METRICS_PATH = OUT_DIR / "training_metrics_xt.json"
BUILDUP_PATH = OUT_DIR / "attention_buildup_xt.gif"
GOAL_PATH = OUT_DIR / "attention_goal_xt.gif"

K_SECONDS = 10.0
FRAME_RATE_HZ = 5.0
METRICA_STRIDE = 5
SKILLCORNER_STRIDE = 2
PFF_STRIDE = 6   # PFF native is ~30 Hz, so /6 → 5 Hz


class XTDataset(Dataset):
    def __init__(self, frames: np.ndarray, labels: np.ndarray, baselines: np.ndarray) -> None:
        assert frames.shape[0] == labels.shape[0] == baselines.shape[0]
        self.frames = frames; self.labels = labels; self.baselines = baselines

    def __len__(self) -> int:
        return self.frames.shape[0]

    def __getitem__(self, idx: int):
        return (
            torch.from_numpy(self.frames[idx]),
            torch.tensor(self.labels[idx], dtype=torch.float32),
            torch.tensor(self.baselines[idx], dtype=torch.float32),
        )


def build_source(loader_fn, match_id, stride, source_name: str):
    frames = list(loader_fn(match_id, sampling_stride=stride))
    if not frames: return None
    tensors = batch_frames(frames)
    labels = future_xt_labels(tensors, k_seconds=K_SECONDS, frame_rate_hz=FRAME_RATE_HZ)
    if labels.shape[0] == 0:
        return None
    aligned = tensors[: labels.shape[0]]
    baseline = xt_now(aligned)
    return {"name": source_name, "frames": aligned, "labels": labels, "baseline": baseline,
            "tracking_frames": frames}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", choices=("small", "full", "pff"), default="small",
                    help="small = SkillCorner 1886347 + Metrica 1. "
                         "full = 11 Metrica+SkillCorner matches. "
                         "pff = PFF-only with --pff-n total matches.")
    ap.add_argument("--pff-n", type=int, default=0,
                    help="Number of PFF matches to use (0–44). For corpus=pff "
                         "the last 4 are held out as val. For corpus=small/full "
                         "they're ADDED to the training corpus.")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--model-dim", type=int, default=64)
    args = ap.parse_args()

    # ---- Load data ----
    print(f"[1/5] Loading data ({args.corpus} corpus) …")
    t0 = time.time()
    sources: list[dict] = []
    pff_val_ids: list[str] = []
    if args.corpus == "small":
        sources.append(build_source(load_skillcorner_match, "1886347", SKILLCORNER_STRIDE, "skillcorner_1886347"))
        sources.append(build_source(load_metrica_match, "1", METRICA_STRIDE, "metrica_1"))
        val_src = build_source(load_metrica_match, "2", METRICA_STRIDE, "metrica_2_val")
    elif args.corpus == "full":
        sources.append(build_source(load_metrica_match, "1", METRICA_STRIDE, "metrica_1"))
        for mid in SKILLCORNER_IDS:
            sources.append(build_source(load_skillcorner_match, mid, SKILLCORNER_STRIDE, f"skillcorner_{mid}"))
        if args.pff_n > 0:
            pff_matches = list_pff_matches()
            for m in pff_matches[: args.pff_n]:
                mid = m.name
                print(f"      loading PFF match {mid} (stride={PFF_STRIDE} → 5 Hz) …", flush=True)
                t_pff = time.time()
                try:
                    src = build_source(load_pff_match, mid, PFF_STRIDE, f"pff_{mid}")
                    if src is not None:
                        sources.append(src)
                        print(f"        {src['frames'].shape[0]} usable frames ({time.time()-t_pff:.0f}s)")
                except Exception as e:
                    print(f"        SKIP {mid}: {type(e).__name__}: {e}")
        val_src = build_source(load_metrica_match, "2", METRICA_STRIDE, "metrica_2_val")
    elif args.corpus == "pff":
        # PFF-only: train on first (N-4), val on last 4.
        if args.pff_n < 6:
            sys.exit("--corpus pff requires --pff-n >= 6 (need val matches too)")
        pff_matches = list_pff_matches()[: args.pff_n]
        n_val = 4
        train_pff = pff_matches[:-n_val]; val_pff = pff_matches[-n_val:]
        for m in train_pff:
            mid = m.name
            print(f"      loading PFF match {mid} (TRAIN, stride={PFF_STRIDE}) …", flush=True)
            t_pff = time.time()
            try:
                src = build_source(load_pff_match, mid, PFF_STRIDE, f"pff_{mid}")
                if src is not None:
                    sources.append(src)
                    print(f"        {src['frames'].shape[0]} usable frames ({time.time()-t_pff:.0f}s)")
            except Exception as e:
                print(f"        SKIP {mid}: {type(e).__name__}: {e}")
        # Concatenate val matches into one big val_src.
        val_frames_l, val_labels_l, val_baseline_l = [], [], []
        for m in val_pff:
            mid = m.name
            print(f"      loading PFF match {mid} (VAL, stride={PFF_STRIDE}) …", flush=True)
            try:
                vs = build_source(load_pff_match, mid, PFF_STRIDE, f"pff_{mid}_val")
                if vs is not None:
                    val_frames_l.append(vs["frames"])
                    val_labels_l.append(vs["labels"])
                    val_baseline_l.append(vs["baseline"])
                    pff_val_ids.append(mid)
            except Exception as e:
                print(f"        SKIP val {mid}: {type(e).__name__}: {e}")
        if not val_frames_l:
            sys.exit("no val frames loaded")
        val_src = {
            "name": "pff_val_combined",
            "frames": np.concatenate(val_frames_l),
            "labels": np.concatenate(val_labels_l),
            "baseline": np.concatenate(val_baseline_l),
            "tracking_frames": None,
        }
    sources = [s for s in sources if s is not None]
    if val_src is None:
        sys.exit("val source could not load")

    train_frames = np.concatenate([s["frames"] for s in sources])
    train_labels = np.concatenate([s["labels"] for s in sources])
    train_baselines = np.concatenate([s["baseline"] for s in sources])
    val_frames = val_src["frames"]; val_labels = val_src["labels"]; val_baseline = val_src["baseline"]

    print(f"      train: {train_frames.shape[0]} frames from {len(sources)} source(s)")
    print(f"      val:   {val_frames.shape[0]} frames (metrica_2)")
    print(f"      train label range: [{train_labels.min():.4f}, {train_labels.max():.4f}]  mean {train_labels.mean():.4f}")
    print(f"      val   label range: [{val_labels.min():.4f}, {val_labels.max():.4f}]  mean {val_labels.mean():.4f}")
    print(f"      load time: {time.time()-t0:.0f}s")

    # ---- Train ----
    print(f"\n[2/5] Training ({args.epochs} epochs) …")
    torch.manual_seed(0)
    train_loader = DataLoader(
        XTDataset(train_frames, train_labels, train_baselines),
        batch_size=args.batch_size, shuffle=True,
    )
    val_loader = DataLoader(
        XTDataset(val_frames, val_labels, val_baseline),
        batch_size=args.batch_size, shuffle=False,
    )
    lit = XTRegressionLitModule(
        feature_len=7, model_dim=args.model_dim, num_heads=4, num_layers=2,
        learning_rate=5e-4,
    )
    trainer = pl.Trainer(
        accelerator="cpu", devices=1, max_epochs=args.epochs,
        enable_progress_bar=False, logger=False, enable_checkpointing=False,
        log_every_n_steps=50,
    )
    trainer.fit(lit, train_loader, val_loader)
    lit.eval()

    val_loss = float(trainer.callback_metrics.get("val_loss", torch.tensor(float("nan"))).item())
    val_mae = float(trainer.callback_metrics.get("val_mae", torch.tensor(float("nan"))).item())
    val_rho_ours = float(trainer.callback_metrics.get("val_spearman_ours", torch.tensor(float("nan"))).item())
    val_rho_lookup = float(trainer.callback_metrics.get("val_spearman_lookup", torch.tensor(float("nan"))).item())
    val_lift = float(trainer.callback_metrics.get("val_lift_vs_lookup", torch.tensor(float("nan"))).item())
    torch.save(lit.state_dict(), CKPT_PATH)

    metrics = {
        "corpus": args.corpus,
        "epochs": args.epochs,
        "train_frames": int(train_frames.shape[0]),
        "val_frames": int(val_frames.shape[0]),
        "train_label_mean": float(train_labels.mean()),
        "val_label_mean": float(val_labels.mean()),
        "val_loss": val_loss,
        "val_mae": val_mae,
        "val_spearman_ours": val_rho_ours,
        "val_spearman_xt_lookup": val_rho_lookup,
        "val_lift_vs_lookup": val_lift,
        "ckpt_path": str(CKPT_PATH),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"\n[3/5] Results")
    print(f"      val_mae          = {val_mae:.4f}  (xT units; mean label ≈ {val_labels.mean():.4f})")
    print(f"      val_spearman ours= {val_rho_ours:.3f}")
    print(f"      val_spearman lookup baseline = {val_rho_lookup:.3f}")
    print(f"      LIFT over lookup = {val_lift:+.3f}    {'<-- we beat xT' if val_lift > 0 else '<-- xT wins'}")

    # ---- Score match 2 for GIF rendering ----
    print(f"\n[4/5] Scoring full match 2 for clip selection …")
    m2_frames = list(load_metrica_match("2", sampling_stride=METRICA_STRIDE))
    m2_tensors = batch_frames(m2_frames)
    m2_torch = torch.from_numpy(m2_tensors)
    with torch.no_grad():
        encoded, attn = lit.backbone.encode_with_attention(m2_torch)
        preds_full = lit.head(encoded).numpy()
    lookup_full = xt_now(m2_tensors)

    # Buildup clip
    W_BUILD = 60
    peak_idx = int(np.argmax(preds_full))
    b_start = max(0, peak_idx - W_BUILD + 1); b_end = b_start + W_BUILD

    # Goal-anchored clip
    sampled_native_frames = np.array([tf.frame_id for tf in m2_frames], dtype=np.int64)
    events = load_metrica_events("2")
    goal_rows = events[(events["Type"] == "SHOT") & events["Subtype"].astype(str).str.contains("GOAL", na=False)]
    W_GOAL = 75; PRE = 55; POST = W_GOAL - 55
    chosen = None
    for _, g in goal_rows.iterrows():
        diffs = sampled_native_frames - int(g["Start Frame"])
        post = diffs >= 0
        if not post.any(): continue
        gi = int(np.where(post)[0].min())
        s = gi - PRE; e = gi + POST
        if s >= 0 and e < len(m2_frames):
            chosen = (s, e, gi, g); break

    raw_m2 = metrica.load_open_data(match_id="2")
    frame_meta = {int(rf.frame_id): ([p.jersey_no for p, _ in list(rf.players_data.items())],
                                     [p.team.team_id for p, _ in list(rf.players_data.items())])
                  for rf in raw_m2.frames}

    def gather(start, end):
        ct = m2_torch[start:end]
        cattn = attn[start:end]
        cchem = cattn.mean(dim=(1, 2)).numpy()
        cps = preds_full[start:end]
        cpg = lookup_full[start:end]  # baseline overlay
        cj = [frame_meta[tf.frame_id][0] for tf in m2_frames[start:end]]
        ct_ = [frame_meta[tf.frame_id][1] for tf in m2_frames[start:end]]
        return ct, cchem, cps, cpg, cj, ct_

    print(f"\n[5/5] Rendering GIFs …")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from clip_renderer import render_clip  # type: ignore

    ct, cchem, cps, cpg, cj, ct_ = gather(b_start, b_end)
    render_clip(
        out_path=BUILDUP_PATH,
        clip_tensors=ct, clip_chem=cchem,
        clip_p_shot=cps, clip_p_goal=cpg,
        clip_jerseys=cj, clip_teams=ct_,
        top_banner=f"xT-regression model · {args.corpus} corpus · 12s peak (ours vs xT-lookup)",
        fps=6,
        head0_label="Our predicted future-xT (max in next 10s)",
        head1_label="xT-lookup baseline (ball position only)",
    )

    if chosen:
        cs, ce, gi, g = chosen
        ct, cchem, cps, cpg, cj, ct_ = gather(cs, ce)
        render_clip(
            out_path=GOAL_PATH,
            clip_tensors=ct, clip_chem=cchem,
            clip_p_shot=cps, clip_p_goal=cpg,
            clip_jerseys=cj, clip_teams=ct_,
            top_banner=f"xT-regression model · 11s+4s around real goal ({g['Team']} · {g['Subtype']})",
            fps=6,
            goal_frame_in_clip=gi - cs,
            head0_label="Our predicted future-xT",
            head1_label="xT-lookup baseline",
        )

    print(f"\nDONE. {CKPT_PATH.name}, {METRICS_PATH.name}, plus both GIFs.")


if __name__ == "__main__":
    main()
