# wc2026-tracking-transformer

A research scaffold for adapting [SumerSports's tracking-data
transformer](https://github.com/SumerSports/SportsTrackingTransformer) from
NFL to soccer, targeting the [PFF FC 2022 World Cup tracking
release](https://www.blog.fc.pff.com/blog/pff-fc-release-2022-world-cup-data).

This repo is **scaffold-only**. Public APIs are declared with full docstrings
and `NotImplementedError` stubs; future iterations fill in the bodies.

---

## How this fits in

There are two adjacent soccer-analytics projects:

| Repo                                 | Data type      | Status                  |
| ------------------------------------ | -------------- | ----------------------- |
| `wc2026-chemistry`                   | StatsBomb events (VAEP-based) | Phase 1 complete, 20/20 tests passing |
| `wc2026-tracking-transformer` (this) | PFF FC 2022 broadcast tracking | Scaffold only           |

`wc2026-chemistry` computes pair-level chemistry from **on-ball events** using
socceraction's VAEP. That signal is conditional on the ball — it only fires
when one teammate passes to another. The tracking transformer is intended to
produce a **ball-independent** complement: pair attention weights between two
players that exist on every frame whether either player is on the ball or not.

---

## What's ported from Sumer vs. net-new

| Component                                | Source                | Status in this repo            |
| ---------------------------------------- | --------------------- | ------------------------------ |
| Unordered-token formulation              | Sumer paper + code    | **architectural reuse** — re-implemented (see licensing note) |
| `nn.TransformerEncoder` backbone shape   | Sumer `src/models.py` | scaffolded in `model/transformer.py` |
| BatchNorm → Linear → Encoder → Pool flow | Sumer `src/models.py` | scaffolded                     |
| 6-feature per-player token spec          | Sumer `src/datasets.py` | adapted to 7 soccer-specific features in `data/schema.py` |
| NFL play-level data prep                 | Sumer `src/prep_data.py` | replaced with kloppy + PFF — `data/pff_loader.py` |
| Tackle-location regression head          | Sumer `src/models.py::SportsTransformer.decoder` | **dropped** — replaced with `tasks/next_event_value.py` (two-head P(score)/P(concede)) |
| Pair-attention extraction                | _not in Sumer_        | **net-new** — `tasks/pair_attention.py` |
| DVC data versioning                      | Sumer                 | not adopted (yet); see "Open questions" |
| Lightning + TensorBoard training scaffold | Sumer `src/train.py` | scaffolded in `train.py`       |

### Licensing note

**The upstream Sumer repo does not ship a LICENSE file** at the time this
scaffold was created. That means:

- The architectural ideas described in the paper *"Attention Is All You Need,
  for Sports Tracking Data"* (Ranasaria & Vabishchevich, CMSAC 2024) are free
  to learn from and cite — that's what papers are for.
- The specific Python code in their repo is **not clearly licensed**, so we
  should not copy it verbatim until that's resolved.

The implementation strategy here is "clean-room re-implementation of the
architecture": we describe the structure in our own docstrings, write our own
code (when we get there), and credit the paper inline. Before merging any
*verbatim* code from Sumer's repo, open an issue with them to clarify the
license, or get explicit written permission.

---

## Install

This repo uses [`uv`](https://docs.astral.sh/uv/) for environment management,
mirroring the upstream Sumer repo's tooling choice.

```bash
# from the repo root
uv sync                   # creates .venv and installs deps from pyproject.toml
source .venv/bin/activate # optional; `uv run ...` works without activating
```

Python 3.12+ required.

---

## Acquire the PFF data (manual)

The PFF FC 2022 release is **free with registration** but is not under an
open-source license — we cannot redistribute or download it on the user's
behalf.

1. Visit <https://www.blog.fc.pff.com/blog/pff-fc-release-2022-world-cup-data>.
2. Register a PFF FC account if you don't have one.
3. Download the full bundle (64 matches, broadcast tracking at ~10Hz, events,
   grades).
4. Unzip into `data/raw/pff_wc2022/`. The exact subdirectory layout is set
   by PFF — see `data/README.md` for the expected shape and how to point the
   loader at it.

`data/raw/` and `data/processed/` are **gitignored**. Nothing under PFF's
terms ever enters version control.

---

## Run tests

```bash
uv run pytest
```

The scaffold ships with smoke tests that confirm:

- the package imports cleanly,
- all public surfaces (`data`, `model`, `tasks`) are exposed,
- scaffolded loader functions raise `NotImplementedError` as expected.

Real-data tests (`tests/test_loader_skeleton.py::test_load_pff_match_roundtrip`)
are currently marked `skip` — un-skip them once the loader is implemented.

---

## Repo layout

```
wc2026-tracking-transformer/
├── pyproject.toml              # uv-managed deps (torch, kloppy, lightning, ...)
├── .python-version             # 3.12
├── .gitignore                  # data/raw, data/processed, checkpoints, venv, ...
├── README.md                   # this file
├── data/
│   ├── README.md               # data acquisition + layout notes
│   ├── raw/pff_wc2022/         # (gitignored) drop PFF unzip here
│   └── processed/              # (gitignored) parquet outputs
├── src/wc2026_tracking_transformer/
│   ├── __init__.py
│   ├── data/                   # PFF loader, schema, batching
│   │   ├── __init__.py
│   │   ├── pff_loader.py       # kloppy-based loader (skeleton)
│   │   ├── schema.py           # soccer token spec + dataclass
│   │   └── batching.py         # frame → tensor (skeleton)
│   ├── model/
│   │   ├── __init__.py
│   │   └── transformer.py      # SoccerTrackingTransformer backbone (skeleton)
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── next_event_value.py # P(score)/P(concede) head (skeleton)
│   │   └── pair_attention.py   # pair-attention chemistry head (skeleton)
│   └── train.py                # training entry point (skeleton)
├── scripts/
│   ├── prepare_data.py         # raw PFF → processed parquet (skeleton)
│   └── inspect_frames.py       # sanity-check loaded frames (skeleton)
└── tests/
    ├── conftest.py
    ├── test_imports.py         # smoke tests, run without data
    └── test_loader_skeleton.py # scaffold-contract tests + skipped real tests
```

---

## Roadmap: three research targets

These are the eventual goals this scaffold enables. None are implemented
yet — they're listed here so the structure choices above make sense.

### 1. Co-movement chemistry (companion to JOI90)

- Train the backbone on any reasonable supervised target (e.g.
  `next_event_value`).
- Apply `PairAttentionHead` to extract per-frame pair attention.
- Aggregate attention over each (player A, player B) pair across all frames
  they share on the pitch.
- Compare to event-based JOI90 from `wc2026-chemistry`. Where do they agree?
  Where does tracking-attention pick up signal that event-VAEP misses?

**Files to fill in:** `model/transformer.py::attention_weights`,
`tasks/pair_attention.py::PairAttentionHead.__call__`.

### 2. Unified two-head P(score) / P(concede)

- Replace Sumer's single tackle-regression head with a two-head classifier
  predicting whether either team scores within the next K seconds.
- Train end-to-end on PFF event labels.
- Decompose predictions per-player via attention rollout / Integrated
  Gradients to get a continuous, on-frame player value signal — the
  tracking analogue of VAEP.

**Files to fill in:** `tasks/next_event_value.py`, `train.py`,
`scripts/prepare_data.py` (label construction).

### 3. Quantifying off-ball patterns

Once the backbone is trained, derived analyses:

- **Defender gravity:** how much does removing a defender from the frame
  change P(score) for nearby attackers? Probe via counterfactual frames.
- **Pitch-control delta per off-ball run:** integrate predicted value change
  over the trajectory of a run.
- **Role-conditional pair attention:** does the model learn that center-
  midfielders coordinate more tightly than full-back/winger pairs? Compare
  to known tactical role pairings.

**Files to fill in:** new module under `tasks/` (TBD), notebooks under
`notebooks/` (TBD).

---

## Open questions

- **DVC?** Sumer pipelines training via DVC. With kloppy + parquet here we
  may not need DVC for data versioning, but we'll need *something* for model
  checkpoint provenance. Decide before training the first real model.
- **Match-level vs. possession-level splits?** See `data/README.md`. Default
  is match-level; revisit empirically.
- **Frame rate?** PFF is ~10Hz. Downsampling to 5Hz halves compute. Test
  whether 5Hz loses task-relevant signal.
- **GPU access?** Sumer trained 24 NFL configs in 8-12h on GPU. Soccer
  frame counts are higher (90 min × 10 Hz × 64 matches ≈ 3.5M frames vs.
  Sumer's ~3M player-frames). Expect comparable budget.

---

## Citation

If/when this project leads to anything publishable, cite both the Sumer paper
and the PFF release:

```bibtex
@article{ranasaria2024attention,
  title={Attention is All You Need, for Sports Tracking Data},
  author={Ranasaria, Udit and Vabishchevich, Pavel},
  journal={arXiv preprint},
  year={2024}
}
```

PFF FC 2022 World Cup data release:
<https://www.blog.fc.pff.com/blog/pff-fc-release-2022-world-cup-data>
