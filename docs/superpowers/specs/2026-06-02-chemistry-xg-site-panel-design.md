# Chemistry → Expected Goals Site Panel — Design Spec

- **Date:** 2026-06-02
- **Status:** Draft (design approved in brainstorming)
- **Branch:** `spec/xg-grounding`
- **Context:** ships the firm finding from the xG-grounding study (`xg_chemistry_layer1_findings.md`, memory `xg-chemistry-grounding`) as a site artifact.

## Goal

Add a **paired offense/defense scatter panel** to `research/site/chemistry-wins.html`, in the headline spot where the TCD-vs-tournament-finish scatter (ρ=0.704) lives, grounding the chemistry claim in **expected goals over/under expected**:
- **Defense (the firm finding):** more defensive-pair chemistry → fewer expected goals conceded than talent/schedule predict.
- **Offense:** offensive chemistry vs expected goals added.

Additive — the existing TCD-vs-finish scatter stays (gets a one-line "older view" caption); the new panel leads.

## The two scatters

| | LEFT (Defense) | RIGHT (Offense) |
|---|---|---|
| x | defensive chemistry = `n_strong_def` | offensive chemistry = `mean_aw_joi90` |
| y | **xGA over/under expected** (residual; **below 0 = concedes fewer than expected = good**) | **xG over/under expected** (residual; **above 0 = creates more than expected = good**) |
| title | "Defensive chemistry → expected goals prevented" | "Offensive chemistry → expected goals added" |

- Each point = a team (n=31); **semifinalists highlighted/labelled** (Argentina, France, Croatia, Morocco).
- Trend line + annotation of the controlled partial-r (def ≈ −0.38; offense its value). No hedge/"suggestive" text on the chart — clean titles only; statistical nuance lives in the methodology note.
- Subcaption on both: "expected goals over/under expected, given talent (FIFA + caps), games, and opponent strength."

**Why over/under-expected (not raw xGA):** a raw `n_strong_def` vs raw xGA scatter is ~flat (ρ≈−0.09, the suppressed version). The finding only appears against the **residual** (xGA minus the talent/schedule baseline). The y-axis residual IS the "over/under expected" framing.

## Data

A build script `research/scripts/build_chemistry_xg_site_data.py` (productionizing the Layer-1 residuals) emits `research/site/data/chemistry_xg.json`:
```
{ "meta": { "n_teams": 31, "def_partial_r": -0.38, "def_ci90": [-0.64,-0.08],
            "off_partial_r": <v>, "off_ci90": [<lo>,<hi>],
            "controls": "FIFA overall + mean_caps + games + opponent FIFA" },
  "teams": [ { "team_id","team_name","def_chem","off_chem",
               "xga_over_expected","xg_over_expected","stage_int","is_semifinalist" }, ... ] }
```
- Inputs: `research/data/xg_grounding_team_match.parquet` (per-team-match model value + StatsBomb xG/xGA), `research/site/data/team_chemistry_vs_paper.json` (n_strong_def, mean_aw_joi90, overall, mean_caps, stage_int), and opponent-FIFA derived from the parquet's two-teams-per-game.
- `xga_over_expected` = residual of per-match xGA on [FIFA, mean_caps, games, opp_fifa]; `xg_over_expected` = residual of per-match xG-for on the same. Residuals + partials/CIs computed **server-side** (the site never runs regressions in JS — matches the pre-baked-JSON pattern).
- `is_semifinalist` from `stage_int` (the 4 deepest-stage teams).

## Site integration

- `chemistry-wins.html`: add a `<section>` with two side-by-side scatter containers above the existing TCD-vs-finish scatter; add the "older talent-confounded view" caption to the latter.
- `chemistry-wins.js`: add a `renderChemistryXgPanel()` that fetches `chemistry_xg.json` and draws the two scatters — **reuse the existing scatter renderer** in that module (read it during planning for exact reuse; no new charting library).
- Bump the `chemistry-wins.js` `?v=` cache-bust tag (the documented stale-cache footgun).

## Components / testing

- Build script: pure helpers in `research/src/xg/` — `team_xg_table()` (assemble) + `residualize(df, y, controls)` — unit-tested on synthetic; JSON emission is integration.
- JS render: integration (eyeball in the served site); reuses the tested-by-eye existing scatter component.

## Non-goals

- Don't remove the TCD-vs-finish scatter (additive; keep as legacy context).
- Don't touch other pages (chemistry-leaderboard, fifa-mode, etc.).
- No new charting dependency; reuse the existing scatter renderer.
- The relational/next-receiver-vs-xGA investigation is tabled (separate; not part of this panel).
