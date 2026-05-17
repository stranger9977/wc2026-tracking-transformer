# wc2026-tracking-transformer

A research scaffold for adapting [SumerSports's tracking-data
transformer](https://github.com/SumerSports/SportsTrackingTransformer) from NFL
to soccer, targeting open soccer tracking data and trained on
[Lightning AI](https://lightning.ai/) Studios.

The scaffolding is **runnable end-to-end with synthetic data** — the full
training pipeline (LightningCLI → LightningModule → LightningDataModule → DDP)
wires up and runs on CPU in under a minute. Real-data loaders are stubs until
their respective datasets are downloaded.

---

## How this fits in

There are two adjacent soccer-analytics projects:

| Repo                                 | Data type                       | Role                                                              |
| ------------------------------------ | ------------------------------- | ----------------------------------------------------------------- |
| `wc2026-chemistry`                   | StatsBomb events (VAEP-based)   | Event-data pair chemistry (JOI90). Phase 1 complete, 20/20 tests. |
| `wc2026-tracking-transformer` (this) | Open soccer tracking data       | Ball-independent chemistry + off-ball value via tracking + transformer. |

`wc2026-chemistry` produces a signal conditional on the ball — it only fires
when one teammate passes to another. The tracking transformer produces a
**ball-independent** complement: pair attention weights between two players
that exist on every frame whether either player is on the ball or not. Plus a
unified two-head model (P(score) / P(concede)) for off-ball value.

---

## What's ported from Sumer vs. net-new

SumerSports is fine with people using their open source — this scaffold reuses
the architecture directly with attribution. Their core insight (self-attention
over unordered player tokens scales while grid CNNs plateau) is what makes the
whole thing work.

| Component                                | Source                  | Status in this repo                                                  |
| ---------------------------------------- | ----------------------- | -------------------------------------------------------------------- |
| Unordered-token formulation              | Sumer paper + code      | reused with attribution                                              |
| `nn.TransformerEncoder` backbone shape   | Sumer `src/models.py`   | implemented in `model/transformer.py` (BatchNorm → Linear → Encoder) |
| 6-feature per-player token spec          | Sumer `src/datasets.py` | adapted to 7 soccer features in `data/schema.py`                     |
| NFL play-level data prep                 | Sumer `src/prep_data.py` | replaced with kloppy-based multi-source loaders (`data/loaders/`)   |
| Tackle-location regression head          | Sumer                   | **dropped** — replaced with `tasks/next_event_value.py` (two-head)   |
| Pair-attention extraction                | _not in Sumer_          | **net-new** — `tasks/pair_attention.py`                              |
| Lightning training scaffolding           | Sumer `src/train.py`    | replaced with `LightningCLI` + YAML configs (Lightning AI Studio ready) |

Attribution lives in each ported file's header docstring. The upstream Sumer
repo currently has no LICENSE file — worth opening an issue with them to add
one, but development isn't blocked.

---

## Install

This repo uses [`uv`](https://docs.astral.sh/uv/) for environment management.

```bash
uv sync --extra dev    # creates .venv and installs runtime + dev deps
```

Python 3.12+ required.

---

## Verify the wiring (no data needed)

The training pipeline runs end-to-end on synthetic data on CPU:

```bash
uv run python -m wc2026_tracking_transformer.train fit --config configs/local_cpu.yaml
```

Two synthetic epochs should complete in well under a minute. If they do, the
Lightning pipeline + transformer backbone + task head are all correctly wired.

---

## Get data

Priority order (see [`data/README.md`](data/README.md) for full details):

1. **DFL / Bassek 2025** — CC-BY 4.0, 7 matches, 25 Hz full optical with events.
   Primary source. Direct download from figshare, no registration.
   <https://www.nature.com/articles/s41597-025-04505-y>
2. **SkillCorner Open Data** — MIT, 10 A-League matches, 10 fps broadcast.
   Just `git clone` it. <https://github.com/SkillCorner/opendata>
3. **Metrica sample** — 3 anonymized matches, useful as dev fixture.
4. **PFF FC WC '22** — optional, registration-gated.

Drop unzipped data into `data/raw/{dfl_bassek,skillcorner_aleague,metrica,pff_wc2022}/`.

---

## Train

Once data is in place and `load_match` is implemented for the source you want:

```bash
# Single GPU
uv run python -m wc2026_tracking_transformer.train fit --config configs/single_gpu.yaml

# Lightning AI Studio (multi-GPU DDP)
uv run python -m wc2026_tracking_transformer.train fit --config configs/lightning_studio_multi_gpu.yaml
```

The recommended training path is **Lightning AI Studios** — see
[`studios/README.md`](studios/README.md) for deployment steps. Same code, same
config schema, just a different YAML for the trainer.

---

## Test

```bash
uv run pytest
```

Tests cover imports, loader contracts (skipped where real data isn't present),
DataModule construction, and a synthetic-batch forward-pass smoke test on the
LightningModule.

---

## Roadmap

The deliverables are organized around the three research targets:

### 1. Co-movement chemistry (ball-independent JOI)

`tasks/pair_attention.PairAttentionHead` extracts pair attention weights from
the trained backbone. Reduce over layers + heads → a `(T, T)` chemistry matrix
per frame, then aggregate over a window to get a continuous chemistry score
per player pair. Compare against `wc2026-chemistry`'s event-based JOI90 — the
disagreements are the interesting story.

### 2. Unified two-head model (P(score) / P(concede))

`tasks/next_event_value.NextEventValueHead` predicts both heads from pooled
encoder output. Per-player decomposition falls out of attention attribution.
This is the soccer analogue of VAEP, learned end-to-end from tracking, with
per-player + per-pair decomposition for free.

### 3. Off-ball pattern quantifiers

The six Messi tactical patterns from the deck (picking at the seams, personal
magnetism, playing in the shadows, arriving fashionably late, standing still in
transition, taking space-making space) become first-class metrics once the
backbone is trained. Each is a function on attention + position data per frame.

---

## Open questions

- **Data versioning.** Sumer uses DVC. We may not need it for 7-match DFL, but
  once we add SkillCorner + PFF, parquet checksum + match-id manifests will
  matter. Defer the decision until first multi-source training run.
- **Match-level vs. possession-level splits.** Defaulting to match-level to
  avoid cross-possession leakage; revisit once we can quantify the gap.
- **Auxiliary tasks.** Co-training with masked-frame reconstruction might
  improve transfer to chemistry-style downstream tasks. Sumer doesn't do this
  because they trained on a single task; for representation learning it's
  worth trying.
