# Frame-by-frame VAEP from the tracking transformer — proposal

Status: scoping. Author: research agent. Target: convince ourselves an afternoon-scale demo will hold up before scaling.

## 1. What we replace

Today's `~/wc2026-chemistry` pipeline computes per-pair JOI/JDI by attributing **SPADL-action-level VAEP** to involved players. That throws away ~95 % of the match (no SPADL action ≈ no signal) and ignores any off-ball runner.

Our checkpoint `output/transformer_xt_regression.ckpt` already emits a scalar **per-frame xT prediction** at 5 Hz (val ρ = 0.714 vs xT-lookup 0.616, +0.098 lift, see `output/training_metrics_xt.json`). Calling this scalar `V_t`, the bridge to chemistry is:

**Design A — Frame-delta credit assignment (v1 pick).** Compute `ΔV_t = V_{t+Δ} − V_t` over a short horizon (e.g. Δ = 1 s = 5 frames). Distribute `ΔV_t` across the 22 player tokens using **attention from the ball token** at layer/head-averaged weight `a_t(ball → i)` from `encode_with_attention` (`src/wc2026_tracking_transformer/model/transformer.py:83`). A pair's chemistry credit on frame `t` is `c_t(i,j) = a_t(ball→i) · a_t(ball→j) · ΔV_t` when `ΔV_t > 0` and same logic with sign flip for defensive value. Accumulate over a match → per-pair VAEP-equivalent.

**Design B — Counterfactual ablation.** For each player slot `i`, re-run the model with token `i` replaced by a placeholder (e.g. midfield league-average dummy or a learned `[MASK]` token). `V_t − V_t^{−i}` is `i`'s marginal value at frame `t`; pair value = `V_t − V_t^{−i,−j}` minus singles.

**v1 picks Design A.** It needs one forward pass per frame, the attention tensor is already a product (CLAUDE.md: "Attention extraction is the product, not a debug feature"), and the signal is dense by construction. We will benchmark against Design B on a single clip as a sanity check (see §5).

## 2. Off-ball value, made concrete

Consider a France counter at minute 80 of 10517 (final): Mbappé carries near halfway, ball-xT lookup ≈ 0.04. A second French winger drifts wide-and-deep, dragging Otamendi. Three frames later the ball is still at Mbappé's feet (ball-xT-lookup barely moves, ~0.05) but our `V_t` jumps to 0.18 because the model sees that **two attackers + the dragged defender created an open lane**. Δ`V` = 0.13. Attention from the ball token splits ~0.30 to Mbappé, ~0.25 to the decoy winger, ~0.10 to the dragged defender. Pair credit `c(Mbappé, decoy) = 0.30·0.25·0.13 ≈ 0.0098 xT-units` accrued on that single frame — SPADL/VAEP records *nothing* during this window because no event has fired. This is the "off-ball" pixel the user wants illuminated.

## 3. Visualizations

1. **xT-field heatmap + dots** — already shipped via `scripts/clip_renderer.py:44` (`draw_pitch`). Reuse unchanged.
2. **Chemistry-over-time edges**: for each frame, draw a line between the top-1 attended pair, line width ∝ `c_t(i,j)`, color = same-team gold / cross-team orange (palette already in `clip_renderer.py:30`). Animate at 5 Hz.
3. **Scrubbable single-clip viewer**: matplotlib (or quick Plotly) panel with `V_t`, xT-lookup, and a stacked bar of top-3 pair credits over the clip. Reuses the existing two-line prob chart pattern in `render_clip`.

## 4. What to demo first

Match: **PFF 10517, Argentina–France WC22 final** (`Metadata/10517.json` — confirmed Argentina home/France away, Lusail). Clip: a **30 s window around Di María's 36th-minute goal** (the Argentina move from MacAllister's interception to the finish — at least four off-ball runs, three involved passers). Argentina starts with low ball-xT (own half) and ends at ~0.30; the frame-delta will fire hard and the credit should resolve cleanly across the MacAllister → Álvarez → Mac Allister → Di María chain.

Afternoon-scale build: ~90 lines wrapping `lit.backbone.encode_with_attention`, computing `ΔV_t` and `c_t(i,j)`, then handing arrays to `render_clip`. Output: one GIF, one JSON of top pairs for that clip. If the top pair is `(Di María, Mac Allister)` we ship it.

## 5. Risks / open questions

- **Target leakage.** `future_xt_labels(... K=10s)` (see `train_xt_regression.py:57`) is by construction forward-looking — that's the desired property, not leakage. Goals are not in the label; only the xT-grid-value of the ball's future location is.
- **Is attention a legitimate credit signal?** It is a *correlate*, not a causal attribution. Jain & Wallace (2019, "Attention is not Explanation") and Wiegreffe & Pinter (2019, rebuttal) bracket the literature: attention is fine as a *ranking signal* over inputs the model conditioned on; it is not a guaranteed causal weight. Design B (counterfactual ablation) is closer to causal — Karun will prefer it. Plan: ship Design A v1, run B on the demo clip, compare top pairs. If top-5 overlap > 3/5 we're done; otherwise A needs calibration (e.g. multiply by per-token gradient × attention).
- **Frame-delta vs ablation.** A is cheap and dense, B is interpretable and ~22× slower per frame. We give Karun both numbers on the same clip.

## 6. Concrete first PR

- `src/wc2026_tracking_transformer/credit/__init__.py` — new module, package marker.
- `src/wc2026_tracking_transformer/credit/frame_delta.py` — `compute_frame_delta(V, horizon_frames)`; `distribute_credit(attn_ball_row, dV)`; `accumulate_pairs(credits_per_frame, jerseys, teams)`.
- `src/wc2026_tracking_transformer/credit/ablation.py` — `marginal_value(lit, tensors, slot_idx, mask_token)`; `pair_marginal(lit, tensors, i, j)`. Optional in v1, used only for sanity check.
- `scripts/demo_frame_vaep.py` — load ckpt, score PFF 10517, slice the Di María goal window (use event timing or hardcoded frame range), compute pair credits via Design A, render GIF + write `output/frame_vaep_10517_dimaria.json`.
- `scripts/clip_renderer.py` — extend `render_clip` with optional `pair_credit_series` and `pair_label` kwargs so the chemistry edges + bar chart land in the existing GIF without forking the renderer.
- `tests/test_frame_delta_credit.py` — unit test: known synthetic frame where `ΔV=0.1` and uniform attention → each pair gets `0.1/(22 choose 2)`-ish; check sums.
- `research/notebooks/dimaria_clip_sanity.ipynb` — paired-comparison of Design A vs Design B top-5 pairs on the demo clip (decision artifact for Karun review).
- `output/frame_vaep_10517_dimaria.gif` + `.json` — committed outputs.
- `CLAUDE.md` — append a one-paragraph "Frame-by-frame VAEP" section pointing at `credit/` and `scripts/demo_frame_vaep.py`.

Word count: ~590.
