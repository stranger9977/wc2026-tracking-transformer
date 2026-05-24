# Narrative QC — WC22 Player Chemistry site

**Audit date:** 2026-05-24
**Reader path:** Overview → What is Chemistry → Interactive Plays → Chemistry Leaderboards → Team Maps → Team Builder → Whiteboard → Club vs National → FIFA Mode → Methodology → Downloads.
**Central question the site must answer:** *Why do some players over-perform on their national team and others under-perform — is chemistry the missing variable?*

This QC pass treats the site as a first-time visitor on a single sitting.

---

## Per-tab audit

### 1. `index.html` — Overview

**Lede.** "What does chemistry look like on a football field?" Strong opening, but the lede paragraph defines chemistry as "how much two players' actions compound" — academic. The chemistry-travel question (the *point* of the video) isn't named in the first 60 lines; you have to scroll to "Why this matters for a World Cup."

**Strong moments.**
- The grid-2 plain-English JOI/JDI cards are clear and self-contained.
- The per-side "Tournament stories" cards with flag backgrounds and percentile sparklines are visually satisfying.
- The "How to read this site" two-card preview is a nice mental scaffold.

**Weak moments.**
- The chemistry-travel framing is buried in card #2, not the H1.
- The Top JOI/JDI cards are loaded from `data/overview.json` but `overview.json` was NOT regenerated with the new min-90/min-10 rule: `top_joi_pair` is still **Bamba Dieng + Youssouf Sabaly (Senegal, JOI90 = 1.91, 6 interactions)** — the exact small-sample artifact the new rule was meant to suppress. `qualification_rule` is `null`, so the explanatory note never renders.
- The "Tournament stories" Senegal card still elevates Dieng–Sabaly to "1.91/90" with a sparkline placing it at the top of the global distribution, contradicting the new headline.
- The "Story arc, tab by tab" footer links to `pairs.html` (legacy) and `transformer-chemistry.html` (legacy) instead of the unified `chemistry-leaderboard.html` named in the nav. Same with the `<a class="next-card" href="pairs.html">` next-card.

**Broken / contradictions.**
- Top JOI headline disagrees with `cross_chem.json` (which correctly headlines Joel Campbell + Brandon Aguilera).
- "Top Pairs (start here)" hand-off resolves to a page that itself says "This view has moved" and routes you back.

---

### 2. `what-is-chemistry.html`

**Lede.** "Chemistry is what happens between players when the ball isn't there." Strong — points the camera exactly where the video wants to look. Xavi/Jordet scanning citation gives credibility.

**Strong moments.**
- "Definition" card with the "I-already-looked pass" line is a quotable, video-ready frame.
- Twelve-mechanism grid (Third-Man, Pin, Decoy, Overlap, Press Trap, Gegen-swarm, Positional Rotations, Meat Wall, Near-Post Flick-On, Short-Corner Overload, Blind Pass, Rest-Defense) is the most concrete inventory on the site.
- "Strong/Mixed/Weak/Contaminated" signal card is honest about ball-token domination.

**Weak moments.**
- No named player ever appears in the body except Xavi, Saka, Rice. The cards talk about mechanisms abstractly; tying e.g. the Pin to "Mbappé pinning the right-back on Argentina-France" would land much harder.
- The "where they disagree" callout in the ball-token caveat is the only place the site teases the disagreement-leaderboard as the empirical pay-off — but it doesn't name a single pair (Ampadu–Allen would be the obvious one).

**Broken / contradictions.**
- "The Meat Wall" is listed as a Strong signal the model *could* see, but the Whiteboard has no corner-kick play, so the mechanism is unverifiable. The site never admits this gap.

---

### 3. `interactive-plays.html`

**Lede.** "See chemistry happen, frame by frame" — works. The body explains exactly what the reader will see.

**Strong moments.**
- "Three things to watch while scrubbing" bullets are precise and falsifiable.
- The differentiation from JOI/JDI ("event-level vs frame-level") is the clearest written explainer of that split anywhere on the site.

**Weak moments.**
- No example. Cold lede, no curated "start with this play" CTA. The reader sees `<div id="play-list">Loading clips…</div>` and waits.
- "Next →" hand-off goes to `methodology.html`. That skips Chemistry Leaderboards/Teams/Team Builder/Club v National entirely — the wrong direction for the central narrative.

**Broken / contradictions.** None.

---

### 4. `chemistry-leaderboard.html`

**Lede.** "Two ways of measuring chemistry, in one place." Adequate but functional — doesn't tell you *why* you'd read this leaderboard before any other.

**Strong moments.**
- Three-mode design (Event / Attention / Disagree) is the cleanest UI on the site.
- The "Where they disagree" callout box is the methodologically sharpest writing on the page.

**Weak moments.**
- **The disagreement view is the cleanest empirical answer to the video's central question, and it has no headline example.** Ampadu + Joe Allen (Wales) sits in the data with attention lift 2.69× on a midfield pair the JOI tables would never elevate; the page never says so.
- The Attention-based mode's lede paragraph is buried; the GK warning ("hidden by default") needs to be in the lede, not a `dim` line below it.
- No "Next →" hand-off block at the bottom. The reader is left without a clear path forward.

**Broken / contradictions.** None. (This page itself is internally consistent — it's the *anchor* the Overview should be aligned to.)

---

### 5. `teams.html`

**Lede.** Functional but transactional ("The Top Pairs leaderboards rank pairs as numbers. This tab puts those same pairs on a pitch"). No narrative hook.

**Strong moments.**
- The "Click any image to download the PNG" affordance is generous.
- Sort by "Most qualifying pairs" / "Most players used" is genuinely useful.

**Weak moments.**
- Links to `pairs.html` (legacy) in lede.
- The cards say nothing about *what to look for* on each team's map. A reader who clicks Argentina vs. England doesn't know what's interesting.
- No example callout (e.g., "Notice Croatia's midfield density; notice France's reliance on the left side").

**Broken / contradictions.**
- The terminology drift: "Top Pairs" (legacy) is used here while the nav says "Chemistry Leaderboards."

---

### 6. `team-builder.html`

**Lede.** "Given the chemistry signal … what eleven should each team actually have started?" — strong frame.

**Strong moments.**
- The Cross-Chemistry α slider (offensive vs defensive weighting) is a powerful interactive.
- The "Total chemistry score" stat is the kind of number a video can quote.

**Weak moments.**
- No example baked into the lede. A line like "For England, the MIP picks Bellingham over Phillips because it predicts a stronger Henderson–Bellingham link than Henderson–Phillips" would make the abstract MIP concrete in one sentence.
- Hand-off to Club v National is correct but generic.
- Same `pairs.html` legacy-link drift in the lede.

**Broken / contradictions.** None.

---

### 7. `whiteboard.html`

**Lede.** "Drag chemistry into a real play" — good, action-oriented.

**Strong moments.**
- The five curated plays (Di María 36', Mbappé 81', Memphis 10', Doan 48', Álvarez 39') are well chosen and reflect the WC22 highlight reel.
- The "How to read this" details panel is precise.
- Pre-computed counterfactuals + an ONNX freestyle button is technically impressive.

**Weak moments.**
- **No corner-kick play and no Meat Wall counterfactual.** The What-is-Chemistry tab lists Meat Wall as a "Strong signal" mechanism; the Whiteboard never demonstrates it. This is the user-named gap the brief flagged — and the site is silent about it.
- The five plays use only 6 of the 12 mechanisms (`third_man_triangle`, `the_pin`, `decoy_run`, `gegenpress_swarm`, `rest_defense`, `blind_pass`). Overlap/Underlap, Press Trap, Positional Rotations, Near-Post Flick-On, Short-Corner Overload, and Meat Wall are listed but never tested. No tab admits this.

**Broken / contradictions.**
- Half the inventory in `what-is-chemistry.html` is unsupported by the Whiteboard. The site presents the twelve-mechanism dossier as the schema and then quietly tests six.

---

### 8. `club-vs-national.html`

**Lede.** "Why does chemistry travel — or not?" — best lede on the site. This is the only tab that directly names the video's central question.

**Strong moments.**
- "Five stories from WC22" delivers the Mbappé / Hakimi / Havertz / Morata / Dieng player-cards with z-scores and supporting numbers. This is exactly the kind of narrative payload the video can use.
- The Havertz reversal (WC22 z = +1.5 → Euro 2024 z = −0.9) is the cleanest cross-tournament example anywhere.
- The three "Open questions" sections (stage trends / transfer-time / regression to mean) are an unusually honest scientific framing.
- The r = 0.03 Pearson on club↔WC22 OI/90 is computed and rendered with the right *argumentative* spin: "near-zero correlation … the chemistry-friction story has room to be real."

**Weak moments.**
- The brief's stated "Havertz reversal (z = +1.45 WC22 vs −0.88 club)" is *not* on the page. The site has WC22 = +1.5 vs Euro 2024 = −0.9 instead. Either the brief is using stale numbers or the site picked the wrong comparison; the on-site framing is defensible but not what the brief expects.
- The r = 0.03 result is buried under the third open-question header. It should be elevated — it's a top-line finding.
- "Bellingham … negative WC22-vs-club delta" is asserted in prose under §2 (Transfer hypothesis) but no chart pins it down.

**Broken / contradictions.**
- The r = 0.03 finding is the empirical backbone of the video, but it's not echoed on Overview, What-is-Chemistry, FIFA Mode, or Methodology.

---

### 9. `fifa-mode.html`

**Lede.** "Paper talent vs. what actually happened" — good, evocative.

**Strong moments.**
- The callout "The gap between paper rating and what actually happened is where chemistry lives" is a genuinely good thesis statement for the *whole site*.
- "Slope ≈ 0 (flat!)" annotation on the players-scatter is a visual the video can lift directly.
- The depth-gap argument (France 2022's top-11 / 12-23 gap) is a sharp tactical claim.

**Weak moments.**
- The flat-slope finding and the Club v National r = 0.03 finding are the two pieces of the same coin (paper talent doesn't predict national-team output; club output doesn't either). The page never links to the Club v National r = 0.03 number.
- The "five biggest team stories" and "headline over/underperformers" cards rely on JS to populate — there's no static fallback text saying "Argentina, Morocco, Croatia overperformed paper rank."
- "Next →" goes only to Club v National and Top Pairs; no link back into the Chemistry Leaderboard.

**Broken / contradictions.**
- The two findings the brief calls the "data spine of the video" (flat slope here, r = 0.03 on Club v National) live in adjacent tabs without referencing each other. They should be a single narrative beat repeated in both directions.

---

### 10. `methodology.html`

**Lede.** Functional academic. The four "plain English" pre-cards (VAEP / JOI-JDI / Attention / Whiteboard) are a strong on-ramp.

**Strong moments.**
- Section 1 (VAEP → JOI → JDI) has both math and Python excerpts and connects each to the relevant tab.
- Section 2 (Tracking transformer) is the cleanest single-page recap of architecture + 0.80/0.79 AUC + 0.714 Spearman ρ.
- Section 3 (Attention chemistry aggregation) explains the per-90 normalisation and the team-baseline lift correctly.
- Section 5 (Limitations) is unusually candid.

**Weak moments.**
- **No methodological coverage of the "where they disagree" view.** The chemistry-leaderboard page treats it as a first-class mode, but methodology never defines `|pct(JOI) − pct(attention)|` formally or names example pairs.
- No reference to the min-90 / min-10 qualifying rule. The Limitations bullet mentions "minimum-minutes filter" but doesn't name the threshold or rationale.
- No formal definition of OI/90 — it's used as a metric on Club v National and FIFA Mode but only defined in passing as "Bransen's offensive xT-like score."

**Broken / contradictions.**
- Limitations §5 says small samples are mitigated by "minimum-minutes filter on the Top Pairs tables." The Overview's `qualification_rule` field is `null` — so on the live site, no qualifying rule is being shown to the reader.

---

### 11. `downloads.html`

**Lede.** Inventory page. Functional.

**Strong moments.**
- Cleanly organised by data-pipeline stage (event / attention / cross-context / whiteboard / CSV / PNG / model artifacts).
- Honest about gitignored checkpoints with a rebuild-from-recipe pointer.

**Weak moments.**
- No closing narrative ("you've just read the argument; here's the receipts"). A short reprise of the video's central question at the top would land it.
- No link back to Methodology §6 (repro recipe) from the lede.

**Broken / contradictions.** None.

---

## Cross-tab contradiction log

| # | Where | Contradiction |
|---|-------|---------------|
| 1 | Overview top_joi_pair vs Chemistry Leaderboard / `cross_chem.json` | Overview headline is **Dieng + Sabaly (1.91 JOI90, 6 interactions)**, but the new rule headlines **Joel Campbell + Brandon Aguilera (1.65 JOI90, 15 interactions)**. Stale `data/overview.json`. |
| 2 | Overview `chemistry_stories.json` Senegal card | Calls Dieng–Sabaly "1.91/90" as Senegal's top JOI pair with a sparkline showing top-of-distribution — still using the un-filtered metric. |
| 3 | Overview "next" link vs nav | Nav says "Chemistry Leaderboards" → `chemistry-leaderboard.html`. Overview body and next-card link to `pairs.html` (legacy "moved" page). Same drift on Teams and Team Builder. |
| 4 | What-is-Chemistry "Strong signal" Meat Wall vs Whiteboard | Meat Wall is listed as a strong-signal mechanism, but the Whiteboard never instantiates it (no corner play). |
| 5 | Twelve-mechanism dossier vs Whiteboard | What-is-Chemistry lists 12 mechanisms; the Whiteboard tests 6 (third-man, pin, decoy, gegen-swarm, rest-defense, blind-pass). The remaining six (Overlap, Press Trap, Positional Rotations, Near-Post Flick-On, Short-Corner Overload, Meat Wall) are unsupported. The site never names this asymmetry. |
| 6 | Brief's Havertz "WC22 +1.45 vs club −0.88" vs site's Havertz card | Site uses Euro 2024 (−0.9) as the comparator, not club. Different finding from the brief. |
| 7 | FIFA Mode flat-slope ↔ Club v National r = 0.03 | These are two restatements of the same finding (paper-and-club talent both fail to predict WC22 output). Neither page references the other. |
| 8 | "Top Pairs" naming | Nav says "Chemistry Leaderboards." Most body links say "Top Pairs." Reader is told two different names for the same destination. |
| 9 | Methodology Limitations on min-minutes vs Overview live page | Methodology promises a "minimum-minutes filter on the Top Pairs tables"; Overview's `qualification_rule` field is `null` so no rule is displayed to the reader. |
| 10 | France story `chemistry_stories.json` | Mbappé–Thuram 1.10 JOI90 honest-hot-streak framing is *correctly* updated ("nine on-ball interactions, read as a hot streak"). This contradicts the still-unreformed Senegal story on the same page — the new framing applied unevenly. |

---

## Top 5 most actionable narrative fixes

1. **Regenerate `data/overview.json` with the min-90-min/min-10-interactions rule.**
   - File: `data/overview.json` (and the export script that produces it).
   - Expected `top_joi_pair`: Joel Campbell + Brandon Aguilera (Costa Rica, JOI90 = 1.65, 104 min, 15 interactions).
   - Also populate `qualification_rule` = `{min_minutes_together: 90, min_interactions: 10}` so the live caveat sentence renders.
   - Side effect: regenerate `chemistry_stories.json` so the Senegal card and any other team that had a sub-10-interaction headline shifts to the next-best qualifying pair.

2. **Wire the chemistry-travel question into the Overview H1 and the very first paragraph.**
   - File: `index.html`, around lines 37–48.
   - Replace H1 "What does chemistry look like on a football field?" with something like "Why do some players over-perform on their national team — and others under-perform? Chemistry is the missing variable."
   - First paragraph: name two specific players the reader knows — e.g. "Havertz outperformed peers at WC22 and underperformed two years later for the same Germany. Hakimi overlapped weekly for PSG but contained at Morocco. The chemistry-travel question is what this site measures."

3. **Surface Ampadu + Joe Allen (and 1–2 more disagreement-view pairs) as the headline empirical example of off-ball chemistry.**
   - Files: `what-is-chemistry.html` (the ball-token caveat callout) and `chemistry-leaderboard.html` (the "Where they disagree" section).
   - Body to add (verbatim, on Chemistry Leaderboards' disagreement callout): "The cleanest live example: Ethan Ampadu + Joe Allen (Wales). The transformer attends to them together 2.7× more than a baseline Wales pair, but the on-ball JOI tables wouldn't elevate them — they're a midfield-double-pivot that earns its keep off-the-ball."

4. **Link the FIFA flat-slope and the Club v National r = 0.03 findings to each other in both directions.**
   - File: `fifa-mode.html` — in the players-scatter callout, add: "The club-level analogue is the r = 0.03 Pearson between a player's club OI/90 and his WC22 OI/90 (see <a href='club-vs-national.html'>Club vs National</a>). Two different lenses, one finding: paper talent does not predict national-team output."
   - File: `club-vs-national.html` — in §3 (regression-to-mean), add a line: "EA's FIFA 23 Overall is no better — see <a href='fifa-mode.html'>FIFA Mode</a>'s flat-slope scatter for the player-level version of the same null result."

5. **Be honest about the Meat Wall / corner-kick gap on `what-is-chemistry.html` and `whiteboard.html`.**
   - File: `what-is-chemistry.html`, in the "Strong signal" card after the Meat Wall bullet.
   - Body to add: "Meat Wall and the other set-piece mechanisms (Near-Post Flick-On, Short-Corner Overload) are *not* yet tested on the Whiteboard — none of the five curated plays is a corner. A future iteration with an attacking set-piece sequence is the obvious next step; until then, treat the Meat Wall as a hypothesis the model *should* see, not a result it has confirmed."
   - File: `whiteboard.html`, beneath the "How to read this" panel.
   - Body to add: "Note: the five plays here cover 6 of the 12 mechanisms in <a href='what-is-chemistry.html'>What is Chemistry?</a>. Set-piece mechanisms (Meat Wall, Near-Post Flick-On, Short-Corner Overload) need a corner-kick play we haven't built yet."

---

## Verdict — does it tell the story?

**The site is two-thirds of the way to a coherent answer.** The pieces are all here: a working definition (What is Chemistry), the mechanism dossier (12 cards), the on-ball leaderboard (Chemistry Leaderboards), the off-ball complement (attention pairs and the disagreement view), the cross-tournament test (Club vs National's z-scored stories), and the null-model baseline (FIFA Mode). Individually, each tab is good — Club vs National in particular reads like a finished piece.

**What stops it from telling the story end-to-end:**

1. The Overview still preaches the un-filtered Dieng–Sabaly headline, so the first thing a new visitor sees contradicts the methodology two clicks later.
2. The single most narrative-rich finding — the disagreement-view pair Ampadu–Allen — exists only in JSON. No tab tells the reader to look at it.
3. The two empirical null results (FIFA flat slope, club↔national r = 0.03) live in adjacent tabs without referencing each other. They should be the same sentence, told twice.
4. The Whiteboard validates 6 of the 12 mechanisms in the dossier and the site never says so. A reader who counts is owed honesty.
5. The "chemistry travel" question, which the video is literally about, is the H1 on exactly one tab (Club v National). Everywhere else it's implied, never named.

Fix items 1, 2, and 4 (the cross-tab inconsistencies), surface the disagreement-view example (item 3), and the site goes from "good components" to "single coherent argument." The bones are there; this is an editorial pass, not a re-architecture.
