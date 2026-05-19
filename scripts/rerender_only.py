"""Re-render the two GIFs from a saved xT-regression checkpoint.

Skips training entirely — useful for iterating on the visualization.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import torch
from kloppy import metrica

warnings.filterwarnings("ignore")

from wc2026_tracking_transformer.baselines.xt import xt_now
from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.metrica import (
    load_metrica_events,
    load_metrica_match,
)
from wc2026_tracking_transformer.model import XTRegressionLitModule

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
CKPT = OUT_DIR / "transformer_xt_regression.ckpt"
BUILDUP = OUT_DIR / "attention_buildup_xt.gif"
GOAL = OUT_DIR / "attention_goal_xt.gif"

print("Loading checkpoint …")
lit = XTRegressionLitModule(feature_len=7, model_dim=96, num_heads=4, num_layers=2)
lit.load_state_dict(torch.load(CKPT, map_location="cpu"))
lit.eval()

print("Scoring Metrica match 2 …")
frames = list(load_metrica_match("2", sampling_stride=5))
tensors = batch_frames(frames)
m2 = torch.from_numpy(tensors)
with torch.no_grad():
    encoded, attn = lit.backbone.encode_with_attention(m2)
    preds = lit.head(encoded).numpy()
lookup = xt_now(tensors)

sampled_native = np.array([tf.frame_id for tf in frames], dtype=np.int64)
raw = metrica.load_open_data(match_id="2")
fmeta = {int(rf.frame_id): ([p.jersey_no for p, _ in rf.players_data.items()],
                            [p.team.team_id for p, _ in rf.players_data.items()])
         for rf in raw.frames}


def gather(s, e):
    ct = m2[s:e]
    cattn = attn[s:e]
    cchem = cattn.mean(dim=(1, 2)).numpy()
    cps = preds[s:e]; cpg = lookup[s:e]
    cj = [fmeta[tf.frame_id][0] for tf in frames[s:e]]
    ct_ = [fmeta[tf.frame_id][1] for tf in frames[s:e]]
    return ct, cchem, cps, cpg, cj, ct_


# Buildup
W_BUILD = 60
peak = int(np.argmax(preds))
b_s = max(0, peak - W_BUILD + 1); b_e = b_s + W_BUILD

# Goal-anchored
events = load_metrica_events("2")
goals = events[(events["Type"] == "SHOT") & events["Subtype"].astype(str).str.contains("GOAL", na=False)]
W_GOAL = 75; PRE = 55
chosen = None
for _, g in goals.iterrows():
    diffs = sampled_native - int(g["Start Frame"])
    if not (diffs >= 0).any(): continue
    gi = int(np.where(diffs >= 0)[0].min())
    s, e = gi - PRE, gi + (W_GOAL - PRE)
    if s >= 0 and e < len(frames):
        chosen = (s, e, gi, g); break

print("Rendering …")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from clip_renderer import render_clip  # type: ignore

ct, cchem, cps, cpg, cj, ct_ = gather(b_s, b_e)
render_clip(
    out_path=BUILDUP, clip_tensors=ct, clip_chem=cchem,
    clip_p_shot=cps, clip_p_goal=cpg, clip_jerseys=cj, clip_teams=ct_,
    top_banner="xT-regression · 11-match corpus · 12s peak window",
    fps=6,
    head0_label="Our predicted future-xT", head1_label="xT-lookup baseline",
)
print(f"  wrote {BUILDUP.name}")

if chosen:
    s, e, gi, g = chosen
    ct, cchem, cps, cpg, cj, ct_ = gather(s, e)
    render_clip(
        out_path=GOAL, clip_tensors=ct, clip_chem=cchem,
        clip_p_shot=cps, clip_p_goal=cpg, clip_jerseys=cj, clip_teams=ct_,
        top_banner=f"xT-regression · 11s+4s around real goal ({g['Team']} · {g['Subtype']})",
        fps=6, goal_frame_in_clip=gi - s,
        head0_label="Our predicted future-xT", head1_label="xT-lookup baseline",
    )
    print(f"  wrote {GOAL.name}")
