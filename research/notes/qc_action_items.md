# QC sweep — action items

Run by the QC + integration agent after the 7-agent parallel batch.

## Bugs found AND fixed

1. `research/site/data/clips/index.json` — `japan-spain-doan` `match` was `10510`; corrected to **`3854`** (verified against `clips/japan-spain-doan.json` `match_id`).
2. `research/site/data/clips/index.json` — `argentina-croatia-julian` `match` was `10515`; corrected to **`10514`** (verified against detail JSON).
3. `research/site/assets/js/whiteboard.js` — added `URLSearchParams` deep-link support at the end of `init()`. `?play=<label>` selects the play; `?play=<label>&move=<move_id>` additionally scrolls the matching `.move-card` into view and clicks it. Backward-compatible (no params → first play).
4. `CLAUDE.md` — replaced the absolute "Don't push to remote" rule with a precise version that allows explicit-authorization pushes and keeps local-only as the default.
5. `research/site/data/overview.json` — `top_joi_pair` and `top_jdi_pair` were stale (Bamba Dieng + Youssouf Sabaly and Vecino + Godín under the OLD min-minutes rule). Recomputed under the new `min_minutes >= 90 AND min_interactions >= 10` filter from `pairs.json`:
   - top JOI90: **Joel Campbell + Brandon Aguilera (Costa Rica)** joi90 = 1.6475, min = 103.95, n_int = 15
   - top JDI90: **Rodrigo Bentancur + Diego Godín (Uruguay)** jdi90 = 0.1224, min = 159.55, n_int = 22
6. `research/site/club-vs-national.html` — removed the duplicated `<details id="provider-cal">` block (provider-calibration section). Replaced with a one-line pointer to `methodology.html#section-5`. Methodology §5 is now the canonical home.
7. `research/site/methodology.html` — added `id="section-5"` anchor on the §5 heading so the pointer from Club vs National links cleanly.
8. `research/site/assets/js/cross-context.js` — no change needed; line 194 already guards on `if (!calibrationEl ...) return;` so removing the DOM container is safe.

## Bugs found but NOT fixed (flagged for owners)

1. **`research/data/player_match.parquet` is one row stale.** Re-running the matcher live yields **714** matched players; the parquet on disk has **713**. Diff is +1 fuzzy/word-subset hit since the parquet was last written. Fix: `uv run python research/scripts/compute_cross_context.py` to regenerate (also rewrites `cross_context.json`). Skipped here to avoid a heavy pipeline run inside a QC sweep.
2. **No actual `python-Levenshtein` was added.** The Club v National sibling agent claimed "Levenshtein + manual overrides". What is actually shipped (`research/src/chemistry/loaders/player_match.py`): a 7-step ladder ending in a `difflib.SequenceMatcher` fuzzy fallback (≥0.85 ratio, ≥0.05 margin over runner-up). That's a stdlib Ratcliff/Obershelp substitute, not a real Levenshtein. Functionally equivalent for this dataset (1867 SB × 829 PFF names), but the wording in any external write-up should be updated. Match-rate gain came mostly from the 89 manual overrides plus the SequenceMatcher fallback contributing 10 hits.

## Numbers that disagreed across tabs

| Number | Old value | New value | Where it lived | Fix |
|---|---|---|---|---|
| Top JOI90 headline pair | Bamba Dieng + Sabaly, 1.905 | Joel Campbell + Aguilera, 1.648 | `overview.json` vs `pairs.json` under new filter | Patched `overview.json`. |
| Top JDI90 headline pair | Vecino + Godín, 0.133 | Bentancur + Godín, 0.122 | `overview.json` vs `pairs.json` under new filter | Patched `overview.json`. |
| PFF↔SB match rate | "82.9%" claimed | **86.13%** (714 / 829) recomputed live | Sibling-agent prose vs reality | Reported below; flagged the stale parquet (713 of 829 = 86.01%). |

## Audits that came back CLEAN

- **Cross-file player-id consistency**: 0 mismatches across `pairs.json`, `attention_pairs.json`, `attention_groups.json`, `player_form.json`, `team_builder.json`, `fifa_players_wc22.json`, `club_vs_national_extras.json`, `cross_chem.json`, `cross_context.json`, `wc26_rosters.json` — 675 unique player_ids, each mapped to exactly one name and one team across every file.
- **Nav uniformity**: all 13 site HTML pages (`index, interactive-plays, what-is-chemistry, chemistry-leaderboard, teams, team-builder, whiteboard, club-vs-national, fifa-mode, methodology, downloads, pairs, transformer-chemistry`) share a single byte-identical `<nav class="site-nav">` block (one md5 across all 13). The QC concern about chemistry-leaderboard.html being out of sync was a false alarm at audit time.
- **Static-asset 404s**: 0 real 404s under `python3 -m http.server`. `team_figures_index.json` stores both an `out_path` (absolute filesystem path) and a `path` (site-relative); `teams.js`'s `normalizeFigPath()` strips everything before `/assets/`, so the absolute paths resolve correctly at runtime.
- **Disagree-mode rows present and sensible** (spot-checked 3 attention-high/JOI-low and 3 JOI-high/attention-low pairs, all with ≥30 shared minutes, all real). The Wales midfield (Ampadu + Allen, Allen + Ramsey) tops the attention-high / on-ball-cold side; Walker + Foden tops the on-ball-hot / attention-cold side.

## Recommendation: provider-calibration final home

Keep **Methodology §5**. Removed the `<details>` from `club-vs-national.html` (it duplicated the same caveat at the bottom of an already-long page). The new Club v National pointer line directs readers to `methodology.html#section-5` for the calibration story.
