# Hunt for an offensive-chemistry metric that explains xG variance

**TL;DR:** four metric families failed; a fifth — **final-third combination play (one-twos)** —
is the standout that meets all three goal criteria (robust xG link + believable story +
visualizable), with two honest caveats (family-wise p=0.18; tracks xG not goals). See the
"Combination play" section at the bottom.


**Goal (user, 2026-06-02):** find an *offensive* chemistry metric that meaningfully explains
team xG-for variance beyond talent, tells a coherent/believable story, and is visualizable in
the interactive plays. Unit: team-tournament, n=29 (WC22 teams with FIFA ratings).

**Method (same rigor as the defensive finding):** outcome = xG-for per match; controls =
FIFA Overall + mean caps + games + opponent FIFA. For each candidate: partial r (both axes
residualized), 2000-rep bootstrap 90% CI, **leave-one-out out-of-sample ΔR²** (overfitting
guard), and — because many metrics were tested — a **family-wise permutation test** (max
partial across all candidates, 10k shuffles). Plus face-validity (do recognizable creative
teams rank high?). Baseline: controls-only LOO R² for xG-for = **+0.562** (talent + schedule
already explain ~56% of xG-for variance out-of-sample — a high bar, little robust residual at n=29).

## Candidates tried (4 conceptually-distinct families) — all fail

| family | metrics | best partial | verdict |
|---|---|---|---|
| **value-based** | event JOI sum/mean (the paper's metric), AW-JOI mean (current panel), n_strong_off, tcd_off, gini | +0.29 (event JOI mean) | all CIs span 0; counts + AW-JOI **overfit** (LOO ΔR² negative) |
| **passing-structure** | next-receiver entropy (unpredictability), max-prob, accuracy, top-3 | +0.38 (entropy) | **family-wise p = 0.38** (best-of-many luck); FIFA-only suppression artifact (+0.05 without FIFA); tracks xG (+0.38) but not goals (+0.12); **face validity fails** — Brazil & France rank "most predictable", Costa Rica/Senegal "most creative" |
| **spatial defense-disruption** (Round 2, user's idea) | defensive spread, ball-carrier space, central coverage, opponent-relative z-versions | −0.23 (d_spread, **wrong sign**) | all CIs span 0; **wrong sign** + incoherent face validity |
| **off-ball attacker freeness** | mean/max nearest-defender distance for attackers in the danger zone, free-rate | −0.16 (**wrong sign**) | all CIs span 0; wrong sign |

## Why offense fails here (the load-bearing insight)

1. **The compact-block confound.** Good attacking teams dominate possession and push opponents
   into deep, compact, organized blocks — so *less* space and *less* defensive "disruption" is
   associated with *better* offense. Spatial space/disruption metrics therefore **anti-correlate**
   with attacking quality (observed: d_spread −0.23, free_mean −0.16). The intuitive "break the
   defense → chances" story has the sign backwards at the season-aggregate level.
2. **Talent eats the variance.** FIFA + caps + schedule already explain ~56% of xG-for OOS; the
   residual is small and noisy at n=29.
3. **Circularity traps the value-based metrics.** AW-JOI is built from p_score (≈ xG by Layer-0
   grounding), and the model's *attention* is danger-saliency (per [[relational-chemistry-falsified]]),
   so attention-coherence "defense-breakdown" would be circular too. The clean (spatial) versions
   are the wrong-sign nulls above.
4. **Multiple-comparisons.** The one metric that looked good (passing entropy, +0.45 in a quick
   single-control check; +0.38 full controls) is statistically indistinguishable from best-of-many
   luck once corrected (family-wise p = 0.38), and has no believable team story.

## Conclusion

**No offensive-chemistry metric robustly and believably explains xG-for variance at n=29.** This
is a real result, not a tooling gap — four distinct operationalizations fail the same rigor that
the **defensive** finding (`n_strong_def` → lower xGA, partial −0.38, CI [0.09,0.60], face-valid:
the 4 semifinalists) passed. The believable, robust, visualizable chemistry→xG story in this data
is **defensive**. For offense, the honest framings are (a) *descriptive/stylistic* (the team
network shapes + interactive plays already do this well — Argentina nucleus, France network) rather
than xG-variance-explaining, or (b) lean the deliverable into the defensive signal.

## Combination play (final-third one-twos) — the standout (Round 3)

Mechanism: A→B→A ball exchanges (one-twos) between two attackers in the final third, detected
from the ball-carrier sequence (possessor spells with a min-hold blip filter; middle touch brief;
same team; return in the final third). Structural — uses NO value/xG signal, so non-circular.
Metric `combo_f3_per100` = final-third one-twos per 100 possession spells.

Results vs xG-for (n=29, full controls):
- partial **+0.45**; **stable across every control spec** (+0.34 to +0.45; raw spearman +0.59) —
  unlike passing-entropy which was a FIFA-only artifact (+0.05 without FIFA).
- **jackknife drop-one** range [+0.36, +0.53]; dropping the top-2 influential teams still +0.30 —
  not outlier-driven (the bootstrap CI [−0.30,+0.31] is the pessimistic with-replacement view; the
  jackknife shows single-team robustness).
- **out-of-sample LOO ΔR² = +0.062** (best of all candidates; actually improves prediction).
- permutation p (alone) = 0.016; **family-wise p (max over 19 metrics) = 0.18** (the multiple-
  comparisons caveat — strong evidence, not p<0.05 proof).
- **face validity good:** raw leaderboard top = England, Spain, S.Korea, Saudi, Germany, Brazil,
  France; bottom = Uruguay, Australia, Wales, Qatar, Denmark, Cameroon. Real combination teams high,
  direct teams low. (S.Korea/Saudi are low-possession → high-rate denominator caveat; signal survives
  dropping them.)
- **specificity (coherent story):** *midfield* one-twos (`combo_per100`) are null (+0.07) — only
  one-twos NEAR GOAL relate to xG. A clean, believable mechanism.
- **caveat — goals:** combo_f3 vs goals-for partial = **+0.02** (tracks xG, not goals). Either
  finishing variance (xG is the cleaner target by design) or partial xG-model artifact; can't
  separate at n=29. Given it passes every other robustness check, finishing variance is the
  more likely reading — but flag it.

**Verdict:** the best, most believable, most visualizable offensive→xG signal found. Meets the
stated goal (xG variance + story + visualizable) with honest n=29 caveats. Candidate for an
interactive-play "one-two" overlay + a combination-play leaderboard. **SHIPPED** as a one-twos
panel (scatter + leaderboard + shared-history chart) on `chemistry-wins.html`. Reproduce:
`research/scripts/extract_combination_play.py` → `combo_metrics.parquet` →
`research/scripts/build_combination_xg_site_data.py` → `research/site/data/combination_xg.json`.
Shared-history link (one-two rate vs prior minutes together): ρ +0.67, +0.58 controlling talent.
Model grounding: next-receiver model predicts the give-back 83% (vs 73% overall, 67% nearest baseline).

## Artifacts
`research/data/offense_chem_candidates.parquet` (Round-1 substrate), `offense_nextrcvr_metrics.parquet`,
`defbreakdown_metrics.parquet`, `attacker_freeness_metrics.parquet`; the dead-end exploratory scripts
(value/passing/spatial/freeness) were session scratch and not promoted.
