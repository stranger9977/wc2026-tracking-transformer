# Player Chemistry — WC 2022 (PFF event data)

A recreation of Lotte Bransen & Jan Van Haaren's 2020 MIT Sloan paper *"Player Chemistry: Striving for a Perfectly Balanced Soccer Team"* applied to 64 PFF FC World Cup '22 matches.

The repo computes:
- **VAEP** (value of every on-the-ball action) trained from scratch on PFF event data
- **JOI** (Joint Offensive Impact) — chemistry value of every same-team player pair on offensive interactions
- **JDI** (Joint Defensive Impact) — chemistry credit for keeping opponents below their expected offensive impact, distributed by 5×5 positional responsibility share
- **JOI90 / JDI90** — per-90-minutes-together normalization
- **Predictor** — gradient-boosted regressors that forecast JOI90 / JDI90 from pair features (age, position, height, prior matches together) so we can score pairs that have never played together
- **Team Builder** — combinatorial optimization that picks a max-chemistry XI from a candidate pool subject to GK/DEF/MID/FWD formation constraints

The static site at `research/site/` is GitHub-Pages-ready (mobile-first, vanilla HTML/CSS/JS) and lets you explore the results interactively.

## Quick start

```bash
# from repo root
PYTHONPATH=research/src uv run python research/scripts/build_spadl.py            # PFF → SPADL parquet, ~50s
PYTHONPATH=research/src uv run python research/scripts/train_vaep.py             # VAEP, ~60s
PYTHONPATH=research/src uv run python research/scripts/compute_chemistry.py      # JOI / JDI, ~30s
PYTHONPATH=research/src uv run python research/scripts/train_predictor_and_teams.py
PYTHONPATH=research/src uv run python research/scripts/analyze_player_form.py
PYTHONPATH=research/src uv run python research/scripts/render_chemistry_figures.py
PYTHONPATH=research/src uv run python research/scripts/export_site_data.py

# Tests
PYTHONPATH=research/src uv run pytest research/tests -q

# Local site preview
cd research/site && python3 -m http.server 8080
# open http://localhost:8080
```

## What's where

```
research/
  src/chemistry/
    loaders/           PFF event → SPADL conversion + minutes-on-pitch
    vaep/              VAEP features + P-score / P-concede models
    joint/             JOI, JDI, 5×5 position grid
    prediction/        Pair-feature predictor (CatBoost-replacement: HistGBM)
    teambuilder/       Bransen §5 MIP (greedy formation enumeration variant)
    viz/               Liverpool-style pitch chemistry plots
  scripts/             End-to-end runners
  data/                Parquet artifacts (gitignored except for the .gitkeep)
  site/                Static site (vanilla HTML/CSS/JS) for github.io
  tests/               Pytest suite (24 tests, all should pass)
```

## Data sources

- **PFF FC WC '22**: 64 matches under `$PFF_ROOT` (defaults to `/Users/nick/Desktop/drive-download-...`)
- The 67 raw JSONs sometimes lack roster files; the converter quietly skips those.

## Methodology gotchas

1. **PFF gameClock is absolute** — period 2 starts at 2700s (45:00 on the clock) rather than 0. Minute calculations rely on this.
2. **VAEP look-ahead must include the action itself** (`vaep/features.py`). Otherwise goal actions get negative VAEP because the post-goal state has low P(score next 10).
3. **JDI 5×5 grid must mirror the opponent** into our coordinate frame (`joint/jdi.py::_mirror_position`). Without the mirror, my CBs are "far" from opponent CFs in the raw grid; with the mirror, the responsibility share correctly concentrates on the players actually defending the threat.
4. **Sample size**: 64 matches is two orders of magnitude smaller than the 106k Wyscout matches Bransen had. Our JOI predictor R² is low/negative on holdout; JDI R² holds up better (~0.78) because the responsibility-share structure constrains predictions. Honest about this on the site.

## Limitations

- No nationality / region / language features (we have country only via team_name); the paper found these had limited predictive power anyway.
- No club-vs-national direct comparison (would need StatsBomb + WC data linked at player level). We approximate the framing with **per-player tournament under/over-performance vs their own dataset-prior expectation** in `player_form.json`.
- Set-piece passes (corners/freekicks) all get VAEP credit; the paper kept them in their interaction set.
