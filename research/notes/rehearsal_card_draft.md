# Card draft — "Does rehearsal carry over?"
**Slot:** new section on `research/site/club-vs-national.html`, between the regression-to-mean section and the "Implications for 2026" closer.

This is the structure. Final HTML/JS comes after the training agent fills in the `${SCORE_SPECIALIST_PSG_RATIO}` placeholder.

---

## Section: Does club rehearsal carry over to the national team?

> The lore is suspicious. Spain 2010 (6 Barça starters) won. Germany 2014
> (7 Bayern) won. Surely the rehearsed automatisms travel.
>
> **They don't — at least, not in 2022.**

### Act 1 · The bold claim fails

For every WC22 same-team pair where we know both players' club histories,
we computed `prior_shared_minutes` (the total minutes they had previously
spent on the pitch together at any club). Then regressed pair JOI90 at
WC22 against that.

**Pooled, n = 3,774 pairs**:

| Test | Result |
|---|---|
| JOI90 ~ prior_shared_minutes (Pearson) | r = **−0.006** (p = 0.72) |
| Spearman | ρ = +0.011 (p = 0.51) |

Flat. Nothing.

The big clusters of WC22 reversed the prediction outright:

| Cluster | Δ JOI90 (ever-shared vs never-shared) |
|---|---:|
| Germany Bayern (7 starters) | **−0.101** ← worst |
| Netherlands Ajax | −0.050 |
| England Man City | −0.048 |
| France PSG / Bayern | −0.035 |
| Brazil Real Madrid | +0.040 (small) |

Bayern is the cleanest counter-example. **Müller had 90,000 prior minutes
on the pitch with his WC22 teammates, more than any other player in the
dataset. His mean JOI90 at WC22: −0.015.** Sané, also Bayern, has a much
smaller history but a +0.245 JOI90 — the variance *inside* the cluster is
larger than any cluster-level signal.

Per-nation, the pattern is the inverse of the lore: the most-clustered nations
(Qatar 4.1 shared teammates/player, Saudi Arabia 4.0) were both group-stage
exits. **The least-clustered elite nation — Argentina, with 1.8 ever-shared
teammates per player — won.**

### Act 2 · But there's a case study that survives

Argentina is interesting precisely because its squad *had no current club
cluster* — by November 2022 Di María and Paredes had moved from PSG to
Juventus, leaving Messi as the only current PSG player. Cluster size at
WC22 time = 1.

But carve the squad by *historical* PSG ties (the 2018–22 triangle):

| | Mean JOI90 | n pairs |
|---|---:|---:|
| At least one ex-PSG player | **0.120** | 40 |
| Neither ex-PSG | 0.019 | 89 |

**A 6× chemistry differential.** Messi's top JOI partner at WC22: Di María
(JOI90 = 0.33, by far his highest). The rehearsal **did** carry over —
for those three players specifically.

So the broad claim ("clusters predict chemistry") is dead, but the narrow
claim ("elite triangles rehearsed at the highest club level may carry
over") survives in one rich case.

### Act 3 · Does the model see what we just saw?

JOI is event-based — it sees on-ball production. The tracking transformer
sees the off-ball stuff: who runs into space, who pulls a defender, who
makes themselves the third-man option. If the PSG triangle is real
chemistry rather than just sample noise on Messi's natural ability, the
model's offensive geometry should attend to those three above its baseline.

We trained a score-specialist transformer (built to attend to offensive
geometry specifically, not the GK/defender bias of the shared model).
Then we asked: among Argentina's same-team pairs, what's the attention
ratio for the PSG triangle vs the rest?

> ${SCORE_SPECIALIST_PSG_RATIO}
> *(filled in once the training agent returns)*

If that ratio is >1.5×, the off-ball model corroborates the event data —
the rehearsal is *visible* to the eye that wasn't given a hint. If it's
~1, the rehearsal pattern only lives in on-ball events, which is its own
finding about what tracking attention can and can't recover.

### What this means for 2026

Don't draft your bracket off cluster size. Of the WC22 cluster-heavy
squads, only one (Brazil, partial Real Madrid set) had a measurable
positive chemistry bump from it. **The rehearsal that survives looks
specific, named, and small — not structural.**

If you're betting on a triangle in 2026, bet on a specific named one. The
"Spain are basically Barça" heuristic doesn't reproduce.

---

## Implementation TODO

1. Wait for training agent to return with `${SCORE_SPECIALIST_PSG_RATIO}`.
2. Convert this draft to HTML (4-card structure: Act 1 stats / Act 2 stats / Act 3 stats / 2026 close).
3. Add an inline bar chart showing the per-cluster Δ JOI90 (Germany Bayern bar pointing −0.101, France/Ajax/City negative, Brazil small positive).
4. Add a side-by-side mini-table for the Argentina PSG-triangle stat.
5. Embed in `club-vs-national.html` between `#hyp-mean` and the `<h2>Implications for 2026</h2>` block.
6. Cross-link from `what-is-chemistry.html` mechanisms section so the "third-man triangle" entry points at the live Argentina case study.

Files to touch when ready:
- `research/site/club-vs-national.html` — add the section
- `research/site/data/rehearsal_card.json` — the per-cluster bar chart data (new file)
- `research/site/assets/js/club-vs-national-extras.js` — render the bar chart and read the Argentina ratio

No CSS changes needed — reuse `.card`, `.callout`, `.story-card`, existing chip styles.
