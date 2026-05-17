# Data layout

This directory holds all input and intermediate data for the project. Everything
under `raw/` and `processed/` is **gitignored** — only `.gitkeep` files and this
README live in the tree.

## Subdirectories

```
data/
  raw/
    pff_wc2022/    <- drop unzipped PFF FC 2022 release here (gitignored)
  processed/       <- parquet outputs from scripts/prepare_data.py (gitignored)
```

## Acquiring the PFF FC 2022 World Cup release

The PFF FC 2022 World Cup data is free but **registration-gated**. It is not
under an open-source license, so we cannot redistribute it.

1. Visit the release page:
   <https://www.blog.fc.pff.com/blog/pff-fc-release-2022-world-cup-data>
2. Register / sign in with a PFF FC account.
3. Download the full bundle (all 64 matches, ~10Hz broadcast tracking, events,
   and grades). Expect several GB compressed.
4. Unzip the archive into `data/raw/pff_wc2022/` such that the structure looks
   roughly like:

   ```
   data/raw/pff_wc2022/
     tracking/      # per-match tracking files (JSON / Parquet, depending on bundle)
     events/        # per-match event files
     metadata/      # rosters / match metadata
     ...
   ```

   The exact subdirectory names are dictated by PFF — adjust the loader in
   `src/wc2026_tracking_transformer/data/pff_loader.py` to match.

5. Verify the file count: 64 matches × (tracking + events + metadata) bundles.

## Processed outputs

Run `uv run python scripts/prepare_data.py` once raw data is in place. It will
write normalized parquet files into `data/processed/`:

- `frames.parquet` — one row per (match_id, frame_id, player_id) with normalized
  position / velocity / role columns.
- `events.parquet` — kloppy-normalized event stream aligned to frame ids.
- `splits/{train,val,test}_match_ids.parquet` — match-level split assignments
  (split at match level to avoid leakage, mirroring Sumer's play-level split).

## Why match-level splits?

Sumer splits at the **play** level for NFL because plays are independent
units of action. The soccer analogue is **possessions**, but cross-possession
leakage (same match, different possession, similar player configurations) is
real. We default to **match-level** splits to be conservative — revisit once
the first model is trained and we can quantify leakage empirically.
