# Phase 2 readiness — Space metrics (CoCE, TURN, occlusion gate)

_Generated 2026-06-16. Salvaged from workflow `space-metrics-harden-v1` (run `wf_ed3a0ff4-724`)._

> **UPDATE 2026-06-16 — data restored, pipeline reproduces exactly.** The "I/O stall" root cause was the **startup disk at 100% full** (0.2 GB free), which forced iCloud to offload the PFF files and then blocked their re-download. Freed ~10 GB, copied the full dataset to `~/pff_wc22_local` (patched 2 missing top-level matches → 64/64), and repointed the three scripts' default `PFF_ROOT` there. **All three now run in 7–14 s off local disk and reproduce the hardened numbers to the digit** (CoCE 518/508, TURN 0.1822 + Di María 6, occlusion 40.9% / 3.18M rows). The data-access blocker is cleared; remaining gap to "solid" is just the cross-cutting package gate.

## TL;DR

The adversarial hardening **worked**: three metrics were built and beaten on by ~61 agents over ~6.7 hours, producing real, anchor-confirmed numbers with false precision and data contamination stripped out. The workflow originally halted on an **environmental I/O stall, not a logic error** — the PFF source data became unreadable mid-run — but **that blocker is now RESOLVED** (data restored locally; see the line-5 update and "Root cause (resolved)" below). The metric outputs survived on local SSD and have since been **re-verified to reproduce byte-identically** off the local copy. The only step that had not yet happened — the cross-cutting package gate — **is this gate, now in progress** against the restored data. There is no remaining data-access blocker.

**Per-metric verdict: all three are SOLID on their HARD counts/leaderboards** (anchor-matching, heavily hardened, re-verified byte-identical), with **soft-xT/geometric reads kept DIRECTIONAL only** (occlusion gate-bias + no-#1 tie discipline). **The website phase may start on these certified outputs once this package gate signs off** — the data-access precondition is already met, and this gate is that closure step.

## Root cause (resolved)

The original mid-run halt: three verification re-runs earlier on 2026-06-16 had died identically:

```
OSError: [Errno 89] Operation canceled   (reading a PFF event/roster JSON)
real 3589s   user ~4s   sys ~0.3s
```

~60 minutes of wall-clock, ~4 seconds of CPU → the process **was blocked on I/O**, not computing. The old `$PFF_ROOT` was `~/Desktop/drive-download-…`; Desktop was under cloud sync. The directory *listed* instantly (metadata local) but reading file *contents* blocked and cancelled — the bytes had been offloaded and hydration was failing. The true trigger was the **startup disk at 100% full** (0.2 GB free), which forced iCloud to offload the files and then could not re-download into a full disk. **This is fixed:** freed ~10 GB, copied the full dataset to `~/pff_wc22_local` (patched 2 missing top-level matches → 64/64), and repointed the three scripts' default `PFF_ROOT` there. The pipeline is no longer cloud-dependent — all three scripts now run in **7–14 s off local disk with no I/O stall** (re-verified during this gate; see below).

## What's computed (and how solid)

### Occlusion / visibility audit + reusable gate — `research/data/occlusion_audit.json`
- Field: **`visibility` ∈ {VISIBLE, ESTIMATED}**, present on 100% of player rows. Carefully distinguished from a *secondary* `confidence` (HIGH/MED/LOW) field so we gate on the right thing.
- **40.9% ESTIMATED overall** (1,301,065 / 3,180,260 rows) · on-ball **16.7%** · off-ball **42.0%** · attacking off-ball **43.2%** · defending 39.8% · ball 31.4%. Worst match 10510.
- Exports `is_estimated()` / `is_visible()` / `VISIBILITY_FIELD` / `ESTIMATED_VALUE`, plus a `gate_bias` breakdown binning the VISIBLE-keep rate by distance-from-ball, lateral |y|, **and position group** (so we can see the gate's selection bias).
- **Finding:** the prior "~46% off-ball imputed" claim was slightly high — real is 40.9% overall / 42.0% off-ball. On-ball ~83% visible confirms the prior anchor.
- **Load-bearing cross-metric finding (the "occlusion bounds both" link, now wired):** the gate is informatively-missing (NOT MAR) along three **compounding** axes — distance-from-ball (~12% ESTIMATED near-ball → ~95% beyond 60 m), lateral |y| (central more occluded than wide), and **position group** (VISIBLE keep-rate **GK 11.1% / CF 53.7% / W 57.6% / CM 71.2% / DM 70.7%**). The position bias is **partly orthogonal to distance** — it persists within every distance bin (30–40 m: CM ~55% vs CF ~37% vs GK ~7%) — so **distance-stratification alone does NOT de-bias the gate.** This directly bounds the CoCE and TURN **SOFT-xT/geometric reads**, which run on forward/winger-dominated boards (En-Nesyri, Di María, Kramarić, Gakpo, Mbappé, Gnabry, Ronaldo) and are position-gated: those visibility-gated columns **over-sample near-ball central midfielders and under-sample exactly the forwards/wingers the boards highlight**, so their soft magnitudes are downward/selection-biased and must stay directional. The CoCE/TURN **hard counts are unaffected** (label-driven). The same gate-bias is the chief reason the deferred SAR metric stays blocked.
- Confidence: **high** (counting pass over a fully-populated field). Most-stabilized metric.

### CoCE — Ignored Open Man Index — `research/data/coce.json`
- 518 `betterOptionPlayerId` tags → **−8 self-references** (`betterOptionPlayerId == actor`: a shot/header the player should've taken himself) → **−2 cross-team-contaminated** (gid 3848 Skov Olsen/DEN wrongly credited to AUS; gid 3854 Pedri/ESP → JPN) → **508 tallied** ✓ anchor.
- **Ignored-Creator (most-ignored open man) leading tier: a SIX-way tie at N=7 net** — En-Nesyri (Morocco), Ferran Torres (Spain), Bruno Fernandes (Portugal), Cristiano Ronaldo (Portugal), David Raum (Germany), Aleksandar Mitrovic (Serbia) — every row `tie_group=6` with the **same** Poisson 95% CI `[4.35, 9.65]`; **no separable #1** and no supportable within-tie order (En-Nesyri shows first only by sort/insertion order). En-Nesyri's N=7 is the **anchor-confirmed reproduction** (his raw N=8 drops to N=7 after his single self-reference, joining the tie) — a raw-count provenance check, **not a #1 finding**. Mirrors TURN's no-#1 discipline; see `coce.json` `meta.ROBUSTNESS_DISCLAIMER` + per-row `tie_group`/`ci_lo`/`ci_hi`.
- Top "Closed Eye" passer by **SOFT** xT-proxy forgone (concentration-prone, directional): Serge Gnabry. **Team boards (the only two that exist): Argentina (raw count #1, 32 misses, exposure-driven) / Germany (per-game #1, 9.667/game).** CoCE has **no per-match team board** — Spain is 5th per-game (5.0/game); the "11.0 per-match" figure belongs to **TURN**, not CoCE, and must not be cited as a CoCE finding.
- **Value = SOFT static-Singh-xT difference** ("xT left on the table"), explicitly **not** P(score), **not** xG. Directional only. Visibility-gated — both-endpoints VISIBLE on only **282/508 (55.5%)** events.
- **Occlusion gate-bias applies to the xT columns:** per the occlusion audit the VISIBLE-only gate is informatively-missing by position (keep-rate GK ~11% / forwards-wingers ~54–58% / central-mids ~71%, persisting within every distance bin), so the both-visible xT magnitudes **under-sample exactly the forwards/wingers (En-Nesyri, Gnabry, Ronaldo, Di María) who headline these boards** — those reads are downward/selection-biased and stay directional. The HARD counts are label-driven and occlusion-robust.
- Confidence: **high on the HARD counts/leaderboards** (CI-disciplined, tie-grouped, anchor-confirmed; two separate contamination classes caught and removed); xT magnitude directional and additionally gate-biased.

### TURN — Turned Under-line Receptions — `research/data/turn.json`
- Completed, open-play passes with `linesBrokenType` populated **and** `receiverFacingType=='G'`, attributed to receiver. **848** tournament-wide.
- **Turned-to-goal share 18.22%** ✓ · **geometric overlap with line-breaks 21.44%** ✓ (honest divergence preserved — TURN is a *graded* construct, not the geometric corridor) · soft-xT at reception ~0.022.
- **Final (PFF 10517): Di María 6** ✓ · Argentina 17 as a team · Argentina 67 total.
- **Robustness win:** every count carries an exact **Poisson 95% CI**; the board is a **36-player statistically-indistinguishable leading tier** (counts 6–11) with **no supportable single #1** (named cluster: Kramarić 11; six-way tie at 9 incl. Gakpo/Bellingham/Di María). Team raw counts **de-ranked as exposure-driven**; per-match: Spain 11.0, Argentina 9.57. Denominator rebuilt to per-appearance (on-ball involvement), not roster.
- Deliberately **excludes** ensuing-possession StatsBomb-xG credit (no temporal join exists) and a next-receiver phantom-turn term.
- **Occlusion gate-bias applies to the SOFT reads:** the count layer (848, turned-to-goal share, leaderboards) is **occlusion-robust** (driven by PFF human event labels, not imputed positions). The soft-xT read survives on only **710/848** receptions with a VISIBLE receiver position, and the geometric cross-check on **146/681** both-visible. Per the occlusion audit the VISIBLE-only gate over-samples near-ball central mids and under-samples the forwards/wingers (Di María, Kramarić, Gakpo, Mbappé, Gnabry) who headline the leading tier (keep-rate GK ~11% / fwd-wing ~54–58% / CM ~71%, persisting within distance bins), so the soft-xT/geometric magnitudes on forward-heavy rows are downward/selection-biased and stay directional.
- Confidence: **high on counts** (CI-disciplined, occlusion-robust label layer); xT/geometric reads directional and gate-biased.

## Adversarial fixes that actually landed
- TURN: Poisson CIs on every row; refusal to crown a #1; denominator rebuilt to per-appearance; team counts de-ranked as exposure-driven.
- CoCE: self-reference exclusion (8); **cross-team contamination** caught and removed (2), independently reproduced from raw rosters + home/away snapshot sides.
- Occlusion: correct field identified (`visibility`, not `confidence`); distance-from-ball / lateral gate-bias binning added.

## What is closed and what remains
- **CLOSED — data access.** The PFF data is materialized locally at `~/pff_wc22_local`; the three scripts default `PFF_ROOT` there and re-run in **7–14 s off local disk with no I/O stall**. Re-verified during this gate: the regenerated JSONs are **byte-identical** to the canonical `research/data/*.json`.
- **CLOSED — anchor reproduction.** CoCE 518/508 (six-way N=7 tie, `tie_group=6`), TURN 848 / turned-to-goal 0.1822 / geometric 0.2144 / Di María 6 in the final, occlusion 40.9% over 3,180,260 rows (on-ball 16.7% / off-ball 42.0%) — all confirmed off the local copy.
- **IN PROGRESS — the cross-cutting package gate** (cross-metric narrative coherence, ledger-matches-disk, website-readiness certification). This is the single remaining step; it is **this gate**, running now against the restored data. It is not blocked — the data it needs is on disk and reproduces cleanly.

## Remaining action
**The only open step is this cross-cutting package gate** (no data re-materialization is needed — the data is already local and reproducing).
1. Cross-metric coherence + ledger-matches-disk + website-readiness certification (this gate; gatekeepers read JSONs + ledger, no slow script execution).
2. RECOMMENDED (not a blocker): build a **one-time parsed event cache** (64 JSON → one parquet) for speed and cloud-independence before the next heavy multi-agent fan-out.

## From-scratch recommendations (per your "OK to rebuild" note)
- **DONE** — PFF data is on stable local storage (`~/pff_wc22_local`). A parsed parquet cache is still RECOMMENDED (not a blocker) before the next heavy fan-out.
- For SAR and the next tier, **drop the stale heads** (teammate-blind motion-forecast ghost; pooled-scalar `xt_regression`). Build a transparent from-scratch PPCF surface + static Singh xT instead.
- Keep value reads labeled **SOFT** until a real validated value model exists; never promote to "value"/"xG" in website copy.

## Deferred (proposed — blocked on missing foundational builds, NOT on data access)
SAR (headline), full P-OBSO, full SMS, CHASE, and any ensuing-possession xG credit — all need foundational builds that do not exist yet (PPCF/pitch-control surface, label↔frame join, teammate-aware ghost, PFF↔StatsBomb temporal join). These are out of scope for the first website build and are separate from the (now-resolved) data-access blocker. See `space_metrics_ledger.json` `proposed_deferred`.

## Certification 2026-06-16

**CERTIFIED. All adversaries satisfied. Website greenlight: YES (count/leaderboard layer solid; soft-xT value layer stays flagged directional).**

The cross-cutting package gate ran three gatekeeper rounds and reached a **clean round** (round 3: **4/4 gatekeepers satisfied, zero blocking**). Round 1 (0/4) caught the CoCE single-#1 crowning that contradicted the metric's own six-way-tie disclaimer, the un-wired occlusion gate-bias, and a TURN "Spain per-match" figure mis-attributed to a non-existent CoCE per-match board. Round 2 (1/4) caught the ledger/readiness self-contradiction over whether the data blocker was resolved. All were remediated; round 3 found nothing blocking.

**Read-only re-verification off the local copy (`~/pff_wc22_local`) during this gate confirmed every anchor:**
- **CoCE:** 518 `betterOptionPlayerId` tags → 508 tallied (−8 self-reference, −2 cross-team). Ignored-Creator leading tier is a **six-way tie at N=7** (En-Nesyri, Ferran Torres, Bruno Fernandes, Ronaldo, Raum, Mitrovic), all `tie_group=6`, all CI `[4.35, 9.65]` — no separable rank-1. Team boards are **raw (Argentina 32) and per-game (Germany 9.667) only**; no per-match board exists; Spain is 5th per-game (5.0). Both-endpoints-VISIBLE on 282/508 soft-xT events.
- **TURN:** 848 receptions, turned-to-goal **0.1822**, geometric overlap **0.2144** (146/681 both-visible), soft-xT 0.02204 (710/848 visible receiver), **Di María 6 / Argentina 17** in the final (PFF 10517), 36-player statistically-indistinguishable leading tier with no single #1.
- **Occlusion:** **0.4091** ESTIMATED over **3,180,260** rows (on-ball 0.1672 / off-ball 0.42); position keep-rate **GK 0.1112 / CF 0.5372 / W 0.5759 / CM 0.7121**, bias persists within every distance bin.

**Per-metric go/no-go:**

| Metric | Verdict | One-line reason |
|---|---|---|
| **occlusion** | **solid** | 100%-populated visibility field; 40.9% / 3.18M-rows reproduces exactly; reusable gate + position/distance/lateral gate-bias breakdown correct; no soft layer to caveat. |
| **CoCE** | **solid** | Counts/leaderboards correct, reproducible, CI-disciplined and tie-grouped (518/508, six-way N=7 tie, raw + per-game team boards only); soft static-Singh-xT honestly labelled directional (NOT P(score)/xG) and flagged as inheriting the occlusion position gate-bias on its both-visible columns. |
| **TURN** | **solid** | Hard count layer occlusion-robust (PFF-label-driven), CI-disciplined, anchor-confirmed; soft-xT/geometric reads labelled directional; ensuing-possession StatsBomb-xG correctly NOT claimed; occlusion gate-bias flagged on the visibility-gated columns. |

**Website greenlight = YES**, conditioned on the two binding website-copy guards (already in the ledger `from_scratch_recommendations`):
1. **Tie discipline** — present the CoCE Ignored-Creator/Closed-Eye boards and the TURN board as tie-grouped tiers (read `tie_group`/`ci_lo`/`ci_hi`), **never** as a single ranked "most-ignored"/"best" name. The only clean single-name anchor safe to headline is an unambiguous count like **Di María 6 in the final**. Do NOT borrow TURN's Spain-11.0/match for any CoCE claim.
2. **Occlusion bound** — whenever a CoCE/TURN soft-xT or geometric magnitude is surfaced, carry the position gate-bias caveat (forwards/wingers under-sampled vs central mids) and keep it labelled **SOFT/directional**, never P(score) or xG. The hard counts are occlusion-robust and may be shown as-is.

**Blocking remaining:** none.

**Out of scope for the first website build (correctly deferred):** SAR (headline), full P-OBSO, full SMS, CHASE, and any ensuing-possession StatsBomb-xG credit — all blocked on missing foundational builds (not on data access). The soft static-xT value layer remains FLAGGED directional and is not certified as a value model; this does not block the website because the count/leaderboard layer is solid and the guards keep the soft layer labelled.
