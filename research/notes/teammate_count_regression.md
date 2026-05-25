# Player-level teammate-count regression — JOI vs. prior shared minutes

**Question:** does the number (or total minutes) of WC22 teammates a player has
prior shared history with predict that player's mean JOI90 at the tournament?

**Hypothesis:** if "rehearsal carries over," players surrounded by familiar
teammates should produce more chemistry-driven value than players surrounded
by relative strangers.

**Verdict:** null. Same as the pair-level regression. JOI does not pick up
the signal at any aggregation level.

## Method

1. Loaded `research/data/pair_prior_minutes.parquet` — every same-team WC22 pair
   with ≥30 min together at the tournament and known club history for both
   players.
2. Long-melted so each row is `(player_id, teammate_id, joi90, prior_shared_minutes)`.
3. Grouped by player → per-player aggregates:
   - `n_teammates_ever_shared` = count of pairs with `prior_shared_minutes > 0`
   - `total_prior_shared_minutes` = sum of prior shared minutes across qualifying teammates
   - `mean_joi90` = average JOI90 across the player's qualifying pairs
4. Filtered to players with ≥3 qualifying teammates → n = 613.
5. Regressed `mean_joi90` on each feature with Pearson + Spearman.

## Headline

| Predictor | Pearson r | p | Spearman ρ | p |
|---|---:|---:|---:|---:|
| `n_teammates_ever_shared` | +0.022 | 0.58 | +0.038 | 0.34 |
| `total_prior_shared_minutes` | +0.042 | 0.30 | +0.038 | 0.35 |

Both null. The slope is essentially zero. Knowing how many of a player's WC22
teammates they've shared a dressing room with before tells you nothing about
their actual chemistry production at the tournament.

## Top-15 players by total prior shared minutes (worth eyeballing)

| Player | Prior min | n ever-shared / n teammates | Mean JOI90 |
|---|---:|---|---:|
| **Thomas Müller** | 90,000 | 7 / 13 | **−0.015** |
| **Joshua Kimmich** | 90,000 | 7 / 17 | +0.146 |
| **Serge Gnabry** | 85,000 | 7 / 15 | +0.135 |
| Manuel Neuer | 77,500 | 6 / 13 | +0.031 |
| Niklas Süle | 70,000 | 7 / 15 | +0.092 |
| Leon Goretzka | 62,500 | 6 / 13 | +0.008 |
| **Leroy Sané** | 60,000 | 8 / 14 | **+0.245** |
| John Stones | 50,000 | 5 / 19 | +0.020 |
| Jamal Musiala | 50,000 | 7 / 15 | +0.141 |
| Sergio Busquets | 40,000 | 5 / 18 | +0.044 |
| Casemiro | 37,500 | 6 / 18 | +0.055 |
| Jordi Alba | 35,000 | 4 / 13 | +0.193 |
| Kyle Walker | 30,000 | 3 / 12 | +0.006 |
| Phil Foden | 30,000 | 4 / 16 | +0.087 |
| Vinícius Júnior | 30,000 | 4 / 13 | +0.166 |

The top of the list is dominated by Bayern + Germany. **Müller** is the
cleanest counter-example: most-rehearsed teammates in the dataset, JOI90 of
basically zero. **Sané** is the cleanest positive: high prior minutes *and*
+0.245 JOI90.

The variance across this Bayern cluster (Müller −0.015 vs Sané +0.245) is
larger than any cluster-level signal. Prior rehearsal isn't determining
who out-performs within the same cluster — individual form and tactical role
clearly are.

## Per-nation breakdown

| Nation | Mean ever-shared teammates per player | Mean player JOI90 | n players | WC22 stage |
|---|---:|---:|---:|---|
| Qatar | 4.1 | 0.056 | 17 | Group |
| Saudi Arabia | 4.0 | **0.036** | 20 | Group |
| Germany | 3.2 | **0.118** | 18 | Group |
| Spain | 2.7 | 0.067 | 19 | R16 |
| Netherlands | 2.5 | 0.091 | 17 | QF |
| France | 2.1 | 0.051 | 23 | Final |
| Portugal | 2.0 | 0.071 | 24 | QF |
| **Argentina** | **1.8** | 0.052 | 19 | **Winner** |
| Brazil | 1.8 | 0.069 | 25 | QF |
| England | 1.6 | 0.065 | 20 | QF |

The two most cluster-heavy nations (Qatar 4.1, Saudi Arabia 4.0) were both
group-stage exits. Germany has the highest mean player JOI90 of the
cluster-heavy set but also exited in the group stage. The least-clustered
elite nation in this list (Argentina, 1.8) **won**. England, Brazil, and
France — all low-to-mid clustered — went deep.

If anything the per-nation signal is the reverse of the hypothesis: cluster
size correlates inversely with tournament progression among the elite. (This
isn't formally tested — n=10 nations — it's just visible in the table.)

## Caveat: this used JOI as the chemistry metric

JOI is event-based — sum of VAEP across consecutive on-ball actions between
two teammates. The hypothesis we set out to test ("rehearsal carries over")
is most plausible for **off-ball automatisms**: third-man combos, decoy runs,
overlap handoffs. JOI doesn't see those.

The attention metric (which does see off-ball patterns) was tested too in
the parent analysis (`historical_chemistry_findings.md`) and showed a weak
positive (Pearson r = +0.065 on baseline attention, r = +0.040 on
score-frame attention). Both significant only because n is huge; effect
sizes trivial.

A cleaner test will come when the score-specialist model finishes training.
Its attention metric is built to capture offensive geometry; if the
"rehearsal carries over" hypothesis is real but currently masked by
defensive bias, the score-specialist's attention should reveal it.

**Until that lands: the hypothesis is null at every aggregation level we can
currently test it.**

## Files referenced

- `research/data/pair_prior_minutes.parquet` (input)
- `research/data/joi.parquet` (label source)
- `research/data/matches.parquet` (team-name lookup)
