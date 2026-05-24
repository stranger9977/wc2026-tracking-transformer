/* What is Chemistry? — narrative tab.
 *
 * Renders:
 *   - the 12-mechanism grid, with a "Test on the Whiteboard" button per
 *     mechanism that links to whiteboard.html?play=<play_id>&move=<move_id>
 *     where a curated counterfactual exists, or a "Coming soon" placeholder
 *     where it doesn't.
 *   - the open-questions list, transposed from the dossier.
 *
 * Data sources (read-only):
 *   - data/chemistry_concepts.json   the dossier in structured form
 *   - data/whiteboard_moves.json     curated counterfactuals per play, with
 *                                    each move tagged by mechanism_id
 */

import { initNav, loadJSON, escapeHTML, renderEmpty } from "./site.js";

initNav();

const gridEl = document.getElementById("mech-grid");
const openQEl = document.getElementById("open-questions");

// Tactical bucket per mechanism — drives the card colour. Rust = in-possession
// offence, steel blue = out-of-possession defence, violet = cross-team off-ball
// relationships (pinning, decoy: where the attacker's effect lives in an
// opposing defender's behaviour).
const MECH_CATEGORY = {
  third_man_triangle: "offence",
  the_pin: "cross",
  decoy_run: "cross",
  overlap_underlap: "offence",
  press_trap: "offence",
  gegenpress_swarm: "defence",
  positional_rotations: "offence",
  meat_wall: "offence",
  near_post_flick_on: "offence",
  short_corner_overload: "offence",
  blind_pass: "offence",
  rest_defense: "defence",
};

// Famous-example one-liners — pulled from the dossier's "famous_example" field
// and compressed for the card header. Kept as a JS lookup so the JSON file
// (a shared data source) stays untouched.
const SHORT_EXAMPLE = {
  third_man_triangle: "Xavi → Iniesta → Messi · Barcelona 2009–12",
  the_pin: "Saka holds the width · Arsenal under Arteta",
  decoy_run: "Müller's Raumdeuter career · France's near-post decoy on Mbappé crosses",
  overlap_underlap: "Trent + Salah · Liverpool 2018–23 · Ben White + Saka",
  press_trap: "De Zerbi's Brighton · foot-on-the-ball bait",
  gegenpress_swarm: "Klopp's Liverpool · the 5-second rule",
  positional_rotations: "Cancelo / Zinchenko as inverted fullbacks · Pep's five lanes",
  meat_wall: "Arsenal under Jover, 2023–26 · Ben White screens the keeper",
  near_post_flick_on: "South Korea at WC '22 · Crouch/Carroll at England",
  short_corner_overload: "Pep's Manchester City · Spain at Euro 2024",
  blind_pass: "De Bruyne → Haaland · Kroos → Modrić",
  rest_defense: "Pep's City · Rodri + Stones + Dias",
};

// Tag for "does event data see this?" derived from the dossier's off-ball-signal
// + moves-the-ball flags. ✓ = event data sees it (passes/touches), ⚠ = partial
// (event sees the action but misses the off-ball setup), ✗ = invisible.
function eventDataSees(mech) {
  const sig = mech.off_ball_signal;
  if (mech.moves_the_ball === false) return { mark: "✗", label: "no", className: "tag-no" };
  // moves_the_ball === true
  if (sig === "very_high" || sig === "high") return { mark: "⚠", label: "partial", className: "tag-partial" };
  if (sig === "medium") return { mark: "⚠", label: "partial", className: "tag-partial" };
  return { mark: "✓", label: "yes", className: "tag-yes" };
}

// Pick the lowest-rank whiteboard move for each mechanism_id. Returns
// { mechanism_id -> { play_id, move_id, narrative } }.
function buildMechToMove(whiteboardPlays) {
  const out = {};
  if (!Array.isArray(whiteboardPlays)) return out;
  for (const play of whiteboardPlays) {
    const playId = play.label || play.title;
    for (const m of play.moves || []) {
      const mid = m.mechanism_id;
      if (!mid) continue;
      const existing = out[mid];
      if (!existing || (m.rank ?? 99) < (existing.rank ?? 99)) {
        out[mid] = {
          play_id: playId,
          play_title: play.title,
          move_id: m.move_id,
          rank: m.rank,
          narrative: m.narrative,
          mechanism_name: m.mechanism_name,
        };
      }
    }
  }
  return out;
}

function categoryLabel(cat) {
  if (cat === "offence") return "Possession / offence";
  if (cat === "defence") return "Out-of-possession / defence";
  if (cat === "cross") return "Cross-team off-ball";
  return "";
}

function renderMechCard(mech, move) {
  const cat = MECH_CATEGORY[mech.id] || "offence";
  const eventSeen = eventDataSees(mech);
  const exampleLine = SHORT_EXAMPLE[mech.id] || (mech.famous_example || "").split(".")[0];

  // Whiteboard button: real link if a curated move exists for this mechanism,
  // placeholder card if not.
  let actionHTML;
  if (move) {
    const url = `whiteboard.html?play=${encodeURIComponent(move.play_id)}&move=${encodeURIComponent(move.move_id)}`;
    actionHTML = `
      <a class="mech-action" href="${url}">
        Test this on the Whiteboard
        <span class="dim small">&middot; ${escapeHTML(move.play_title || move.play_id)}</span>
      </a>`;
  } else {
    actionHTML = `
      <div class="mech-action mech-action--placeholder" aria-disabled="true">
        Coming soon
        <span class="dim small">&middot; needs a curated set-piece play</span>
      </div>`;
  }

  return `
    <article class="mech-card mech-card--${cat}">
      <header class="mech-card-head">
        <h3 class="mech-name">${escapeHTML(mech.name)}</h3>
        <span class="mech-cat-chip mech-cat-chip--${cat}" title="${escapeHTML(categoryLabel(cat))}">
          ${escapeHTML(categoryLabel(cat))}
        </span>
      </header>
      <p class="mech-what">${escapeHTML(mech.what_it_is)}</p>
      <p class="mech-example"><span class="dim small">Famous example.</span>
        ${escapeHTML(exampleLine)}</p>
      <div class="mech-tags">
        <span class="mech-tag ${eventSeen.className}"
              title="Does event data (passes, shots, tackles) capture this mechanism?">
          Event data: ${eventSeen.mark} ${eventSeen.label}
        </span>
        <span class="mech-tag tag-off-ball"
              title="Strength of the off-ball signal — how much of the mechanism lives in player positions, not ball-touches.">
          Off-ball: ${escapeHTML(String(mech.off_ball_signal || "").replace("_", " "))}
        </span>
      </div>
      ${actionHTML}
    </article>
  `;
}

function renderMechGrid(concepts, mechToMove) {
  if (!concepts || !Array.isArray(concepts.mechanisms)) {
    renderEmpty(gridEl, "Mechanism dossier not found.",
      "Expected data/chemistry_concepts.json.");
    return;
  }
  const cards = concepts.mechanisms.map(m => renderMechCard(m, mechToMove[m.id] || null));
  gridEl.innerHTML = cards.join("");
  gridEl.removeAttribute("aria-busy");
}

function renderOpenQuestions(concepts) {
  if (!concepts || !concepts.model_analysis || !Array.isArray(concepts.model_analysis.open_questions)) {
    openQEl.innerHTML = "";
    return;
  }
  const items = concepts.model_analysis.open_questions.map(q => {
    return `<li class="open-question"><strong>${escapeHTML(prettyQId(q.id))}.</strong>
      ${escapeHTML(q.question)}</li>`;
  });
  openQEl.innerHTML = items.join("");
}

function prettyQId(qid) {
  // attention_joi_gap → "Attention–JOI gap"
  const map = {
    attention_joi_gap: "Attention–JOI gap",
    pinning_detection: "Pinning detection",
    third_man_anticipation: "Third-man anticipation",
    set_piece_attention_shapes: "Set-piece attention shapes",
    club_vs_country_chemistry_transfer: "Club vs country transfer",
  };
  return map[qid] || qid.replaceAll("_", " ");
}

async function init() {
  const [concepts, whiteboardPlays] = await Promise.all([
    loadJSON("data/chemistry_concepts.json"),
    loadJSON("data/whiteboard_moves.json"),
  ]);

  const mechToMove = buildMechToMove(whiteboardPlays);
  renderMechGrid(concepts, mechToMove);
  renderOpenQuestions(concepts);
}

init();
