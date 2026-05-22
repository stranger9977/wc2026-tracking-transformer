# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A research scaffold adapting [SumerSports's tracking-data transformer](https://github.com/SumerSports/SportsTrackingTransformer) from NFL to soccer. The supervised target is **regression on `max(xT) in the next K seconds`** (Karun Singh's Expected Threat as a dense, continuous label) — *not* binary shot/goal classification. The headline metric is **Spearman ρ vs. the xT-lookup baseline**: ours beating xT-lookup quantifies the value of seeing all 22 players, not just the ball.

Current best result: **Spearman ρ = 0.714 (+0.098 over xT-lookup)** trained on 18 PFF WC '22 matches, validated on 4 held-out PFF matches.

## Development

```bash
uv sync --extra dev                                       # env setup
uv run pytest -q                                          # full test suite (~30s); DFL tests skip if no data
uv run pytest tests/test_metrica_loader.py -q             # one test file
uv run pytest -k "metrica" -q                             # by keyword

# Wiring smoke test (synthetic data, no real data needed, ~10s on CPU)
uv run python -m wc2026_tracking_transformer.train fit --config configs/local_cpu.yaml

# Real training (xT regression, the main entry point)
uv run python scripts/train_xt_regression.py --corpus pff --pff-n 22 --epochs 8

# Analysis on a trained checkpoint
uv run python scripts/analyze_space_and_chemistry.py --source pff --match 10502

# GIF rendering
uv run python scripts/render_pff_gif.py --match 10502
```

Python 3.12+. `uv` (not pip) for everything. Adding deps: `uv add <pkg>`.

## Architecture in one trail

The non-obvious thing is that supervision flows through multiple loosely-coupled layers and the regression task is what currently matters (the old binary classification setup is still in the tree but bypassed). To trace it end-to-end:

1. **`data/loaders/{metrica,skillcorner,pff,dfl}.py`** — per-source tracking loaders. Each one yields a stream of `TrackingFrame` (see `data/schema.py`). All four follow the same recipe: load via `kloppy`, convert positions to centered `[-1, 1]` normalized coords, compute velocities by finite-difference with stride-aware `dt`, clamp at ±25 m/s, identify GKs via the extreme-x heuristic over a calibration window. New sources should mirror this layout.
2. **`data/schema.py`** — the 7 per-token features (`x_norm, y_norm, vx, vy, is_attacking_side, is_goalkeeper, has_possession`) plus the dataclass. 22 players + 1 ball = 23 tokens per frame. Order within the player block carries no meaning; the transformer is permutation-equivariant.
3. **`data/batching.py`** — `frame_to_tensor` stacks a `TrackingFrame` into `(23, 7)`; `batch_frames` stacks a list of them into `(N, 23, 7)`.
4. **`baselines/xt.py`** — Karun Singh's published 12×8 xT grid hard-coded, plus `xt_per_frame`/`xt_now` for the baseline and `future_xt_labels(tensors, k_seconds, frame_rate_hz)` for the regression target (`max xT` over the look-ahead window).
5. **`model/transformer.py`** — `SoccerTrackingTransformer`: BatchNorm-over-features → Linear embed → stacked `TransformerEncoder` layers (pre-norm, GELU). Exposes both `forward(x)` and `encode_with_attention(x)` — the latter returns `(encoded, attn)` where `attn` has shape `(B, layers, heads, T, T)`. **Attention extraction is the product**, not a debug feature.
6. **`model/xt_regression.py`** — `XTRegressionLitModule` is the active training entry point. Single head, Huber loss, logs `val_spearman_ours`, `val_spearman_lookup`, `val_lift_vs_lookup`. The older two-head BCE version (`model/lit_model.py` + `tasks/next_event_value.py`) is still there for reference but no longer in the active pipeline.
7. **`scripts/train_xt_regression.py`** — main training runner. Three `--corpus` modes: `small` (2 matches, fast smoke), `full` (11 Metrica+SkillCorner matches), `pff` (PFF-only, last 4 of `--pff-n` held out as val). Trains, scores match 2, picks a peak-prediction window + a goal-anchored window, renders both GIFs via `scripts/clip_renderer.py`. Saves checkpoint to `output/transformer_xt_regression.ckpt` and metrics to `output/training_metrics_xt.json`.
8. **`scripts/clip_renderer.py`** — shared rendering used by all visualization scripts. Builds the GIF: xT-heatmap pitch background (symmetrized so both goals glow), 22 player dots + ball, direction arrowheads, top-3 attended players ringed with halos, top-5 attention edges colored by team relationship (yellow = same-team, orange = cross-team), and a probability chart below showing ours vs xT-lookup over time. Accepts optional `team_color_map`/`team_label_map` for source-specific palettes (e.g., WC '22 national colors from `data/team_colors.py`).
9. **`scripts/analyze_space_and_chemistry.py`** — runs on a saved checkpoint. Outputs `output/space_attribution.json` (top off-ball xT contributors per player, GKs excluded) and `output/chemistry_pairs.json` (top same-team and cross-team pair-attention scores). Uses kloppy metadata directly for real player names + team IDs.

The `tasks/`, `model/lit_model.py`, and `scripts/visualize_attention_gif.py` files predate the xT-regression pivot. They still work but if you're changing training behavior, modify `xt_regression.py` + `train_xt_regression.py` instead.

## Data conventions

`data/raw/` is gitignored. Each source has its own subdirectory:

| Source | Path | Access | License | Notes |
|---|---|---|---|---|
| Metrica | inline via `kloppy.metrica.load_open_data` | open | open educational | 2 matches; dev fixture |
| SkillCorner | inline via `kloppy.skillcorner.load_open_data` | open | MIT | 10 A-League matches at 10 Hz |
| PFF WC '22 | local files (default `/Users/nick/Desktop/drive-download-20260518T234612Z-3-001/` or `$PFF_ROOT`) | registration-gated | restricted | 44 matches; bzipped JSONL tracking |
| DFL/Bassek 2025 | local files at `data/raw/dfl_bassek/` | manual figshare download | CC-BY 4.0 | not yet downloaded; loader scaffold exists |

For PFF, the loader supports `--pff-n N` so training can scale incrementally — start with a few matches, validate, then add more.

## Test gating

`tests/conftest.py` exposes `has_dfl_data` / `has_metrica_data` / etc. fixtures that return False when the data dir is empty. DFL tests use this to skip cleanly when data isn't downloaded. **Don't break this contract** — when adding a new real-data test, gate it on the corresponding fixture so CI / fresh checkouts don't fail spuriously.

## Conventions worth knowing

- **xT grid is static, ball position is dynamic.** When users ask "what changes over time" — clarify that Karun's 12×8 grid is a fixed lookup; what varies frame-to-frame is which cell the ball occupies. Our model's job is to predict the *future* xT trajectory using all 22 players, not just the ball.
- **GKs are excluded from space/chemistry rankings** by default (the `is_goalkeeper` flag from the features). They otherwise dominate attribution because they touch the ball in every defensive-third sequence.
- **Velocity clamp at ±25 m/s** — handles substitution discontinuities and tracker glitches without distorting realistic player speeds (max human sprint ≈ 12 m/s, ball passes up to ~30 m/s).
- **Stride convention for sampling** — every loader takes `sampling_stride` so all sources can be aligned to 5 Hz: Metrica stride=5 (25 Hz native), SkillCorner stride=2 (10 Hz), PFF stride=6 (30 Hz). `dt` for velocity = `stride / native_rate`.
- **Don't push to remote.** Local commits only.
- **`uv add`, not `pip install`.** Edits to deps go through pyproject.toml via uv.

## Sibling project

`~/wc2026-chemistry/` (separate repo) — event-data pair chemistry via VAEP/JOI90. The tracking transformer here is its ball-independent complement: chemistry from continuous tracking instead of from on-ball events.

## Memory

Project context that should persist across sessions is stored in `/Users/nick/.claude/projects/-Users-nick-projects-dynasty-dashboard/memory/`:
- `wc2026_video_framing.md` — three candidate video directions; chemistry (club vs national team gap) is the strongest
- `wc2026_data_sources.md` — what's available where with license + access mode
- `wc2026_xt_target.md` — why we pivoted to xT regression
