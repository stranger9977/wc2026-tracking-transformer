# Two-specialist transformer — findings

Trained two dedicated single-head transformers (score-only, concede-only) on
the same architecture as the existing shared-backbone frame-VAEP model
(2 layers × 4 heads × 64 dim, same 36-train / 8-val split, 6 epochs), then
extracted attention from each across all PFF WC22 matches with tracking and
compared.

## 1. Val AUCs (best epoch, held-out 8-match split)

| Model | val_auc_score | val_auc_concede |
|---|---:|---:|
| Shared (two-head, deployed) | **0.801** | **0.792** |
| Score specialist | **0.816** | — |
| Concede specialist | — | **0.799** |

Both specialists beat the shared model on their respective head, **modestly**
(+0.015 score, +0.007 concede). Not a step-change. The shared backbone is
already optimising well; pinning the loss to one head buys a little more
headroom but the representation budget is mostly the same.

## 2. Top-10 off-off pairs — RAW attention

### Score specialist (NEW vs the shared model bolded)

| # | Team | Pair | Attention |
|---|---|---|---:|
| 1 | France | **Dembélé + Mbappé** | 9,361 |
| 2 | France | Griezmann + Mbappé | 8,428 |
| 3 | France | Mbappé + Tchouaméni | 8,004 |
| 4 | Morocco | **Boufal + Ziyech** | 7,984 |
| 5 | Croatia | Modrić + Perišić | 7,416 |
| 6 | Croatia | **Kramarić + Perišić** | 7,157 |
| 7 | Brazil | **Vinícius + Raphinha** | 7,073 |
| 8 | Morocco | Ziyech + Amrabat | 6,893 |
| 9 | Argentina | Mac Allister + Messi | 6,828 |
| 10 | Argentina | **Messi + Enzo Fernandez** | 6,585 |

### Shared model (for comparison)

| # | Team | Pair | Attention |
|---|---|---|---:|
| 1 | France | Griezmann + Mbappé | 7,664 |
| 2 | France | Mbappé + Tchouaméni | 7,609 |
| 3 | Croatia | Modrić + Perišić | 7,000 |
| 4 | Morocco | Ziyech + Amrabat | 6,866 |
| 5 | Croatia | Kovačić + Perišić | 6,730 |
| 6 | France | Mbappé + Rabiot | 6,709 |
| 7 | France | Dembélé + Mbappé | 6,661 |
| 8 | Argentina | Mac Allister + Messi | 6,368 |
| 9 | Argentina | Messi + de Paul | 6,192 |
| 10 | Croatia | Kovačić + Modrić | 6,149 |

**Overlap: 7/10.** Score specialist surfaces 5 new pairs:
Dembélé + Mbappé at #1 (the France right-flank duo, which was #7 on shared),
Boufal + Ziyech, Kramarić + Perišić, Vinícius + Raphinha (Brazil RM duo,
not in shared top-10 at all), Messi + Enzo Fernandez.

### Comparison with the score-frame conditional view

The conditional view (`When scoring vs neutral` tab) surfaces a
**fundamentally different** set: Morocco's Ziyech + Hamdallah / Aboukhlal /
Ounahi / En-Nesyri, USA Sargent + Musah, Uruguay Pellistri + Valverde +
De Arrascaeta. **0/20 overlap with the raw shared-model leaderboard.**

The score specialist's RAW view sits between the two — it surfaces some new
attacking pairs but mostly reproduces the shared-model's preferred
attacking-line-of-the-tournament structure. The conditional filter (frames
that actually lead to a goal) is doing more interpretive work than the
specialist training.

## 3. Argentina PSG triangle test

Players: Messi (1531), Di María (3868), Paredes (3856). Only 2 of the 3
intra-triangle permutations clear the ≥ 30-min cutoff at WC22.

| | Score specialist | Shared model |
|---|---:|---:|
| Triangle (both PSG) mean attn | 2,321 | 2,111 |
| One PSG mean attn | 2,721 | 2,505 |
| Neither PSG mean attn | 2,530 | 2,373 |
| **Triangle / neither ratio** | **0.92×** | **0.89×** |

**The score specialist does NOT see the PSG triangle as special.** The
triangle is slightly *below* the team baseline on both models. Messi +
Di María (the highest pair within the triangle on attention) clocks 2,862
against a team mean of 2,530 — modestly above the median but not the
heavy lift the JOI data shows.

**Compare to JOI**: Messi + Di María had JOI90 = 0.33, by far Messi's top
pair. The ARG ex-PSG pair-mean of 0.12 vs 0.02 for non-PSG ARG pairs is
a 6× event-data differential.

**Verdict**: the PSG rehearsal effect is **event-bound** (high on-ball JOI)
and **invisible in tracking attention**. The Argentina PSG triangle's
chemistry is "we pass to each other a lot," not "we're geometrically
attuned to each other off the ball." The "rehearsal carries over" story
holds in *on-ball* chemistry but not in the off-ball geometry the
transformer learns.

## 4. Historical-shared-club regression — score-specialist attention

`score_specialist_attention_per90 ~ prior_shared_minutes`, n = 3,443 pairs
(≥30 min at WC22, both players' club history known):

| Test | Result |
|---|---|
| Pearson r | **+0.051** (p = 0.003) |
| Spearman ρ | **+0.036** (p = 0.034) |

Weakly positive at the population level, statistically significant only
because n is huge. Effect size trivial in absolute terms.

### Per-nation, ever vs never shared-club (score-specialist attn_per90)

| Nation | Ever-shared mean | Never-shared mean | Δ | MW p (ever > never) |
|---|---:|---:|---:|---:|
| 🇩🇪 **Germany** | **1,366** (n=29) | **894** (n=76) | **+471** | **< 0.001** |
| 🇫🇷 France | 1,317 (n=24) | 1,470 (n=138) | −153 | 0.66 |
| 🇪🇸 Spain | 1,279 (n=25) | 1,503 (n=100) | −224 | 0.88 |
| 🇦🇷 Argentina | 1,030 (n=16) | 1,215 (n=111) | −185 | 0.95 |
| 🇳🇱 Netherlands | 890 (n=21) | 1,112 (n=86) | −221 | 0.92 |
| 🏴 England | 838 (n=15) | 853 (n=106) | −15 | 0.43 |
| 🇧🇷 Brazil | 1,293 (n=22) | 1,358 (n=155) | −66 | 0.21 |

**The Germany Bayern reversal is the headline.** Germany was the WORST
JOI cluster (Δ JOI90 = −0.101). On score-specialist attention it's the
ONLY nation with a clean significant positive shared-history signal
(Δ = +471, p < 0.001). The two metrics literally disagree on the same team.

Possible interpretations:
- The model attends to Germany's Bayern cluster as if they should produce
  more (their off-ball geometry looks like a scoring team) — but the
  on-ball events say they didn't convert.
- Germany 2022 looked like a scoring side and underperformed.
- The score specialist learned "this is what offensive Bayern looks like"
  during training, then Germany failed to execute it.

Either way: **the rehearsal hypothesis is reborn under tracking attention
and stays dead under event chemistry.** The story isn't "rehearsal doesn't
matter" — it's "the model *thinks* rehearsal matters, the outcomes don't
bear it out."

## 5. Site-view decision

**Hold the 5th leaderboard tab.** The score specialist's RAW view only
differs from the shared model in 3 of the top 10 off-off pairs, and the
new pairs (Dembélé+Mbappé, Vinícius+Raphinha) are easily framed as small
edits to the existing attacking-line story. The **conditional ("When
scoring vs neutral")** tab does the cleaner interpretive work — surfacing
Morocco/USA/Uruguay pairs that *neither* the shared model's raw view nor
the score specialist's raw view surface. That's where the editorial
energy belongs.

The Germany-Bayern reversal **is** worth surfacing — but on the
Club v National page as a "rehearsal-then-execution" sub-card, not as a
leaderboard tab. (See `rehearsal_card_draft.md` — the Act 3 line can
now be filled in: "the tracking model picked up Germany's Bayern
rehearsal pattern, but the on-ball outcomes didn't.")

## Files

- `research/data/attention_chemistry_score_specialist.parquet` (44 matches, 18,534 rows)
- `research/data/attention_chemistry_concede_specialist.parquet` (43 matches, 18,032 rows)
- `output/transformer_score_only.ckpt` (val AUC 0.816)
- `output/transformer_concede_only.ckpt` (val AUC 0.799)
- `output/training_metrics_score_only.json`, `output/training_metrics_concede_only.json`

## Open follow-up

- The Germany Bayern result is a 1-team headline. Worth probing whether
  the model's "they should produce" attention pattern is a training-set
  prior (Bayern look like a top-of-the-table team because they were in
  Bundesliga training data) vs a real WC22-specific signal. Beyond this
  agent's scope.
