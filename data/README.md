# Data layout

This directory holds all input and intermediate data. Everything under `raw/`
and `processed/` is **gitignored** — only `.gitkeep` files and this README live
in the tree.

```
data/
  raw/
    dfl_bassek/           # PRIMARY — CC-BY 4.0, direct download
    skillcorner_aleague/  # secondary — MIT, GitHub clone
    metrica/              # dev fixture — small, fast
    pff_wc2022/           # optional — registration-gated
  processed/              # parquet outputs from scripts/prepare_data.py
```

## Primary source — DFL / Bassek 2025 (CC-BY 4.0)

**Recommended starting point.** Direct download, no registration, no license
ambiguity. 7 matches (2 Bundesliga + 5 2. Bundesliga, 2022/23), 25 Hz full
optical tracking with synchronized events. Data is in the Sportec / DFL XML
format — kloppy's Sportec loader reads it natively.

1. Open the paper page:
   <https://www.nature.com/articles/s41597-025-04505-y>
2. Follow the figshare link in the **Data Records** section.
3. Download the tarball (~tens of GB compressed).
4. Unzip into `data/raw/dfl_bassek/`. Confirm the per-match structure (each
   match should ship a `positions.xml`, `events.xml`, and `meta.xml` — exact
   filenames depend on how figshare bundles the release).
5. Cite the paper in any derivative work.

## Secondary source — SkillCorner Open Data (MIT)

10 matches of broadcast tracking from the 2024/25 A-League season at 10 fps.
Off-screen players are flagged. Useful as a generalization check after training
on DFL.

```bash
cd data/raw
git clone https://github.com/SkillCorner/opendata skillcorner_aleague
```

## Dev fixture — Metrica sample

3 anonymized matches. No formal OSS license — fine for development and
tutorials, not for redistribution. Useful for sanity-checking new code without
moving the larger datasets around.

```bash
cd data/raw
git clone https://github.com/metrica-sports/sample-data metrica
```

## Optional — PFF FC 2022 World Cup release

All 64 WC '22 matches with broadcast tracking, events, and grades. Free but
**registration-gated**, and the license terms aren't a standard OSS license —
treat as restricted-use. Useful specifically when extending to WC-era questions
(player chemistry analysis tied to the actual tournament).

1. Visit <https://www.blog.fc.pff.com/blog/pff-fc-release-2022-world-cup-data>
2. Register and download the bundle.
3. Unzip into `data/raw/pff_wc2022/`.

## Processed outputs

Once raw data is in place, run:

```bash
uv run python scripts/prepare_data.py --source dfl
```

It writes normalized parquet into `data/processed/`:

- `frames.parquet` — one row per `(match_id, frame_id, token_idx)` with
  position, velocity, and role columns.
- `events.parquet` — kloppy-normalized event stream aligned to frame ids.
- `splits/{train,val,test}_match_ids.parquet` — match-level split assignments
  (split at match level to avoid leakage).

## Why match-level splits?

Sumer splits at the **play** level for NFL because plays are independent units.
The closest soccer analogue is the **possession**, but cross-possession leakage
within the same match (similar player configurations, same lineup, same
opponent shape) is real. We default to **match-level** splits — revisit once
the first model is trained and we can quantify leakage empirically.
