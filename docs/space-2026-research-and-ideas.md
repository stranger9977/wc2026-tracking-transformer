# "Space" — Research Synthesis & Project Ideas for 2026 World Cup Content

*Prepared 2026-06-10. Sources: deep-research sweep (25 claims verified against primary papers, 0 refuted) + direct inspection of the PFF WC2022 data and this repo's models. Citations at the bottom.*

## The pitch

Off-ball movement is soccer analytics' best unanswered question. Karun Singh's own framing — *we don't really understand off-ball movement* — is backed by the literature's most striking admission: **there is no ground truth for "space."** Fernández & Bornn validated their space metrics by having two FC Barcelona video analysts eyeball clips. That's the state of the art for validation.

Our angle: **we have something nobody public has** — PFF's human-graded events (`createsSpace`, `movementGrade`, `positionGrade`, `betterOptionPlayerId`, `pressureType`) synchronized with 30 Hz tracking on the same World Cup matches, *plus* an already-trained tracking transformer with calibrated P(score), an xT-regression head, a next-receiver head, a motion-forecasting head, and a positional-counterfactual pipeline. The narrative writes itself: *the question nobody has answered, attacked with labels nobody else has, on the world's biggest stage, right before it returns.*

---

## 1. What the literature says (verified)

### The model ladder, by data requirement

| Model | Data needed | What it measures | Key limitation |
|---|---|---|---|
| **xT** (Singh 2019) | Events only | Value of on-ball moves via Markov chain over a 12×8 grid | Only *successful, on-ball* moves; explicitly tolerates ignoring off-ball effects ("moving in a loop might actually draw defenders out of position... an inaccuracy we tolerate") |
| **OBSO** (Spearman 2018) | Events + one tracking snapshot per on-ball event (~1,000 frames/match, not ~8M) | Off-ball scoring opportunity = Σ over pitch of Transition × Control (PPCF) × Score | Distance-only scoring model with a "fudge factor" β; transition model has no toward-goal preference; **ignores defensive pressure and carrier speed** (all three named by Spearman himself) |
| **Pitch control / SOG-SGG** (Fernández & Bornn 2018) | Full tracking — but the parametric pitch-control component deliberately runs on a single frame, no training data | Continuous control surface (bivariate-normal influence per player, logistic team difference); Space Occupation Gain / Space Generation Gain | Validated only by expert video review — the "no ground truth" problem |
| **EPV** (Fernández, Bornn, Cervone 2019/2021) | Full tracking + events (633 EPL matches @ 10 Hz) | EPV ∈ [−1,1]; decomposed pass/carry/shot surfaces; off-ball value for all 10 teammates at every pass + every 1 s of carries | **No body orientation** (the Rakitic example); **average-player model** — the authors' own "Messi effect" gap |

### Verified findings worth building on

- **OBSO is a leading indicator**: per-game OBSO → next-game goals r = 0.26, vs 0.17 for shots and 0.12 for goals; autocorrelation 0.60; team opportunity/match vs goals/match r = 0.76. (53-game sample, no significance tests — improvable.)
- **"Messi walking" is quantified — but only once**: in a *single match* (Barcelona–Villarreal 2017, 845 attacking situations), 66.67% of Messi's space gain was passive (< 1.5 m/s), 71% of it in front of the ball, yet he ranked near the top in total space gained. The authors' gloss: walking is "a conscious action to move through empty spaces of value." Iniesta + Busquets + Messi = 41.2% of Barça's space-occupation gains. **n = 1 match. Nobody has replicated it at tournament scale.**
- **Forwards generate as much or more off-ball value than midfielders** despite much lower reception probability (EPV, KDE plots, no formal tests) — counterintuitive, content-friendly, replicable.
- **Published content templates exist**: "Pressing Liverpool" (how a 4-3-3 press pushes buildup into low-value wide space) and "Growing around David Silva" (which teammates generate space for the star) are the verified blueprints for team-level pieces.
- **Broadcast tracking caveat** (Penn, Donnelly & Bhatt 2025): reconstructed off-camera positions carry ~7.3 m mean error in a comparable method — fine for team-level structure and xT-style modeling, **not** for fine-grained off-camera run detection. Our spot check of PFF match 10502: event-snapshot player positions are **54% VISIBLE / 46% ESTIMATED**. Every "getting open" claim must be conditioned on visibility.
- Research-corpus caveat: the verified sweep covers the canonical 2017–2021 stack plus one 2025 paper; post-2021 graph/transformer approaches (TacticAI-style) weren't in the verified set. Locally, *our transformer is that newer generation* — which is exactly the gap our work fills.

---

## 2. What we already have (asset inventory)

**Data** (local PFF download at `$PFF_ROOT` — see CLAUDE.md; event data for all 64 WC22 matches, tracking cached for 44):
- 30 Hz broadcast tracking (all players + ball x/y/z), event data, rosters, per-event player snapshots with `speed`, `visibility`, `confidence`.
- **Human labels nobody else pairs with tracking** (actual tournament totals, computed over all 64 event files — 144,541 events; see `research/scripts/eda_space_leaderboards.py`):
  - `createsSpace` boolean → **1,422 expert-tagged space-creation moments** (attributed to the on-ball actor; the dedicated `csPlayerId` is unusable, 2/1,422 populated)
  - `betterOptionPlayerId/Type/Time` → **518 "an open man was ignored" tags**
  - `grades.movementGrade` (368 events) + `positionGrade` (1,300 events) → **graded off-ball movement/positioning** — note: these are mostly *deduction* metrics (movementGrade ~71% negative, positionGrade ~99% negative), so "best avg grade" reads as "least-bad"
  - `pressureType` (N/P/A/L) populated on ~62% of possession events (46,782 under pressure: P/A/L) → **the pressure annotation Spearman said OBSO needs**
  - `bodyMovementType` (toward-goal / away / lateral / stationary; sparse) and `bodyType` → partial orientation signal (the EPV authors' named gap)

**Models** (this repo):
- Tracking transformer (23 tokens × 7 features) with calibrated P(score)/P(concede) specialists
- **xT-regression head** — predicts max xT in next K s; lift over the static xT lookup is already framed as the off-ball signal; `scripts/analyze_space_and_chemistry.py` prototypes per-player off-ball xT lift via ball→player attention
- **Next-receiver head** — possessor-conditioned P(receive) per teammate
- **Motion-forecasting head** — 2 s displacement forecast per player (= a built-in "average player" ghost)
- **Whiteboard counterfactuals** — perturb a player's position, recompute ΔP(score)
- Messi oriented position-density work (geometry, 6 cached Argentina matches)
- AW-JOI attention chemistry + a polished static site for interactive clips

---

## 3. Nick's Q1: Would we improve any preexisting models? — Yes, four ways

Each is a gap *named by the original authors*, matched to an asset we hold:

| Named open problem (source) | Our asset | The improvement |
|---|---|---|
| OBSO ignores defensive pressure & carrier speed (Spearman) | `pressureType` on ~63% of events; `speed` per player snapshot | **Pressure-aware OBSO**: condition the transition/control models on pressure state. Benchmark: does opportunity→goals correlation beat the published r = 0.76 team-level / 0.26 leading-indicator marks on WC22? |
| No ground truth for space (Fernández & Bornn) | ~1,200 `createsSpace` tags, ~1,000 movement/position grades | **First label-validated space metric**: report precision/recall of pitch-control gain, SOG, and our off-ball xT lift against expert tags. This upgrades the whole field's validation story — from "two analysts watched video" to quantitative agreement with independent expert labels. |
| Average-player EPV, no "Messi effect" (Fernández et al.) | Transformer + 44 matches with player IDs | **Player-conditioned value**: add player-identity embeddings to the value heads; measure how much the surface shifts when "a generic forward" becomes Messi/Mbappé. Even a null result is content ("one World Cup isn't enough to learn Messi — here's why"). |
| No body orientation in tracking (Fernández et al.) | `bodyMovementType`/`bodyType` (sparse) | Supplementary: orientation-aware corrections on the subset of tagged events. Honest framing: partial, exploratory. |

Plus a transfer-learning question the literature flags and we can answer: pitch-control/EPV parameters were calibrated on club data (EPL 2013–15, La Liga) — **do they hold in international tournament play?** Re-fit on WC22 and report the differences. That's a methods piece in itself.

## 4. Nick's Q2: What else could we look at or measure? — The idea board

### Track A — Tournament-scale replications (fast, citable lineage)

**A1. "Messi Walked Here" — the replication the field never did.**
Fernández & Bornn's walking result is one match. We run the active/passive (1.5 m/s) space-gain split across all of Argentina's matches in our data (6 cached) — did Messi *walk his way to the trophy*? Pairs with our existing position-density work and the FiveThirtyEight "Messi walks better than most players run" lineage. 2026 hook: he may play his last World Cup at 39 — *will he walk through it one more time?*

**A2. The WC22 OBSO leaderboard.** Who generated the most off-ball scoring danger in Qatar? OBSO needs only event-time snapshots — we exceed its data bar by orders of magnitude. Cross-check the EPV finding that forwards out-generate midfielders off-ball.

**A3. "Growing around Pedri."** The David Silva case study, on Spain 2022: which teammates' movement opened space for Pedri — and vice versa (is Pedri the space *consumer* or *creator*?). Perfect tee-up: Spain enter 2026 as Euro champions with Pedri/Yamal.

**A4. Strangling space.** The "Pressing Liverpool" template on Morocco's semifinal run: quantify how their block pushed opponents' buildup into low-value space. Also: the final — how Argentina's space control collapsed for 20 minutes of Mbappé.

### Track B — Model improvements (Section 3, as runnable projects)

B1. Pressure-aware OBSO (benchmark vs published correlations)
B2. Label-validated space metrics (`createsSpace` precision/recall + case-study gallery of hits and misses — *the misses are content too*)
B3. Player-conditioned value heads
B4. Re-fit club-calibrated models on tournament data; report what moves

### Track C — Novel, ours-only (the transformer plays)

**C1. Space Above Replacement (ghosting).** The motion-forecast head predicts what an average player would do in the next 2 s. The gap between a player's *actual* movement and the forecast, valued through Δpitch-control or ΔP(score), is **movement skill above expectation** — Le et al.'s ghosting idea, applied to space, at a World Cup. This is the headline metric candidate.

> **Prior art (de-risks C1/B1): C-OBSO** — Teranishi, Tsutsui, Takeda & Fujii (arXiv:2206.01899, 2022) built almost exactly this on J1-League data: actual off-ball OBSO minus the OBSO of a GVRNN-predicted reference trajectory. They also fix two Spearman gaps (their score model adds goal angle + multi-defender shot-blocking). C-OBSO correlated with salary (ρ=0.45, p=0.046) where plain OBSO (ρ=−0.28) and goals (ρ=−0.23) did not. Our edge: a transformer forecast across the full World Cup, validated against `createsSpace`/`movementGrade` labels they explicitly lacked.

**C2. The Most Ignored Open Man.** Combine the next-receiver head (P(receive) trajectory — who *gets open*) with PFF's `betterOptionPlayerId` tags (who got open *and was ignored*). Leaderboard + film room. This is the Pedri narrative in metric form: getting open is a skill even when the pass never comes.

**C3. Move the players yourself.** The whiteboard counterfactual pipeline as public-facing interactive content: drag the winger wider, watch P(score) move. "What if" is the most shareable form of tactics content, and it's already built.

**C4. Off-ball xT lift, formalized.** The existing prototype (attention-weighted lift over the xT lookup) graduated into a tournament leaderboard — validated against `movementGrade`/`createsSpace` (B2) before publishing.

**C5. How much of the World Cup does the camera actually see?** The occlusion audit (visibility/confidence rates by player, team, phase of play) is both the mandatory methods prerequisite for everything above *and* a standalone story — the dark-matter framing made literal: the players you can't see are often the ones creating the space.

**C6. Gravity: who stretches the block (CHASE, translated).** CHASE — Convex Hull Area Strength Estimate (Lauer et al., NFL Big Data Bowl 2025) — measures an NFL receiver's impact on *defensive spacing* via the defenders' convex hull, inspired by basketball "gravity," and validates it against teammate catch probability. Every metric in Tracks A–C values space from the *attacker's* side (control gained, value of position); CHASE measures the *defense's geometric reaction* — a complementary axis we don't otherwise cover. Soccer translation: when a striker runs in behind or a winger holds width, how much does the opposing block deform — line height pushed back, block width pulled apart, inter-line gaps opened? Soccer-specific twist: a compact block is a 10-player connected structure, so line-based compactness measures (defensive line height, block width × depth, inter-line distance) will behave better than a raw convex hull, which outliers dominate. It's pure geometry — no trained model, cheap, explainable — and credits decoy runs the instant defenders react, even when no pass comes (the same "unrewarded movement" theme as C2, through a different lens). Validate deformation events against `createsSpace` tags; cash out the opened space via pitch control or ΔP(score) for teammates. Hook: "Gravity leaderboard — whose runs bend defenses," with obvious 2026 candidates (Mbappé's depth, Yamal's width).

### The meta-piece

**Where the models disagree.** xT, OBSO, pitch control, and our transformer will rank moments and players differently. Chart the disagreement instead of hiding it. This honors the original framing — *an unanswered question is still very interesting* — and positions the series as honest science, not metric-mongering.

---

## 5. Suggested content arc ("Space: Soccer's Dark Matter")

1. **The unanswered question** — explainer: why off-ball movement resists measurement (xT → OBSO → pitch control → EPV ladder; Karun's framing)
2. **How much of the game can we even see?** (C5 occlusion audit)
3. **Messi walked here** (A1)
4. **The most ignored open man in Qatar** (C2)
5. **Who actually creates space** (B2 validation + C4 leaderboard)
6. **Strangling space: Morocco** (A4)
7. **Interactive: move the players yourself** (C3)
8. **Where the models disagree** (meta-piece)
9. **2026 preview**: the space-creators to watch (Pedri/Yamal's Spain, France, host-nation angles)

## 6. Order of operations & honest caveats

1. **C5 first** — quantify PFF occlusion (visibility = ESTIMATED ≈ 46% of event-snapshot positions in our spot check). Every downstream claim gets conditioned on it.
2. **Parametric pitch control next** — single-frame, no training data, designed for exactly this situation; unlocks A3/A4/B2/C4.
3. **A1 + A2 as first publishable pieces** (replication lineage = low methodological risk).
4. Then B-track improvements and C-track novel metrics, validated against the PFF labels before any leaderboard goes public.

Caveats to carry everywhere: broadcast-derived tracking (off-camera ≈ imputed); the Messi-walking original is n=1 with the "deliberate" framing being the authors' interpretation; OBSO's validation sample was small and test-free; label counts (~27 `createsSpace`/match) are sparse — they validate, they don't train; we hold 44 of 64 matches.

## Sources (primary, verified 3-0 in adversarial review)

- Singh, *Introducing Expected Threat (xT)*, 2019 — https://karun.in/blog/expected-threat.html (grid: open_xt_12x8_v1.json, bundled in `baselines/xt.py`)
- Spearman, *Beyond Expected Goals* (OBSO), SSAC 2018 — https://www.researchgate.net/publication/327139841_Beyond_Expected_Goals
- Fernández & Bornn, *Wide Open Spaces*, SSAC 2018 — https://www.lukebornn.com/papers/fernandez_ssac_2018.pdf
- Fernández, Bornn & Cervone, *Decomposing the Immeasurable Sport* (EPV), SSAC 2019 — http://www.lukebornn.com/papers/fernandez_ssac_2019.pdf; journal version, Machine Learning 2021 — https://arxiv.org/abs/2011.09426
- Martens, Dick & Brefeld, *Space and Control in Soccer* (individualized pitch control + Space Generation), Frontiers in Sports and Active Living 2021 — https://pmc.ncbi.nlm.nih.gov/articles/PMC8322620/
- Teranishi, Tsutsui, Takeda & Fujii, *Evaluation of creating scoring opportunities for teammates in soccer via trajectory prediction* (C-OBSO), 2022 — https://arxiv.org/abs/2206.01899
- Penn, Donnelly & Bhatt, *Continuous football player tracking from discrete broadcast data*, R. Soc. Open Science 2025 — https://royalsocietypublishing.org/rsos/article/12/10/251175/236076
- PFF FC WC2022 dataset — https://www.blog.fc.pff.com/blog/enhanced-2022-world-cup-dataset; kloppy loader — https://kloppy.pysport.org/user-guide/loading-data/pff/
- Narrative lineage: FiveThirtyEight, *Messi walks better than most players run* — https://fivethirtyeight.com/features/messi-walks-better-than-most-players-run/; Karun Singh's space-control talk — https://youtu.be/X9PrwPyolyU
