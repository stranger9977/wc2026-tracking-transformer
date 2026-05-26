# Score-specialist vs shared frame-VAEP attention networks

## Question

The shared frame-VAEP backbone trains two heads (P(score), P(concede)) on top of
one transformer. We hypothesised that a single-head **score-only specialist**,
freed from any defensive supervision, would attend more to offence-to-offence
relationships and thus surface visibly more "off-off" chemistry in its per-team
networks. The reader-facing test: of each team's top-20 pairs by attention,
what fraction are off-off (both grid-role FWD/MID)?

## Method

1. Reused the per-match score-specialist shards in
   `research/data/attention_chemistry_score_specialist_shards/` (extracted from
   `output/transformer_score_only.ckpt`).
2. Applied the ball-distance baseline correction. The per-pair frame counts per
   distance bin are a property of the data (same `_stream_match_combined`
   pipeline), so the bin counts from the shared model's baselined shards apply
   verbatim. The per-bin global baseline was recomputed from the specialist's
   own attention (distributing each pair's total proportional to its bin
   frame counts). Output:
   `research/data/attention_chemistry_score_specialist_baselined.parquet`
   (18,534 rows, 44 matches). Script:
   `research/scripts/baseline_correct_specialist_attention.py`.
3. Aggregated to per-pair per-90 via the existing
   `aggregate_team_attention` (same as the shared deployment).
4. Rendered specialist per-team PNGs to `team_<id>_attention_score.png`
   alongside the shared ones (the renderer now takes `--source specialist`).
5. Per team, computed top-20-pair off-off / def-def / cross fractions for both
   models.

## Results

### Headline (averaged across all 31 teams)

| | shared | specialist | delta |
|---|---|---|---|
| top-20 off-off fraction | **7.74%** | **7.90%** | **+0.16pp** |
| teams where specialist is higher | – | – | 10 / 31 |
| teams unchanged | – | – | 12 / 31 |
| teams where specialist is lower | – | – | 9 / 31 |

### Leaderboard top-300 composition

| | shared | specialist |
|---|---|---|
| off | 0 | 8 |
| def | 57 | 86 |
| cross | 243 | 206 |

The specialist *does* surface a handful of off-off pairs in the top-300 (vs
zero for the shared model), but the bulk of the rebalancing was actually
cross → def, not cross → off.

### Teams where the specialist most clearly out-cleans the shared network

| Team | shared off-off | specialist off-off | Δ |
|---|---|---|---|
| Denmark | 5% | 20% | +15pp |
| Japan | 0% | 10% | +10pp |
| Qatar | 25% | 35% | +10pp |
| Costa Rica | 15% | 20% | +5pp |
| Spain | 0% | 5% | +5pp |
| United States | 0% | 5% | +5pp |

### Teams where the specialist is worse

| Team | shared off-off | specialist off-off | Δ |
|---|---|---|---|
| Tunisia | 30% | 15% | -15pp |
| Saudi Arabia | 20% | 10% | -10pp |
| Netherlands | 15% | 5% | -10pp |
| Ghana, Cameroon, South Korea | … | … | -5pp |

## Decision

The user's hard rule was **specialist ships sitewide only if the average top-20
off-off fraction beats the shared model by ≥ 5 percentage points**. The
specialist beats it by **+0.16pp** — well under the threshold, and improvements
are roughly evenly split with regressions across teams (10 better, 9 worse).

**Keep the shared frame-VAEP backbone as the deployed network source.** No site
files are overwritten. The specialist baselined parquet and per-team PNGs
(`team_<id>_attention_score.png`) plus `attention_pairs_score.json` /
`attention_groups_score.json` / `attention_figures_index_score.json` are
written but not linked from the site.

The honest read on the hypothesis: dropping the concede head does shift a small
amount of attention budget toward defenders pairs (def-def 57 → 86 in the
top-300) and a handful of offensive pairs (0 → 8), but the dominant effect is
the cross-role pairs still own the top of the distribution. The score-only
model isn't a fundamentally different lens on chemistry; it's a marginal
re-weighting of the same one.

## Files

- `research/scripts/baseline_correct_specialist_attention.py` (new)
- `research/data/attention_chemistry_score_specialist_baselined.parquet` (new)
- `research/scripts/render_attention_figures.py` — `--source {shared,specialist}` flag
- `research/src/chemistry/viz/attention_pitch.py` — `filename_suffix` parameter
- `research/site/assets/figures/team_<id>_attention_score.png` (31 files, unlinked)
- `research/site/data/{attention_figures_index_score,attention_pairs_score,attention_groups_score}.json` (unlinked)
- `research/site/transformer-chemistry.html` — added a one-paragraph mention of
  the A/B and which model powers the live networks.
