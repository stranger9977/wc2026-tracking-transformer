# Chemistry Concepts Dossier

A research dossier of what soccer people (coaches, players, analysts, fans) actually mean when they say a pairing or team has "chemistry." Compiled to feed (a) the Digital Whiteboard agent — which needs concrete drag-the-player counterfactuals — and (b) the "What is Chemistry?" narrative tab.

Working definition used throughout: **Chemistry is the unspoken, repeatable understanding that lets two or more players coordinate spatially without a verbal call** — sometimes through rehearsed automatisms, sometimes through emergent peripheral awareness, sometimes through pure pattern-matching from playing together for years. The taxonomy below tries to break that into mechanisms that are *individually testable* with tracking data and tracking-attention.

---

## Table of contents

1. [The Third-Man Triangle](#1-the-third-man-triangle)
2. [The Pin (Fixing the Defender)](#2-the-pin-fixing-the-defender)
3. [The Decoy Run](#3-the-decoy-run)
4. [The Overlap / Underlap Handoff](#4-the-overlap--underlap-handoff)
5. [The Press Trap (De Zerbi Bait)](#5-the-press-trap-de-zerbi-bait)
6. [Gegenpressing Swarm](#6-gegenpressing-swarm)
7. [Positional Rotations](#7-positional-rotations)
8. [The Meat Wall](#8-the-meat-wall)
9. [Near-Post Flick-On](#9-near-post-flick-on)
10. [Short-Corner Overload](#10-short-corner-overload)
11. [The Blind Pass / Scan-and-Release](#11-the-blind-pass--scan-and-release)
12. [Rest-Defense Anchoring](#12-rest-defense-anchoring)

After the taxonomy: **["What does our model actually see as chemistry?"](#what-does-our-model-actually-see-as-chemistry)** — an analysis of where transformer attention should and shouldn't pick up each mechanism, plus open empirical questions.

---

## 1. The Third-Man Triangle

**What it is.** A possession sequence in which the ball goes from player A to player B, and B's first-time pass releases a *third* player C who never touched the ball with A. The defenders track A's pass and B's body, but C is moving into space behind their eye-line.

**Where you see it.** Open-play build-up, especially against high man-oriented presses. Iconic against opponents who pressure the ball-carrier hard.

**Famous example.** Xavi → Iniesta → Messi sequences in 2009–2012 Barcelona; Manchester City under Pep weaponized it from the half-spaces. Pep is repeatedly quoted: *"The third man is impossible to defend."* ([Phase of Play](https://www.phaseofplay.com/post/third-man-is-impossible-to-defend), [Coaches' Voice](https://learning.coachesvoice.com/cv/third-man-runs-football-tactics-explained-gasperini-guardiola/))

**Why it's "chemistry" and not just a play call.** The pass A→B is read by *anyone*. The off-ball positioning of C ahead of time — anticipating that B will turn and release first-time — is the part that requires playing-together intuition: C has to read B's body before B has the ball. That's not call-able from the touchline.

**Does it move the ball?** Yes (eventually) — but the *chemistry* lives in the off-ball third-runner's pre-positioning, which event data only sees as the receiver tag at the end. The 2-second prep is invisible to JOI/JDI.

**Whiteboard counterfactual.** Drag C 5m closer to A→B's line. Does the model's predicted xT drop? If yes, the value was in C being *behind* the defenders' eye-line, not just being open. Conversely, drag B 3m further from A — does the through-pass to C still exist? Tests whether the chain depends on B's first-time release.

---

## 2. The Pin (Fixing the Defender)

**What it is.** An off-ball attacker stands in a position so threatening that a defender refuses to leave them, even though the ball is elsewhere. The "pinned" defender becomes a hole-puncher for the attacking shape — their gravity opens a lane somewhere else.

**Where you see it.** Open play, especially with wide forwards pinning fullbacks ("hold the width"), or a striker pinning the last center-back to keep the line deep.

**Famous example.** Bukayo Saka holding the width to pin Arsenal opponents' left-back so an underlap opens for the right-half-space runner. ([Arsenal Fanatics on Timber's underlap](https://www.facebook.com/ArsenalFanaticsNews/posts/timberdecoy-run-underneath-to-pin-the-fullback-stop-them-from-jumping-out-to-int/1322517656551708/)) Pep's wide forwards under instruction to *not* tuck inside until the ball is in the opposite half-space.

**Why it's "chemistry" and not just a play call.** It IS a coached call ("stay wide"), but the chemistry layer is *which* teammate the pinner is opening space for, and the *timing* — pinning works only if a runner arrives the instant the defender's gaze locks. The runner reads the pinner's commitment to the wide line.

**Does it move the ball?** No. The pinner often touches the ball zero times in the sequence. Pure off-ball mechanic — invisible to event data.

**Whiteboard counterfactual.** Drag the wide forward 4m narrower. Does the inside fullback step out? If yes, the inside-channel attacker should lose value. Drag them back wide — does the channel reopen? Direct test of "pinning gravity."

---

## 3. The Decoy Run

**What it is.** A player makes a sharp, committed run toward space or goal *without expecting the ball*, intending only to drag a defender out of position. Closely related to the dummy run; the line between "I'm trying to receive" and "I'm trying to be tracked" is the defender's job to read, which is exactly why it works. ([Soccer Wizdom on dummy runs](https://soccerwizdom.com/2024/10/23/mastering-the-art-of-the-dummy-run-in-soccer/), [Total Football Analysis](https://totalfootballanalysis.com/article/tactical-theory-using-full-backs-as-decoys-in-transition-tactical-analysis-tactics))

**Where you see it.** Open play, especially transition; also in deep free kicks where attackers make runs to bend the defensive line. ([TFA on deep free-kick runs](https://totalfootballanalysis.com/set-piece-analysis/deep-runs-free-kicks-set-piece-tactical-analysis-tactics))

**Famous example.** Thomas Müller's "Raumdeuter" identity — full career built on decoy runs that pull center-backs and create lanes for Lewandowski or Gnabry. France's near-post runner on Mbappé crosses repeatedly pulled the inside-CB away, opening the back-post for Giroud at Euro 2024 / Nations League.

**Why it's "chemistry" and not just a play call.** The decoy and the actual ball-receiver must share a read of *which* defender is the one to pull. Two strikers without chemistry will both run into the same channel; chemistry is when one fakes the other's run and peels off.

**Does it move the ball?** No. The decoy by definition does not receive the ball.

**Whiteboard counterfactual.** Freeze the decoy in place (don't let them sprint forward). Does the actual receiver still find a lane? If the model says no, the decoy was load-bearing. This is the cleanest "off-ball chemistry" test we have.

---

## 4. The Overlap / Underlap Handoff

**What it is.** A two-player wide-channel handoff. *Overlap*: the fullback runs outside the winger, creating a 2v1. *Underlap*: the fullback (or midfielder) runs inside the winger through the half-space. ([The Football Analyst on overlaps](https://the-footballanalyst.com/arsenal-mikel-arteta-tactical-analysis/), [TFA on full-back overlap/underlap](https://totalfootballanalysis.com/tactical-theory/full-back-overlap-underlap-principles-tactical-theory-analysis-tactics))

**Where you see it.** Settled possession in the final third, especially at the wing-to-half-space boundary.

**Famous example.** Trent Alexander-Arnold + Mo Salah at Liverpool 2018–2023 — perhaps the most empirically chemistry-rich wide pairing of the era. Ben White + Bukayo Saka at Arsenal under Arteta, where White's underlap forces the inside-FB to choose. ([The Football Analyst on Arsenal](https://the-footballanalyst.com/arsenal-mikel-arteta-tactical-analysis/))

**Why it's "chemistry" and not just a play call.** Whether to overlap or underlap is a real-time choice based on (a) the winger's body shape and (b) which way the FB is shaded. Pairs with chemistry don't talk — the FB reads the winger's hips. Trent/Salah famously almost never had to call it.

**Does it move the ball?** Yes — there's almost always a pass between the two. Event data sees this one *partially* (it sees the pass) but misses the decision tree (which run was offered, which was rejected).

**Whiteboard counterfactual.** Toggle the fullback's run from overlap to underlap. Does the predicted xT change shape (more crosses vs. more cutbacks)? Does the inside-CB stay vs. step?

---

## 5. The Press Trap (De Zerbi Bait)

**What it is.** A team in possession deliberately invites the opponent's press by playing slow, low passes near their own box, planting a foot on the ball, then exploding vertically the instant the press commits. ([Sky Sports on De Zerbi](https://www.skysports.com/football/news/11095/12810847/roberto-de-zerbis-brighton-tactics-explained-provoking-the-opposition-press-by-becoming-the-possession-kings), [SoccerTutor on De Zerbi's baiting](https://www.soccertutor.com/blogs/inside-football-coaching/de-zerbis-tactics-bait-the-press-build-up-play))

**Where you see it.** Goal-kicks and deep build-up.

**Famous example.** Roberto De Zerbi's Brighton (2022–2024), then Marseille. The "foot on the ball" trigger is his signature. De Zerbi: *"If you receive the ball with the sole and from the front, you can play for the side you want. There you have total control of the ball."* ([SoccerTutor blog](https://www.soccertutor.com/blogs/inside-football-coaching/de-zerbis-tactics-bait-the-press-build-up-play))

**Why it's "chemistry" and not just a play call.** Every player in the chain has to hold their nerve and *not* bail out early. The CB on the ball trusts that the pivot will check in at the exact moment the press triggers; the pivot trusts that the wide forward is sprinting in behind. Chemistry = collective comfort with deliberate vulnerability.

**Does it move the ball?** Yes (the trap *ends* with a forward pass), but the chemistry signal is in the *positions held during the bait* — who stays calm, who checks in early.

**Whiteboard counterfactual.** Move the CB 5m further from the box (less inviting bait). Does the opponent press commit less? Does the vertical option open less? Tests whether the trap depends on the proximity of the bait to danger.

---

## 6. Gegenpressing Swarm

**What it is.** The instant possession is lost, the closest 3–4 players collapse on the ball-carrier within ~5 seconds, trying to win it back before the opponent's transition organizes. Klopp's signature, articulated by him as: *"No playmaker in the world can be as good as a good gegenpressing situation."* ([Klopp quote, Fussballcoaches](https://www.fussballcoaches.com/en/post/counter-pressing-is-the-best-playmaker-j%C3%BCrgen-klopp), [Sky Sports on Klopp](https://www.skysports.com/football/news/11661/11729575/why-jurgen-klopps-gegenpressing-with-dortmund-was-revolutionary))

**Where you see it.** Defensive transitions, especially in the attacking and middle thirds.

**Famous example.** Klopp's Liverpool 2018–19; Dortmund 2012–13. The "5-second rule" is its hallmark; the trigger is a loose touch or a backwards/sideways pass under pressure. ([SoccerEDU on gegenpressing](https://www.socceredu.com/en-US/blog/counter-pressing-soccer))

**Why it's "chemistry" and not just a play call.** The trigger is reactive — players have milliseconds to commit. A 3-man swarm only works if all three read the same trigger at the same instant. Klopp's drilled triggers are doctrine, but who-presses-which-passing-lane is chemistry.

**Does it move the ball?** No (the ball is lost). This is *defensive* chemistry, of which event data sees almost none.

**Whiteboard counterfactual.** Move one of the swarming players 8m further away at the moment of turnover. Does opponent escape probability rise? Tests whether the swarm's compactness was load-bearing vs. one specific player.

---

## 7. Positional Rotations

**What it is.** Coordinated swaps of position between teammates during a possession sequence — e.g., the inside-fullback steps into midfield, the central midfielder drops into the back line, the winger tucks into the half-space. Pep's Manchester City made this their signature. ([SoccerTutor: Pep's rotations](https://www.soccertutor.com/products/pep-guardiola-coaching-positional-rotations), [The Football Analyst on inverted fullbacks](https://the-footballanalyst.com/inverted-fullbacks-football-tactics-explained/))

**Where you see it.** Settled possession, build-up phase, half-space attacks.

**Famous example.** Cancelo / Zinchenko as inverted fullbacks 2021–23. The "five-lane" Juego de Posición framework codifies the rotations: only three players per horizontal line, only two per vertical line. ([Coaches' Voice on positional play](https://learning.coachesvoice.com/cv/positional-play-football-tactics-explained-guardiola-cruyff-manchester-city/), [Breaking The Lines on Juego de Posición](https://breakingthelines.com/tactical-analysis/what-is-juego-de-posicion/))

**Why it's "chemistry" and not just a play call.** The principle is coached (one in, one out — never both in the same lane). But *which* of the three eligible players makes the rotation is a real-time negotiation. Two teammates with chemistry don't double up; two without chemistry crowd each other's space.

**Does it move the ball?** Sometimes. The rotation itself is off-ball, but it's usually triggered by a ball circulation pattern. Event data sees the passes but not the *swap*.

**Whiteboard counterfactual.** Force the inside-fullback to stay wide. Does the central midfielder occupy the half-space instead, or do both leave it empty? Tests the rotational rule against pure individual habit.

---

## 8. The Meat Wall

**What it is.** On an in-swinging corner toward the 6-yard box, the attacking team places 2–3 large players directly in the goalkeeper's path, screening the keeper from claiming the ball. Plus a separate group blocking the front-zone defender(s). The cluster forms a "wall of bodies" between the keeper and the delivery zone. ([Expecting Goals on the Meat Wall era](https://www.expectinggoals.com/p/the-meat-wall-era-in-the-premier), [Expecting Goals: Origins of the Set-Piece Revolution](https://www.expectinggoals.com/p/the-origins-of-the-set-piece-revolution), [Sky Sports on Arsenal corners](https://www.skysports.com/football/news/11670/13415710/arsenals-goals-from-corners-how-can-premier-league-rivals-stop-mikel-arteta-and-nicolas-jovers-set-piece-tactics))

**Where you see it.** Corner kicks. Rising sharply in EPL 2024–26.

**Famous example.** Arsenal under Nicolas Jover, 2023–26 — they pioneered the modern version, with Ben White as the primary keeper-screener. ([TheCable on Jover](https://www.thecable.ng/nicolas-jover-the-set-piece-wizard-who-turned-arsenal-into-englands-dead-ball-king/)) 75%+ of Arsenal corners played to the 6-yard box. Number of attackers in the 6-yard box across the league rose ~70% in two seasons. Liverpool, Forest, Brentford, Palace, Bournemouth all adopted variants by 2025–26.

**Why it's "chemistry" and not just a play call.** It IS heavily rehearsed — Jover scripts who stands where. But the *micro-chemistry* is in the screener trio: who shifts when the keeper feints, who picks up the late runner if a defender breaks through. Anecdotal/coaching-folklore says Ben White and Gabriel "just know" which one of them peels off to attack the ball vs. continue to screen.

**Does it move the ball?** No — the screen-setters mostly don't touch the ball. The shot taker does. Pure off-ball spatial mechanism.

**Whiteboard counterfactual.** Remove the keeper-screener (drag them 5m wider). Does the model's xG-on-the-shot drop sharply? Does it preserve the value if the front-zone blockers stay? Tests which screen is doing the work.

---

## 9. Near-Post Flick-On

**What it is.** An in-swinging corner aimed at the near post, where an attacker rises early to glance the ball on with a header across the face of goal, behind the defensive line, for a back-post runner to finish. ([Coaching American Soccer on corner types](https://coachingamericansoccer.com/tactics-and-teamwork/types-of-corner-kicks/), [FIFA Training Centre](https://www.fifatrainingcentre.com/en/game/game-analysis/set-plays/corners/targeting-the-front-post.php))

**Where you see it.** Corners and wide free-kicks. Pre-dates the meat wall by decades.

**Famous example.** South Korea at the 2022 World Cup repeatedly targeted near-post flick-ons. ([FIFA Training Centre on near-post](https://www.fifatrainingcentre.com/en/game/game-analysis/set-plays/corners/targeting-the-front-post.php)) Classic Sam Allardyce / Tony Pulis routine at Bolton and Stoke. Bilbao under Bielsa drilled it relentlessly.

**Why it's "chemistry" and not just a play call.** Two-player chemistry: the flicker has to commit to a clearing header that *doesn't try to score*, trusting the back-post runner is timing into the right zone. Famous flickers (Peter Crouch, Andy Carroll) developed near-telepathic timing with specific back-post runners.

**Does it move the ball?** Yes (the flick is a ball touch). Event data sees the flick but doesn't model whether the back-post runner started moving *before* the corner was kicked, which is the chemistry part.

**Whiteboard counterfactual.** Shift the back-post runner's start position 4m. Does the xT of the flick-on drop? Tests timing dependency. Or: remove the flicker entirely and have the corner go straight to the back-post. Same xG?

---

## 10. Short-Corner Overload

**What it is.** Instead of crossing, the corner-taker plays a short pass to a teammate who has come to the corner flag, creating a 2v1 or 3v2 in the wide channel. They then combine to draw defenders out and deliver a cross or cutback from a better angle. ([Spielverlagerung: Tactical Theory Set-Pieces](https://spielverlagerung.com/2019/12/06/tactical-theory-set-pieces/), [Modern Soccer Coach](https://www.modernsoccercoach.com/post/msc-five-favorite-short-corner-kick-routines))

**Where you see it.** Corner kicks against teams committing all 10 outfield defenders to the box.

**Famous example.** Manchester City under Pep regularly used short corners to manipulate Arsenal/Liverpool's pre-set defensive blocks. Spain at Euro 2024 used them to draw man-markers and reset the angle.

**Why it's "chemistry" and not just a play call.** The taker and the receiver have to read the defending team's response in the first second after the short pass — does the closest defender step out (creating a passing lane back inside) or stay home (creating a 2v1 to the byline)? The pair's decision-making must be synchronized.

**Does it move the ball?** Yes — short corners are a chain of 2–4 ball touches. Event data sees them well, *except* for the bait/decoy positioning of the off-ball corner-kick attackers.

**Whiteboard counterfactual.** Move the receiver 3m further toward the byline. Does the defender step out? Does this open a 1-2 with the corner-taker? Tests how the geometry of the overload determines what comes next.

---

## 11. The Blind Pass / Scan-and-Release

**What it is.** A pass that looks like a "no-look" but is in fact the product of *pre-scanning*: the passer looked at the receiver's position 1–2 seconds *before* receiving the ball, built a mental model, then released first-time without needing to look again. Research by Geir Jordet found Xavi scanning ~0.8 times per second; FIFA World Player winners scan more frequently than peers. ([Sky Sports / Jordet on scanning](https://www.skysports.com/football/news/11096/12341305/kevin-de-bruyne-is-a-master-at-scanning-geir-jordet-on-the-science-behind-the-importance-of-vision-and-perception-in-football), [Frontiers paper on scanning](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2020.553813/full))

**Where you see it.** Open play, especially in midfield under pressure. Most visible when a player receives a backward pass and releases first-time forward without looking.

**Famous example.** Xavi: *"Think quickly, look for spaces. That's what I do: look for spaces. All day... I'm always looking... I see the space and pass."* ([Planet Football: Xavi quotes](https://www.planetfootball.com/quick-reads/17-quotes-explain-xavi-legend)) De Bruyne to Haaland: Haaland says *"I saw for many years where he plays the ball, and he hasn't changed for the last five years where he plays the ball."* ([EssentiallySports](https://www.essentiallysports.com/soccer-football-news-erling-haaland-with-kevin-de-bruyne-i-know-im-going-to-get-the-perfect-pass-nothing-bad-about-others/)) Kroos and Modrić — Casemiro: *"We didn't talk much, but we knew what the other liked."* ([Madrid Universal](https://madriduniversal.com/modric-opens-up-on-legendary-partnership-with-kroos-casemiro-at-real-madrid/))

**Why it's "chemistry" and not just a play call.** It's not really chemistry on the *passer's* side (that's individual skill — scanning). The chemistry is on the *receiver's* side: they trust that the passer's last scan registered them, so they make the run before the pass is hit. Anecdotal/coaching-folklore: the De Bruyne–Haaland understanding is built on Haaland running *because* he knows De Bruyne already saw him.

**Does it move the ball?** Yes — the pass is a ball touch. Event data captures the pass. It does NOT capture the scan, the trust, or the receiver's *anticipatory* run that came before.

**Whiteboard counterfactual.** Move the receiver's start position 5m. Does the model still predict the through-ball is on? If the receiver had committed early based on a scan, moving them late breaks the chain. (Hard test: the model has to be calibrated against pre-scan vs. post-scan windows.)

---

## 12. Rest-Defense Anchoring

**What it is.** While the team is attacking, certain players (usually 2 CBs + 1 holding midfielder, plus sometimes one inverted fullback) stay back and hold a structured shape *anticipating* the loss of possession. This shape is the "rest defense." Pep is the architect; the term is now standard. ([The Football Analyst on rest-attack](https://the-footballanalyst.com/rest-attack-football-tactics-explained/), [Squawka: What is rest defence?](https://www.squawka.com/en/features/tactical-explainer-what-is-rest-defence/))

**Where you see it.** Settled possession, especially during long build-up phases against counter-attacking opponents.

**Famous example.** Manchester City under Pep with Rodri + 2 CBs + Stones as inverted CB = canonical rest-defense quartet. They function as a 4-man counter-prevention unit while the other 6 attack.

**Why it's "chemistry" and not just a play call.** The shape is coached. The chemistry is in the constant micro-adjustments: when the ball-side winger drifts inside, which of the four rest-defenders shifts to cover the abandoned flank? They communicate by glance more than by call. Rodri + Dias + Akanji is a famous example of a back-three that "rotates without speaking."

**Does it move the ball?** No (these players are not in the attack). They mostly never touch the ball during the sequence. Event data is blind to this entirely — only tracking sees them.

**Whiteboard counterfactual.** Move the rest-defense holding midfielder 5m forward (closer to the attack). Does opponent counter-attack probability rise sharply? Tests whether their *positioning* alone is doing the deterrence, not their ball-actions.

---

## What does our model actually "see" as chemistry?

We have a transformer trained on PFF World Cup 2022 tracking data, predicting `max(xT) over the next K seconds` from all 22 players + ball. Its attention matrix is `(layers, heads, 23, 23)` — i.e., for every pair of tokens (player or ball), we have a learned weight at every frame.

### Where attention should pick up these mechanisms

**Strong signal expected:**

- **Pinning** (mechanism #2) — the pinned defender and the pinning attacker should attend to each other heavily even when the ball is far. The pin is a *spatial relationship* that doesn't involve the ball; pure tracking-attention territory. Event data sees zero of this.
- **Decoy runs** (#3) — similar to pinning, but dynamic. We'd expect attention to spike from the would-be receiver to the decoy at the moment the defender takes the bait. This is a signature off-ball signal.
- **Rest-defense anchoring** (#12) — the rest-defenders should attend to opposition forwards even during deep attack. If our model shows the holding midfielder attending to the opposition striker when the ball is in the attacking third, that's the model "seeing" rest defense as relevant.
- **The Meat Wall** (#8) — on a corner, the screener's attention should be on the keeper, not on the ball. Easy to check qualitatively.

**Mixed signal expected:**

- **Third-man triangle** (#1) — the third runner C should be attended-to by the on-ball player B even before the pass is made. Attention should *anticipate* the receiver. If we see this, the model is genuinely learning football. If C just gets attended after the ball arrives, the model is reactive.
- **Overlap/underlap** (#4) — the winger and the fullback should attend to each other persistently. Should be easy to find. But because the ball is between them, the ball-token will dominate.
- **Press trap** (#5), **Gegenpressing** (#6) — should appear as a cluster of attention onto the opponent ball-carrier across multiple of our attackers/pressers simultaneously. The "swarm" attention pattern.

**Weak / contaminated signal expected:**

- **Blind pass / scan-and-release** (#11) — the chemistry here is *temporal* (the scan happens 1–2 sec before the pass). Our single-frame attention won't capture it. We'd need to look at attention *trajectories* across frames to see the pre-scan window.
- **Positional rotations** (#7) — the rotation is a coordination over 3–5 seconds. Hard to see in instantaneous attention; better to look at the *change* in attention across the rotation window.

### The Big Caveat: Ball-Token Domination

Attention in tracking transformers is heavily dominated by the ball token — i.e., the player tokens mostly attend to the ball (the most "informative" token in any frame), and player-to-player attention is the *residual*. This means our headline attention scores conflate two things:

1. **"Who's near the action"** (proximity to the ball) — easy, almost trivial.
2. **"Who's relevant to the action even if they're not near the ball"** (the actual chemistry signal) — much harder.

Concretely: when Saka is pinning the opponent's left-back wide while the ball is at Rice in the center circle, we want the model to attend Saka↔left-back even though both are 40m from the ball. If the model only attends Saka↔ball and Rice↔ball, we've learned proximity, not chemistry.

**Mitigations** the analysis pipeline should consider:
- Compute attention excluding the ball-token row/column, or normalize by ball-distance.
- Compare attention between same-team and cross-team pairs — same-team chemistry (overlap, third-man) should differ from cross-team chemistry (pinning, marking).
- Decompose attention into "ball-mediated" vs. "off-ball" by looking at frames when the ball is far from both players in the pair.

### Open empirical questions (concrete things the site should answer)

1. **Attention–JOI gap.** For each pair (player_A, player_B) on the same team, plot `mean_attention_score` vs. `event-based JOI90` (or VAEP-pair-sum). The pairs that score *high attention but low JOI* are the pure off-ball chemistry pairs — the gold. The pairs that score high on both are well-known dynamic duos. The pairs high on JOI but low on attention are likely a bug or a model blind spot. The off-diagonal cases are the story.

2. **Pinning detection.** Define a feature: opposition defender's velocity when their assigned attacker holds a wide position and the ball is on the far side. Do the highest-attention cross-team pairs in our model correspond to the highest "pin index" pairs by this geometric measure?

3. **Third-man arrival.** For every pass A→B that leads to a first-time release to C, was C's attention from B elevated in the 2 seconds *before* B received the ball? If yes, the model is anticipating; if no, the model is reactive (and the chemistry signal is downstream of the pass, not upstream).

4. **Set-piece attention shapes.** On corners, plot the attention from each attacking screener to (a) the keeper, (b) the corner-taker, (c) the would-be shooter. Do Arsenal-style "meat wall" routines show qualitatively different attention shapes from teams that do not screen the keeper? If yes, attention is reading the *role* of each screener — that's a clean win for the model.

5. **Chemistry stability across club ↔ national team.** For pairs that play together at both club and country, is their attention-pair-score similar in both contexts, or does it shift? This is the sibling-project ([wc2026-chemistry](https://github.com/) event-based JOI work)'s headline question, in tracking form. If attention chemistry transfers but JOI chemistry doesn't, we've found something event data can't see — the holy grail for the WC '26 narrative.

---

## Most surprising / counter-intuitive things learned

- **The "meat wall" is much newer than I assumed** — the rugby-screen-the-keeper variant is essentially an Arteta/Jover invention from 2023, copy-pasted across the EPL in 2024–26. The number of attackers in the 6-yard box on corners rose ~70% in two seasons. Earlier Stoke/Bolton "near-post target man" routines are a different mechanism.
- **Scanning is measurable and is the upstream cause of "telepathy."** Geir Jordet's research at the Norwegian School of Sport Sciences shows Xavi scanned ~0.8 times per second; FIFA World Player winners scan significantly more than peers. The "no-look pass" is mostly "I-already-looked pass." That fundamentally changes how the site should frame chemistry: it's a *prediction* problem (the scan registers, the pass anticipates), not a paranormal one.
- **Pep's "five lanes" rule limits player count per line.** Never more than 3 on a horizontal line, never more than 2 on a vertical line. That's a *coordination constraint*, not a position assignment — exactly the kind of thing transformer attention could rediscover from raw tracking. A nice latent-structure check.

---

## Mechanisms I considered and rejected

- **"Pressing triggers"** as their own mechanism — folded into Gegenpressing Swarm (#6) since the trigger is the doctrinal *part*, not the chemistry part.
- **"Hold up play" / target-man chemistry** — real (Haaland holding off CBs for De Bruyne to arrive), but it's mostly individual physical play, not pair-level coordination. The chemistry here is captured better by #11 (scan-and-release) and #1 (third-man).
- **"Counter-attack chemistry"** as its own thing — too broad; gets decomposed into #6 (winning the ball back), #3 (decoy runs in transition), and #11 (vertical passes off scans).
- **"Goalkeeper sweeper-keeper chemistry"** — interesting but mostly a GK-vs-defensive-line phenomenon and our GK tokens are explicitly de-prioritized in the space/chemistry rankings.
- **"Penalty-area marking handoffs"** (zonal-to-man transitions on a corner) — real and important defensively, but tracking-attention should pick this up as a sub-case of cross-team chemistry pairs on set pieces; not enough public taxonomy material to write a clean entry.

---

## Sources

Coaches and players:
- [Pep Guardiola: Five Years in Quotes — Manchester City](https://www.mancity.com/features/ipep-quotes/)
- [SoccerTutor: De Zerbi Build-Up](https://www.soccertutor.com/blogs/inside-football-coaching/de-zerbis-tactics-bait-the-press-build-up-play)
- [Sky Sports: De Zerbi Brighton tactics](https://www.skysports.com/football/news/11095/12810847/roberto-de-zerbis-brighton-tactics-explained-provoking-the-opposition-press-by-becoming-the-possession-kings)
- [EssentiallySports: Haaland on De Bruyne](https://www.essentiallysports.com/soccer-football-news-erling-haaland-with-kevin-de-bruyne-i-know-im-going-to-get-the-perfect-pass-nothing-bad-about-others/)
- [Madrid Universal: Modrić on Kroos](https://madriduniversal.com/modric-opens-up-on-legendary-partnership-with-kroos-casemiro-at-real-madrid/)
- [Managing Madrid: Kroos on Modrić](https://www.managingmadrid.com/2023/2/13/23597368/kroos-modric-real-madrid-2023-news-quotes)
- [Planet Football: Xavi quotes](https://www.planetfootball.com/quick-reads/17-quotes-explain-xavi-legend)
- [Fussballcoaches: Klopp "counter-pressing is the best playmaker"](https://www.fussballcoaches.com/en/post/counter-pressing-is-the-best-playmaker-j%C3%BCrgen-klopp)
- [Coaches' Voice: Marcelo Bielsa coach watch](https://learning.coachesvoice.com/coach-watch-marcelo-bielsa-leeds-guardiola/)
- [Training Ground Guru: Bielsa philosophy](https://archive.trainingground.guru/articles/marcelo-bielsa-tactics-and-philosophy-of-a-cult-manager)

Tactics writers:
- [Spielverlagerung: Tactical Theory — Set-Pieces](https://spielverlagerung.com/2019/12/06/tactical-theory-set-pieces/)
- [Coaches' Voice: Third-man runs explained](https://learning.coachesvoice.com/cv/third-man-runs-football-tactics-explained-gasperini-guardiola/)
- [Coaches' Voice: Positional play explained](https://learning.coachesvoice.com/cv/positional-play-football-tactics-explained-guardiola-cruyff-manchester-city/)
- [Coaches' Voice: Xavi II on third-man](https://learning.coachesvoice.com/cv/xavi-tactics-barcelona-rijkaard-guardiola-third-man/)
- [Phase of Play: Third Man is impossible to defend](https://www.phaseofplay.com/post/third-man-is-impossible-to-defend)
- [Phase of Play: Klopp gegenpressing mastery](https://www.phaseofplay.com/post/jurgen-klopp-s-revolutionary-football-gegenpressing-and-counter-attacking-mastery)
- [Total Football Analysis: third-man principle](https://totalfootballanalysis.com/tactical-theory-third-man-tactical-analysis-tactics)
- [Total Football Analysis: full-back overlap/underlap](https://totalfootballanalysis.com/tactical-theory/full-back-overlap-underlap-principles-tactical-theory-analysis-tactics)
- [Total Football Analysis: deep runs from free kicks](https://totalfootballanalysis.com/set-piece-analysis/deep-runs-free-kicks-set-piece-tactical-analysis-tactics)
- [Total Football Analysis: positional rotations and rest defence](https://totalfootballanalysis.com/tactical-theory/how-do-positional-rotations-in-attack-affect-rest-defence-tactical-analysis-tactics)
- [The Football Analyst: Rest-Attack explained](https://the-footballanalyst.com/rest-attack-football-tactics-explained/)
- [The Football Analyst: Inverted fullbacks](https://the-footballanalyst.com/inverted-fullbacks-football-tactics-explained/)
- [The Football Analyst: Arteta Arsenal tactical analysis](https://the-footballanalyst.com/arsenal-mikel-arteta-tactical-analysis/)
- [Breaking The Lines: What is Juego de Posición](https://breakingthelines.com/tactical-analysis/what-is-juego-de-posicion/)
- [Squawka: What is Rest Defence](https://www.squawka.com/en/features/tactical-explainer-what-is-rest-defence/)
- [FourFourTwo: Inverted full-back tactics](https://www.fourfourtwo.com/features/the-inverted-full-back-football-tactics-explained)
- [Soccer Wizdom: Mastering the dummy run](https://soccerwizdom.com/2024/10/23/mastering-the-art-of-the-dummy-run-in-soccer/)

Set pieces:
- [Expecting Goals: Origins of the Set Piece Revolution (Michael Caley)](https://www.expectinggoals.com/p/the-origins-of-the-set-piece-revolution)
- [Expecting Goals: The Meat Wall Era in the Premier League](https://www.expectinggoals.com/p/the-meat-wall-era-in-the-premier)
- [Sky Sports: Arsenal corner tactics (Jover)](https://www.skysports.com/football/news/11670/13415710/arsenals-goals-from-corners-how-can-premier-league-rivals-stop-mikel-arteta-and-nicolas-jovers-set-piece-tactics)
- [Sky Sports: Set-piece precision and Arsenal/Man City contrast](https://www.skysports.com/football/news/11661/13458757/arsenals-set-piece-precision-shows-value-of-dead-ball-situations-in-modern-era-as-man-city-struggle-to-adapt)
- [TheCable: Nicolas Jover profile](https://www.thecable.ng/nicolas-jover-the-set-piece-wizard-who-turned-arsenal-into-englands-dead-ball-king/)
- [FIFA Training Centre: Targeting the front post](https://www.fifatrainingcentre.com/en/game/game-analysis/set-plays/corners/targeting-the-front-post.php)
- [FIFA Training Centre: Defending corners zonal/man](https://www.fifatrainingcentre.com/en/game/game-analysis/set-plays/corners/defending-corners-zonal-or-player-to-player.php)
- [Modern Soccer Coach: Five favorite short corners](https://www.modernsoccercoach.com/post/msc-five-favorite-short-corner-kick-routines)
- [TNT Sports: Long-throw boom stats](https://www.tntsports.co.uk/football/premier-league/2025-2026/stats-long-throw-increase-set-piece-brentford-crystal-palace_sto23239835/story.shtml)
- [Bet365 News: Premier League set-piece trend](https://news.bet365.com/en-gb/article/premier-league-set-piece-trend/2025102816520284583)
- [Daily Maverick: Long throw resurgence and Rory Delap legacy](https://www.dailymaverick.co.za/article/2025-11-14-long-throw-in-sees-a-resurgence-as-rory-delaps-legacy-reshapes-premier-league-tactics/)

Scanning research:
- [Sky Sports: Geir Jordet on scanning](https://www.skysports.com/football/news/11096/12341305/kevin-de-bruyne-is-a-master-at-scanning-geir-jordet-on-the-science-behind-the-importance-of-vision-and-perception-in-football)
- [Frontiers in Psychology: Scanning in EPL footballers](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2020.553813/full)
- [NCBI: Visual exploration frequency and passing](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6628054/)
- [Training Ground Guru: Jordet on scanning quality](http://archive.trainingground.guru/articles/geir-jordet-why-scanning-is-about-more-than-just-frequency)
