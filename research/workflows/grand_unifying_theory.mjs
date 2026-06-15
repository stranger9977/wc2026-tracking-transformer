export const meta = {
  name: 'grand-unifying-theory-of-space',
  description: 'Fan out across every space metric (assumptions plus limitations plus cross-fixes), forge novel composites, adversarially verify, synthesize a unifying theory plus YouTube narrative.',
  phases: [
    { title: 'Map nodes', detail: 'one agent per method or asset: assumption, limitation, repair-edges' },
    { title: 'Forge', detail: 'combination generators: novel composite space metrics' },
    { title: 'Verify', detail: 'two adversarial skeptics per composite (novelty and feasibility)' },
    { title: 'Synthesize', detail: 'unify into the framework plus headline metric plus YouTube segments' },
  ],
}

const CONTEXT = [
  'PROJECT: an analytically-driven "Space"/off-ball-movement narrative for a YouTube video teeing up the 2026 World Cup. Built on PFF FC World Cup 2022 data (30Hz broadcast tracking plus HUMAN-GRADED events, all 64 matches) plus StatsBomb open-data (real xG) plus a trained tracking transformer. Core premise: the field has NO ground truth for "space" (Fernandez and Bornn validated by two analysts watching video), and PFF human labels are the unique asset that can validate space metrics.',
  '',
  'VERIFIED LITERATURE (ground truth, do not contradict):',
  '- xT (Singh 2019): event-only; values successful on-ball moves via a Markov chain on a 12x8 grid. Limitation: ignores off-ball effects entirely; only successful moves.',
  '- Pitch control plus OBSO (Spearman 2017/18): events plus one tracking snapshot per on-ball event. OBSO = sum over the pitch of Transition x Control(PPCF) x Score. Author-named limitations: distance-only score model with a fudge factor; transition has no toward-goal preference; IGNORES defensive pressure and carrier speed.',
  '- Pitch control plus SOG/SGG (Fernandez and Bornn 2018): continuous control surface (bivariate-normal player influence); Space Occupation/Generation Gain. Parametric component runs on a single frame, no training. Limitation: no ground truth, validated only by expert video review. Quantified Messi walking: 66.7% of his space gain passive.',
  '- EPV (Fernandez/Bornn/Cervone 2019/21): full tracking; off-ball value surfaces for all 10 teammates. Author-named limitations: NO body orientation; AVERAGE-player model (the Messi-effect gap).',
  '- Space Generation / individualized movement (Martens/Dick/Brefeld 2021): rebuilds pitch control with per-player learned movement models; SG_rec (space for self) vs SG_pas (space for teammates); SG_rec correlates with xG at r=0.66. Limitation: 54 Bundesliga matches, one club season, never tournament-scale.',
  '- C-OBSO (Teranishi et al. 2022): an off-ball player actual OBSO minus the OBSO of a GVRNN-predicted REFERENCE trajectory (ghosting). Adds goal-angle plus multi-defender score model. C-OBSO correlates with salary rho=0.45 where OBSO and goals do not. Limitation: no ground truth; one club season; only 3 players predicted.',
  '- CHASE / gravity (Lauer et al. 2025, NFL): a receiver impact on DEFENSIVE spacing via the defenders convex hull, inspired by basketball gravity. Measures the defense geometric REACTION, a complementary axis to attacker-side value.',
  '- Broadcast tracking (Penn et al. 2025): continuous tracking reconstructable from broadcast at about event-data cost, BUT off-camera positions imputed (about 7m error); unsuitable for fine-grained off-camera run detection.',
  '',
  'OUR UNIQUE ASSETS (the substrate):',
  '- PFF HUMAN LABELS (all 64 matches): createsSpace (1,422 expert-tagged space-creation moments), betterOptionPlayerId (518 open-man-ignored tags), movementGrade (368, mostly negative deductions) plus positionGrade (1,300, about 99% negative deductions), pressureType N/P/A/L (about 62% of events), bodyMovementType (toward-goal/away/lateral/stationary). GROUND TRUTH for space, nobody else pairs them with tracking.',
  '- TRACKING TRANSFORMER heads: calibrated P(score)/P(concede); xT-regression (off-ball xT LIFT over the static lookup); next-receiver (who gets open, P(receive) per teammate); motion-forecast (2s displacement, a built-in average-player ghost); counterfactual whiteboard (move a player, recompute delta P(score)); attention chemistry (ball-independent player-pair attention).',
  '- StatsBomb REAL xG (all 64 matches). Caveat everywhere: broadcast tracking about 46% off-camera positions imputed.',
  '',
  'EMPIRICAL FINDINGS (already computed, use as concrete examples):',
  '- Messi: number 1 space creator (25; 23 under pressure), number 1 actions under pressure (472), tournament-leading 6.03 xG, 33 line breaks (only forward in the LB top 7).',
  '- Line breaks (3-plus opponents bypassed) led by ball-playing CBs and number 6s: Stones 37, Modric 36, Rodri 35, Gvardiol 35, Brozovic 34, Maguire 33.',
  '- Teams: Croatia and Argentina led BOTH space-creation and line breaks; Argentina led actions-under-pressure.',
  '- Per-match outliers: Lozano 5.7 space-creations/match; Pedri 69.5 pressured-actions/match.',
  '- The 2022 final (ARG 3-3 FRA, ARG won on pens): xG 2.76-2.27, line breaks 46-16 ARG.',
].join('\n')

const NODE_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['id', 'name', 'family', 'measures', 'assumption', 'limitation', 'data_required', 'edges', 'validated_by'],
  properties: {
    id: { type: 'string' }, name: { type: 'string' }, family: { type: 'string' },
    measures: { type: 'string' }, assumption: { type: 'string' }, limitation: { type: 'string' },
    data_required: { type: 'string' },
    edges: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['fixes', 'how'], properties: { fixes: { type: 'string' }, how: { type: 'string' } } } },
    validated_by: { type: 'string' },
  },
}
const COMBO_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['name', 'components', 'measures', 'novelty', 'feasible', 'feasibility_note', 'visual_type', 'youtube_segment'],
  properties: {
    name: { type: 'string' }, components: { type: 'array', items: { type: 'string' } },
    measures: { type: 'string' }, novelty: { type: 'string' },
    feasible: { type: 'boolean' }, feasibility_note: { type: 'string' },
    visual_type: { type: 'string' }, youtube_segment: { type: 'string' },
  },
}
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['novel', 'feasible', 'survives', 'reason'],
  properties: { novel: { type: 'boolean' }, feasible: { type: 'boolean' }, survives: { type: 'boolean' }, reason: { type: 'string' } },
}
const SYNTH_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['thesis', 'shared_blind_spot', 'pff_substrate', 'families', 'headline_metric', 'youtube_segments', 'open_risks'],
  properties: {
    thesis: { type: 'string' },
    shared_blind_spot: { type: 'string' },
    pff_substrate: { type: 'string' },
    families: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['family', 'nodes', 'key_edges'], properties: {
      family: { type: 'string' }, nodes: { type: 'array', items: { type: 'string' } },
      key_edges: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['from', 'to', 'fix'], properties: { from: { type: 'string' }, to: { type: 'string' }, fix: { type: 'string' } } } },
    } } },
    headline_metric: { type: 'object', additionalProperties: false, required: ['name', 'recipe', 'why_novel'], properties: { name: { type: 'string' }, recipe: { type: 'string' }, why_novel: { type: 'string' } } },
    youtube_segments: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['title', 'metric', 'visual', 'star_example', 'aha'], properties: { title: { type: 'string' }, metric: { type: 'string' }, visual: { type: 'string' }, star_example: { type: 'string' }, aha: { type: 'string' } } } },
    open_risks: { type: 'array', items: { type: 'string' } },
  },
}

const SEEDS = [
  { id: 'xt', name: 'Expected Threat (xT)', family: 'Event-only value' },
  { id: 'obso', name: 'Pitch Control plus OBSO (Spearman)', family: 'Pitch control / space' },
  { id: 'fb', name: 'Pitch Control plus SOG/SGG (Fernandez and Bornn)', family: 'Pitch control / space' },
  { id: 'epv', name: 'EPV (Fernandez/Bornn/Cervone)', family: 'Possession value' },
  { id: 'martens', name: 'Space Generation / individualized movement (Martens)', family: 'Pitch control / space' },
  { id: 'cobso', name: 'C-OBSO ghosting (Teranishi)', family: 'Possession value' },
  { id: 'chase', name: 'CHASE / gravity (convex-hull defensive deformation)', family: 'Defensive geometry' },
  { id: 'linebreaks', name: 'Line breaks (3-plus opponents bypassed)', family: 'Defensive geometry' },
  { id: 'pfflabels', name: 'PFF human labels (createsSpace / betterOption / grades / pressure / orientation)', family: 'Data substrate' },
  { id: 'transformer', name: 'Our tracking transformer heads (ghosting forecast, next-receiver, P(score), xT-lift, counterfactual, attention)', family: 'Our models' },
  { id: 'sbxg', name: 'StatsBomb real xG', family: 'Data substrate' },
]

const COMBO_THEMES = [
  { id: 'ghost-pc', desc: 'Ghosting (our motion-forecast average player) times pitch control / space gain, VALIDATED against the createsSpace human label: movement skill above expectation, grounded.' },
  { id: 'gravity-lanes', desc: 'CHASE/gravity (defensive deformation) times line breaks: quantify how an off-ball run bends the block and OPENS the lane the line-breaking pass then exploits.' },
  { id: 'xtlift-grade', desc: 'Off-ball xT-lift (transformer over the static lookup) times movementGrade/positionGrade: continuous off-ball value calibrated to PFF human movement grades.' },
  { id: 'pressure-obso', desc: 'OBSO/C-OBSO times pressureType: the pressure-aware off-ball scoring opportunity Spearman said was missing.' },
  { id: 'ignored-epv', desc: 'EPV off-ball value surfaces times betterOptionPlayerId: value the open man who was ignored, the cost of NOT finding created space.' },
  { id: 'space-to-shot', desc: 'Pitch control / space occupation times StatsBomb real xG: bridge space owned to shot quality created, closing the no-ground-truth gap with real outcomes.' },
  { id: 'getopen-occupation', desc: 'Next-receiver head (who gets open) times Fernandez-Bornn space occupation: who manufactures their own receiving space, validated by createsSpace.' },
  { id: 'orientation-receptions', desc: 'bodyMovementType (orientation) times receptions-behind-lines: receiving on the half-turn to play forward; closes the EPV no-orientation gap.' },
  { id: 'attention-spacegen', desc: 'Attention chemistry (ball-independent player-pair attention) times Space Generation (SG_pas, space for teammates): who unlocks whom off the ball.' },
]

// ---- Phase 1: map nodes ----
phase('Map nodes')
const nodeResults = await parallel(SEEDS.map(s => () => agent(
  CONTEXT + '\n\nYou are mapping ONE node of a Grand Unifying Theory of Space. NODE: ' + s.name + ' (family: ' + s.family + ').\n' +
  'Using the verified context as ground truth, return the structured node. For EDGES: name 1-3 OTHER methods or PFF human-labels that most directly REPAIR this node key limitation, each with a one-sentence HOW. For validated_by: which PFF human label or empirical finding could validate/ground this node. Be specific and non-generic; this feeds a connected map of how the methods fix each other.',
  { label: 'node:' + s.id, phase: 'Map nodes', schema: NODE_SCHEMA }
)))
const nodes = nodeResults.filter(Boolean)
log('Mapped ' + nodes.length + '/' + SEEDS.length + ' nodes')

// ---- Phase 2 + 3: forge composites, adversarially verify (pipeline, no barrier) ----
const judged = await pipeline(
  COMBO_THEMES,
  t => agent(
    CONTEXT + '\n\nForge ONE NOVEL composite space metric or video segment by fusing methods per this THEME:\n' + t.desc + '\n' +
    'Return: name; components (which methods/labels/heads it fuses); what it measures; why it is NOVEL vs the verified literature; whether it is FEASIBLE with our data (PFF broadcast tracking about 46% off-camera imputed, PFF human labels, StatsBomb xG, the transformer heads) plus a one-sentence note; the single best VISUAL (heatmap / interactive play scrubber / leaderboard / shot map / pass network / ghosting animation / pitch-control surface); and a one-line YOUTUBE SEGMENT pitch naming a concrete STAR EXAMPLE from the empirical findings (Messi, Pedri, Lozano, Stones/Modric, Croatia/Morocco, the 2022 final).',
    { label: 'combo:' + t.id, phase: 'Forge', schema: COMBO_SCHEMA }
  ),
  (combo, t) => {
    if (!combo) return null
    const lenses = [
      { k: 0, lens: 'NOVELTY: has the verified literature (xT/OBSO/pitch control/EPV/Martens/C-OBSO/CHASE) already effectively done this? Default to not-novel unless the PFF human-label validation or the specific fusion is genuinely new.' },
      { k: 1, lens: 'FEASIBILITY: can this actually be computed and shown given PFF broadcast tracking (about 46% off-camera imputed), the human-label sample sizes (createsSpace 1422, betterOption 518, grades sparse), StatsBomb xG, and our transformer heads? Default to skeptical about off-camera/sparse-label claims.' },
    ]
    return parallel(lenses.map(v => () => agent(
      CONTEXT + '\n\nAdversarially evaluate this proposed composite. TRY TO REFUTE IT through this lens:\n' + v.lens + '\n\nComposite:\n' + JSON.stringify(combo) + '\n\nReturn novel/feasible booleans, an overall survives call, and a one-sentence reason. Be a strict skeptic.',
      { label: 'verify:' + t.id + ':' + v.k, phase: 'Verify', schema: VERDICT_SCHEMA }
    ))).then(vs => ({ combo: combo, verdicts: vs.filter(Boolean) }))
  }
)

const all = judged.filter(Boolean)
const survivors = all.filter(c => {
  const v = c.verdicts || []
  const notFeasible = v.filter(x => !x.feasible).length
  const notNovel = v.filter(x => !x.novel).length
  return v.length > 0 && notFeasible < v.length && notNovel < v.length
})
log('Composites: ' + all.length + ' forged, ' + survivors.length + ' survived adversarial verification')

// ---- Phase 4: synthesize ----
phase('Synthesize')
const theory = await agent(
  CONTEXT + '\n\nYou are the SYNTHESIS step of The Grand Unifying Theory of Space.\n\n' +
  'MAPPED NODES (each method assumption, limitation, and the edges showing what repairs it):\n' + JSON.stringify(nodes) + '\n\n' +
  'SURVIVING NOVEL COMPOSITES (passed adversarial verification):\n' + JSON.stringify(survivors.map(c => c.combo)) + '\n\n' +
  'Synthesize the unifying framework:\n' +
  '(1) thesis: one tight paragraph unifying ALL of these into a single coherent theory of space;\n' +
  '(2) shared_blind_spot: the ONE blind spot every prior method shares that our PFF labels/tracking close;\n' +
  '(3) pff_substrate: how the human labels (createsSpace/betterOption/grades/pressure/orientation) act as the validation ground truth binding the framework;\n' +
  '(4) families: group the nodes into 4-6 families; for each give its node names and key_edges (from to, plus the one-line fix);\n' +
  '(5) headline_metric: the SINGLE novel metric to anchor the video (name, a concrete recipe naming specific components, why_novel);\n' +
  '(6) youtube_segments: an ordered 6-8 segment narrative; each with title, metric, visual, star_example from our real findings, and aha;\n' +
  '(7) open_risks: honest limitations.\n' +
  'Be concrete, use our real player/team findings, and make it genuinely novel and defensible. This becomes a published graphic plus plan.',
  { label: 'synthesize', phase: 'Synthesize', schema: SYNTH_SCHEMA }
)

return {
  nodes: nodes,
  composites: all.map(c => ({ combo: c.combo, verdicts: c.verdicts })),
  survivors: survivors.map(c => c.combo.name),
  theory: theory,
}
