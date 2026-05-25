/* Digital Whiteboard — counterfactual chemistry on real WC22 plays.
 *
 * Renders a tactical SVG pitch with 22 player dots + ball, a scrubber/play
 * control over the clip's frames, a Δ-curve chart (canvas), and a panel of
 * "chemistry move" cards on the right. Clicking a card animates the player
 * shift on the pitch and overlays the counterfactual probability traces.
 *
 * Data source: `data/whiteboard_moves.json` (per-play frames + pre-computed
 * counterfactual deltas). See research/scripts/compute_whiteboard_counterfactuals.py.
 *
 * Style and colour conventions intentionally mirror interactive-plays so the
 * two tabs read as siblings — but the code is deliberately self-contained
 * (no shared module) to avoid coordination conflicts with the bug-sweep
 * agent working on the Interactive Plays renderer.
 */

import { initNav, loadJSON, escapeHTML, fmtNum, renderEmpty } from "./site.js";

initNav();

// Pitch dims (must match data/schema.py — PFF normalises to 105 x 68 m, but
// the SVG viewBox uses 110 x 72 with a 5-unit margin baked in).
const PITCH_L = 105;
const PITCH_W = 68;

const SVG_NS = "http://www.w3.org/2000/svg";

// ------------------------------------------------------------
// DOM
// ------------------------------------------------------------
const playSelect = document.getElementById("play-select");
const playMeta = document.getElementById("play-meta");
const movesList = document.getElementById("moves-list");
const pitch = document.getElementById("pitch");
const frameScrub = document.getElementById("frame-scrub");
const frameCounter = document.getElementById("frame-counter");
const probStrip = document.getElementById("prob-strip");
const deltaChart = document.getElementById("delta-chart");
const resetBtn = document.getElementById("reset-btn");
const playBtn = document.getElementById("play-btn");

// ------------------------------------------------------------
// State
// ------------------------------------------------------------
let allPlays = [];
let currentPlay = null;
let currentMove = null; // {move} | null when reset
let currentFrame = 0;
let playTimer = null;

// Freestyle mode (stretch): if active, dots become draggable and onnxruntime-web
// reruns the model on the modified frame to produce a one-frame counterfactual.
let freestyle = {
  enabled: false,
  ort: null,           // onnxruntime-web namespace once loaded
  session: null,       // InferenceSession
  loading: false,
  // Per-player metres-delta applied to the *current* frame only (live drag).
  // map: player_id -> {dx, dy}
  liveShifts: new Map(),
  cf: null,            // last live cf result {p_score, p_concede}
};
const FREESTYLE_PITCH_RANGE = { xMin: -PITCH_L / 2 - 2, xMax: PITCH_L / 2 + 2,
                                 yMin: -PITCH_W / 2 - 2, yMax: PITCH_W / 2 + 2 };

// Per-card sticky cache for the per-move "modal slot" of shifted players —
// computed once we know the play, then reused so the animated dot is the
// same one across frames (slot order is otherwise unstable).
let shiftedSlotByMoveAndPid = new Map();

// ------------------------------------------------------------
// Pitch SVG primitives
// ------------------------------------------------------------
function buildPitch() {
  pitch.innerHTML = "";
  // Background rect
  const bg = document.createElementNS(SVG_NS, "rect");
  bg.setAttribute("x", -PITCH_L / 2);
  bg.setAttribute("y", -PITCH_W / 2);
  bg.setAttribute("width", PITCH_L);
  bg.setAttribute("height", PITCH_W);
  bg.setAttribute("class", "pitch-bg");
  pitch.appendChild(bg);

  // Outer rect (lines)
  const outer = document.createElementNS(SVG_NS, "rect");
  outer.setAttribute("x", -PITCH_L / 2);
  outer.setAttribute("y", -PITCH_W / 2);
  outer.setAttribute("width", PITCH_L);
  outer.setAttribute("height", PITCH_W);
  outer.setAttribute("class", "pitch-line");
  pitch.appendChild(outer);

  // Halfway line
  const half = document.createElementNS(SVG_NS, "line");
  half.setAttribute("x1", 0); half.setAttribute("y1", -PITCH_W / 2);
  half.setAttribute("x2", 0); half.setAttribute("y2", PITCH_W / 2);
  half.setAttribute("class", "pitch-line");
  pitch.appendChild(half);

  // Centre circle
  const cc = document.createElementNS(SVG_NS, "circle");
  cc.setAttribute("cx", 0); cc.setAttribute("cy", 0);
  cc.setAttribute("r", 9.15);
  cc.setAttribute("class", "pitch-line");
  pitch.appendChild(cc);

  // Penalty boxes
  const penW = 40.32, penD = 16.5;
  for (const sign of [-1, 1]) {
    const pen = document.createElementNS(SVG_NS, "rect");
    pen.setAttribute("x", sign === -1 ? -PITCH_L / 2 : PITCH_L / 2 - penD);
    pen.setAttribute("y", -penW / 2);
    pen.setAttribute("width", penD);
    pen.setAttribute("height", penW);
    pen.setAttribute("class", "pitch-line");
    pitch.appendChild(pen);
    // 6-yard box
    const sixW = 18.32, sixD = 5.5;
    const six = document.createElementNS(SVG_NS, "rect");
    six.setAttribute("x", sign === -1 ? -PITCH_L / 2 : PITCH_L / 2 - sixD);
    six.setAttribute("y", -sixW / 2);
    six.setAttribute("width", sixD);
    six.setAttribute("height", sixW);
    six.setAttribute("class", "pitch-line");
    pitch.appendChild(six);
    // Penalty spot
    const spot = document.createElementNS(SVG_NS, "circle");
    spot.setAttribute("cx", sign * (PITCH_L / 2 - 11));
    spot.setAttribute("cy", 0); spot.setAttribute("r", 0.25);
    spot.setAttribute("class", "pitch-spot");
    pitch.appendChild(spot);
  }

  // Container groups for arrows, players, ball — layered (arrows below dots)
  const gArrows = document.createElementNS(SVG_NS, "g");
  gArrows.setAttribute("id", "g-arrows");
  pitch.appendChild(gArrows);

  const gPlayers = document.createElementNS(SVG_NS, "g");
  gPlayers.setAttribute("id", "g-players");
  pitch.appendChild(gPlayers);

  const gLabels = document.createElementNS(SVG_NS, "g");
  gLabels.setAttribute("id", "g-labels");
  pitch.appendChild(gLabels);

  const gBall = document.createElementNS(SVG_NS, "g");
  gBall.setAttribute("id", "g-ball");
  pitch.appendChild(gBall);
}

function clearGroup(id) {
  const g = document.getElementById(id);
  if (!g) return;
  while (g.firstChild) g.removeChild(g.firstChild);
}

function shortName(name) {
  if (!name) return "";
  const parts = name.trim().split(/\s+/);
  return parts[parts.length - 1] || name;
}

function teamClass(play, p) {
  if (!p || !p.team_id) return "away";
  return p.team_id === play.home.team_id ? "home" : "away";
}

function fillForTeam(play, p) {
  // Use the explicit home/away colors from the play meta (so Argentina white,
  // France blue, etc., come through accurately).
  const tc = teamClass(play, p);
  return tc === "home" ? play.home.color : play.away.color;
}

// ------------------------------------------------------------
// Render a single frame
// ------------------------------------------------------------
function renderFrame(frameIdx, opts = {}) {
  if (!currentPlay) return;
  currentFrame = frameIdx;
  const frame = currentPlay.frames[frameIdx];
  if (!frame) return;

  // Apply move shifts to player positions for this frame (visual only — the
  // model already ran on the same shift during pre-compute).
  let shiftLookup = null;
  if (currentMove) {
    shiftLookup = new Map();
    for (const s of currentMove.shifts) {
      shiftLookup.set(s.player_id, { dx: s.dx_m, dy: s.dy_m });
    }
  }

  clearGroup("g-players");
  clearGroup("g-labels");
  clearGroup("g-arrows");
  clearGroup("g-ball");

  const gPlayers = document.getElementById("g-players");
  const gLabels = document.getElementById("g-labels");
  const gArrows = document.getElementById("g-arrows");
  const gBall = document.getElementById("g-ball");

  for (const p of frame.players) {
    // Curated-move shift takes priority; freestyle live-drag overrides if set.
    let shift = shiftLookup ? shiftLookup.get(p.player_id) : null;
    if (freestyle.enabled && freestyle.liveShifts.has(p.player_id)) {
      shift = freestyle.liveShifts.get(p.player_id);
    }

    // Original (pre-shift) dot (ghosted) if shifted
    if (shift) {
      const fromDot = document.createElementNS(SVG_NS, "circle");
      fromDot.setAttribute("cx", p.x);
      fromDot.setAttribute("cy", p.y);
      fromDot.setAttribute("r", 1.55);
      fromDot.setAttribute("class", `player-dot ${teamClass(currentPlay, p)} shifted-from`);
      fromDot.setAttribute("fill", fillForTeam(currentPlay, p));
      gPlayers.appendChild(fromDot);

      // Arrow from→to (in pitch metres)
      const arrow = document.createElementNS(SVG_NS, "line");
      arrow.setAttribute("x1", p.x); arrow.setAttribute("y1", p.y);
      arrow.setAttribute("x2", p.x + shift.dx); arrow.setAttribute("y2", p.y + shift.dy);
      arrow.setAttribute("class", "shift-arrow");
      gArrows.appendChild(arrow);
    }

    // Render each player as ONE <g transform="translate(cx, cy)"> containing
    // the dot, an optional GK ring, and the surname label. Bundling them as a
    // single transformed group means the dot and its label can never appear at
    // different positions regardless of any other bug — they share the
    // group's transform.
    const cx = p.x + (shift ? shift.dx : 0);
    const cy = p.y + (shift ? shift.dy : 0);
    const g = document.createElementNS(SVG_NS, "g");
    g.setAttribute("transform", `translate(${cx} ${cy})`);
    g.setAttribute("class", "player-group");

    const dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("cx", 0);
    dot.setAttribute("cy", 0);
    dot.setAttribute("r", 2.2);
    let cls = `player-dot ${teamClass(currentPlay, p)}`;
    if (shift) cls += " shifted-to";
    if (freestyle.enabled) cls += " freestyle-draggable";
    dot.setAttribute("class", cls);
    // style.fill beats the .home/.away CSS rules (which were forcing teal/red
    // regardless of the team's actual color).
    dot.style.fill = fillForTeam(currentPlay, p);
    dot.style.stroke = "#ffffff";
    dot.style.strokeWidth = "0.4";
    if (freestyle.enabled && p.player_id) {
      dot.style.cursor = "grab";
      dot.dataset.playerId = String(p.player_id);
      dot.dataset.originX = String(p.x);
      dot.dataset.originY = String(p.y);
      dot.addEventListener("pointerdown", onDragStart);
    }
    g.appendChild(dot);

    if (p.is_gk) {
      const ring = document.createElementNS(SVG_NS, "circle");
      ring.setAttribute("cx", 0); ring.setAttribute("cy", 0);
      ring.setAttribute("r", 3.1);
      ring.setAttribute("class", "player-dot gk-ring");
      g.appendChild(ring);
    }

    if (p.name) {
      const t = document.createElementNS(SVG_NS, "text");
      t.setAttribute("x", 0);
      t.setAttribute("y", -3.0);
      t.setAttribute("text-anchor", "middle");
      t.setAttribute("class", "player-label");
      t.textContent = shortName(p.name);
      g.appendChild(t);
    }

    gPlayers.appendChild(g);
  }

  // Ball
  const ball = document.createElementNS(SVG_NS, "circle");
  ball.setAttribute("cx", frame.ball.x);
  ball.setAttribute("cy", frame.ball.y);
  ball.setAttribute("r", 0.9);
  ball.setAttribute("class", "ball-dot");
  gBall.appendChild(ball);

  // Update strip + scrub UI
  updateProbStrip(frame);
  frameScrub.value = String(frameIdx);
  frameCounter.textContent = `frame ${frameIdx + 1}/${currentPlay.frames.length}`;

  // Update vertical cursor on chart
  drawDeltaChart(currentPlay, currentMove, frameIdx);
}

// ------------------------------------------------------------
// Prob strip — text-only line showing baseline + (if move active) cf values
// ------------------------------------------------------------
function fmtPct(v) {
  return (v * 100).toFixed(1) + "%";
}
function fmtDelta(v) {
  const sign = v >= 0 ? "+" : "−";
  return sign + Math.abs(v).toFixed(3);
}

function updateProbStrip(frame) {
  const t = currentFrame;
  const psBase = frame.p_score;
  const pcBase = frame.p_concede;
  const cf = currentMove ? currentMove.per_frame : null;
  const psCf = cf ? cf.p_score[t] : null;
  const pcCf = cf ? cf.p_concede[t] : null;

  let html = `
    <span><span class="swatch score"></span><strong>P(score)</strong> ${fmtPct(psBase)}</span>
    <span><span class="swatch concede"></span><strong>P(concede)</strong> ${fmtPct(pcBase)}</span>
  `;
  if (cf) {
    const dScore = psCf - psBase;
    const dConcede = pcCf - pcBase;
    html += `
      <span><span class="swatch score-cf"></span>cf P(score) ${fmtPct(psCf)} <span class="${dScore >= 0 ? "delta-chip pos" : "delta-chip neg"}">${fmtDelta(dScore)}</span></span>
      <span><span class="swatch concede-cf"></span>cf P(concede) ${fmtPct(pcCf)} <span class="${dConcede >= 0 ? "delta-chip neg" : "delta-chip pos"}">${fmtDelta(dConcede)}</span></span>
    `;
  }
  probStrip.innerHTML = html;
}

// ------------------------------------------------------------
// Delta chart (canvas) — baseline + cf P(score) and P(concede) over time
// ------------------------------------------------------------
function drawDeltaChart(play, move, cursorFrame) {
  if (!play) return;
  const ctx = deltaChart.getContext("2d");
  // Hi-DPI scaling
  const dpr = window.devicePixelRatio || 1;
  const cssW = deltaChart.clientWidth || deltaChart.width;
  const cssH = deltaChart.clientHeight || deltaChart.height;
  if (deltaChart.width !== Math.round(cssW * dpr)
      || deltaChart.height !== Math.round(cssH * dpr)) {
    deltaChart.width = Math.round(cssW * dpr);
    deltaChart.height = Math.round(cssH * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const W = cssW;
  const H = cssH;
  const padL = 38, padR = 14, padT = 16, padB = 22;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const n = play.frames.length;
  if (n < 2) return;

  // Background
  ctx.fillStyle = "#1a1f29";
  ctx.fillRect(padL, padT, plotW, plotH);

  // y-axis range: scale to include all values
  let yMin = 0, yMax = 1;
  const allVals = [];
  for (const f of play.frames) { allVals.push(f.p_score, f.p_concede); }
  if (move) {
    for (const v of move.per_frame.p_score) allVals.push(v);
    for (const v of move.per_frame.p_concede) allVals.push(v);
  }
  yMax = Math.min(1.0, Math.max(0.05, Math.max(...allVals) * 1.05));

  const xToPx = (i) => padL + (i / (n - 1)) * plotW;
  const yToPx = (v) => padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  // Grid lines
  ctx.strokeStyle = "#2a313d";
  ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const y = padT + (g / 4) * plotH;
    ctx.beginPath();
    ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y);
    ctx.stroke();
  }
  // y labels
  ctx.fillStyle = "#97a0b0";
  ctx.font = "10px ui-monospace, Menlo, monospace";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let g = 0; g <= 4; g++) {
    const v = yMin + ((4 - g) / 4) * (yMax - yMin);
    ctx.fillText((v * 100).toFixed(0) + "%", padL - 4, padT + (g / 4) * plotH);
  }

  // X label (frame number)
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText("0", padL, padT + plotH + 4);
  ctx.fillText(String(n - 1), padL + plotW, padT + plotH + 4);

  // Draw a series
  function drawSeries(values, color, dashed) {
    ctx.strokeStyle = color;
    ctx.lineWidth = dashed ? 1.7 : 1.4;
    ctx.setLineDash(dashed ? [4, 3] : []);
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const x = xToPx(i);
      const y = yToPx(values[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const psBase = play.frames.map(f => f.p_score);
  const pcBase = play.frames.map(f => f.p_concede);
  drawSeries(psBase, "#6dd58c", false);
  drawSeries(pcBase, "#e98074", false);

  if (move) {
    drawSeries(move.per_frame.p_score, "#ffd166", true);
    drawSeries(move.per_frame.p_concede, "#ff8c5a", true);
  }

  // Cursor (vertical line at the current frame)
  if (typeof cursorFrame === "number") {
    const x = xToPx(cursorFrame);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.35)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH);
    ctx.stroke();
  }

  // Legend in the top-right
  ctx.font = "10px ui-monospace, Menlo, monospace";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  let legY = padT + 2;
  function legendItem(color, label, dashed) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(dashed ? [3, 2] : []);
    ctx.beginPath();
    ctx.moveTo(padL + 6, legY + 5);
    ctx.lineTo(padL + 24, legY + 5);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#c8d0dc";
    ctx.fillText(label, padL + 28, legY);
    legY += 12;
  }
  legendItem("#6dd58c", "P(score) baseline", false);
  legendItem("#e98074", "P(concede) baseline", false);
  if (move) {
    legendItem("#ffd166", "P(score) counterfactual", true);
    legendItem("#ff8c5a", "P(concede) counterfactual", true);
  }
}

// ------------------------------------------------------------
// Move card rendering
// ------------------------------------------------------------
function renderMoves(play) {
  movesList.innerHTML = "";
  if (!play.moves || play.moves.length === 0) {
    movesList.innerHTML = `<div class="dim small">No counterfactual moves computed for this play.</div>`;
    return;
  }
  for (const move of play.moves) {
    const card = document.createElement("div");
    card.className = "move-card";
    card.dataset.moveId = move.move_id;
    const dScore = move.summary.mean_d_score;
    const dConcede = move.summary.mean_d_concede;
    const dNet = move.summary.mean_d_net;
    const mechTag = move.mechanism_id
      ? `<span class="mech-tag">${escapeHTML(move.mechanism_name || move.mechanism_id)}</span>`
      : `<span class="mech-tag no-mech">free-form sweep</span>`;
    const peakStr = move.summary.peak_abs_d_net.toFixed(3);
    card.innerHTML = `
      <div class="mech-row">
        ${mechTag}
        <span class="dim small">peak |Δ net| ${peakStr}</span>
      </div>
      <div class="move-label">${escapeHTML(move.label)}</div>
      <div class="move-narrative">${escapeHTML(move.narrative)}</div>
      <div class="move-deltas">
        <span class="delta-chip ${dScore >= 0 ? "pos" : "neg"}">Δ P(score) ${fmtDelta(dScore)}</span>
        <span class="delta-chip ${dConcede >= 0 ? "neg" : "pos"}">Δ P(concede) ${fmtDelta(dConcede)}</span>
        <span class="delta-chip ${dNet >= 0 ? "pos" : "neg"}">Δ net ${fmtDelta(dNet)}</span>
      </div>
    `;
    card.addEventListener("click", () => applyMove(move));
    movesList.appendChild(card);
  }
}

function applyMove(move) {
  currentMove = move;
  document.querySelectorAll(".move-card").forEach(c => {
    c.classList.toggle("active", c.dataset.moveId === move.move_id);
  });
  // Jump to the peak |Δ net| frame so the user immediately sees the swing
  const jumpFrame = Math.max(0, Math.min(
    currentPlay.frames.length - 1,
    move.summary.peak_d_net_frame ?? Math.floor(currentPlay.frames.length / 2)
  ));
  renderFrame(jumpFrame);
}

function resetMove() {
  currentMove = null;
  document.querySelectorAll(".move-card").forEach(c => c.classList.remove("active"));
  renderFrame(currentFrame);
}

// ------------------------------------------------------------
// Play selection
// ------------------------------------------------------------
function activatePlay(play) {
  currentPlay = play;
  currentMove = null;
  currentFrame = 0;
  if (playTimer) { clearInterval(playTimer); playTimer = null; playBtn.textContent = "▶ play"; }

  // The pre-compute pipeline used unstable per-frame snapshot attribution, so
  // slot→(player_id, name, team_id) can flip mid-play (e.g. slot 0 = Varane in
  // frame 0 but Álvarez in frame 137). Pin the canonical mapping from frame 0
  // and override every later frame so dots, labels and team colours stay
  // consistent for the whole play.
  if (play.frames && play.frames.length) {
    const canonical = new Map();
    for (const p of play.frames[0].players || []) {
      canonical.set(p.slot, {
        player_id: p.player_id,
        name: p.name,
        team_id: p.team_id,
        position: p.position,
        is_gk: p.is_gk,
      });
    }
    for (const f of play.frames) {
      for (const p of f.players || []) {
        const c = canonical.get(p.slot);
        if (c) Object.assign(p, c);
      }
    }
  }

  // Meta line
  const goalFrame = (play.moves || []).length;  // not used directly
  playMeta.innerHTML = `
    <strong>${escapeHTML(play.title || play.label)}</strong>
    <span class="dim"> · ${escapeHTML(play.home.name || play.home.short)} vs
    ${escapeHTML(play.away.name || play.away.short)} · ${play.frames.length} frames @ 5 Hz</span>
    <div class="dim small">${escapeHTML(play.summary || "")}</div>
  `;

  frameScrub.max = String(play.frames.length - 1);
  frameScrub.value = "0";

  renderMoves(play);
  renderFrame(0);
}

// ------------------------------------------------------------
// Init
// ------------------------------------------------------------
async function init() {
  buildPitch();
  const data = await loadJSON("data/whiteboard_moves.json");
  if (!data || !Array.isArray(data) || data.length === 0) {
    renderEmpty(movesList,
      "Counterfactuals not yet computed.",
      "Run scripts/compute_whiteboard_counterfactuals.py.");
    return;
  }
  allPlays = data;

  playSelect.innerHTML = data.map((p, i) =>
    `<option value="${i}">${escapeHTML(p.title || p.label)}</option>`
  ).join("");
  playSelect.addEventListener("change", () => {
    activatePlay(allPlays[Number(playSelect.value)]);
  });

  frameScrub.addEventListener("input", (e) => {
    renderFrame(Number(e.target.value));
  });

  resetBtn.addEventListener("click", resetMove);
  playBtn.addEventListener("click", () => {
    if (playTimer) {
      clearInterval(playTimer); playTimer = null; playBtn.textContent = "▶ play";
      return;
    }
    playBtn.textContent = "⏸ pause";
    playTimer = setInterval(() => {
      if (!currentPlay) return;
      const next = currentFrame + 1;
      if (next >= currentPlay.frames.length) {
        clearInterval(playTimer); playTimer = null; playBtn.textContent = "▶ play";
        return;
      }
      renderFrame(next);
    }, 200);  // 5 Hz playback to match the data rate
  });

  // Redraw chart on resize (canvas needs re-rasterization)
  window.addEventListener("resize", () => {
    if (currentPlay) drawDeltaChart(currentPlay, currentMove, currentFrame);
  });

  // Deep-link via query params: ?play=<label>&move=<move_id>
  // Backward-compatible: falls back to first play if no/invalid params.
  const params = new URLSearchParams(window.location.search);
  const playParam = params.get("play");
  const moveParam = params.get("move");
  let startIdx = 0;
  if (playParam) {
    const found = allPlays.findIndex(
      (p) => p.label === playParam || String(p.title) === playParam,
    );
    if (found >= 0) startIdx = found;
  }
  playSelect.value = String(startIdx);
  activatePlay(allPlays[startIdx]);

  if (moveParam) {
    // activatePlay synchronously renders the move cards, so we can locate
    // and click the matching card right away. scrollIntoView lands the card
    // in the user's viewport when arriving from a deep link.
    const card = document.querySelector(
      `.move-card[data-move-id="${CSS.escape(moveParam)}"]`,
    );
    if (card) {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.click();
    }
  }
}

// ------------------------------------------------------------
// Freestyle mode — drag-anywhere with onnxruntime-web inference
// ------------------------------------------------------------

const freestyleBtn = document.getElementById("freestyle-btn");
const freestyleStatus = document.getElementById("freestyle-status");

function setFreestyleStatus(msg) {
  if (freestyleStatus) freestyleStatus.textContent = msg || "";
}

async function ensureOnnx() {
  if (freestyle.session) return true;
  if (freestyle.loading) return false;
  freestyle.loading = true;
  setFreestyleStatus("Loading ONNX runtime (~5 MB)…");
  try {
    // jsdelivr's ort.min.js is the UMD bundle: a dynamic import() wraps it
    // but `env.wasm` ends up undefined because UMD writes to `window.ort`.
    // Inject as a classic <script> instead and pick up the global namespace,
    // which is the canonical way onnxruntime-web's UMD is meant to be used.
    await new Promise((resolve, reject) => {
      if (window.ort && window.ort.env) return resolve();
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.18.0/dist/ort.min.js";
      s.async = true;
      s.onload = () => resolve();
      s.onerror = (e) => reject(new Error("Could not load onnxruntime-web bundle"));
      document.head.appendChild(s);
    });
    const ns = window.ort;
    if (!ns || !ns.env || !ns.env.wasm) {
      throw new Error("onnxruntime-web global did not expose env.wasm");
    }
    ns.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.18.0/dist/";
    freestyle.ort = ns;
    setFreestyleStatus("Loading frame-VAEP model (525 KiB)…");
    freestyle.session = await ns.InferenceSession.create("assets/models/frame_vaep.onnx", {
      executionProviders: ["wasm"],
    });
    setFreestyleStatus("Freestyle ready — drag any player.");
    return true;
  } catch (err) {
    console.error("onnxruntime-web load failed:", err);
    setFreestyleStatus("Failed to load ONNX runtime: " + (err.message || err));
    return false;
  } finally {
    freestyle.loading = false;
  }
}

if (freestyleBtn) {
  freestyleBtn.addEventListener("click", async () => {
    if (!freestyle.enabled) {
      const ok = await ensureOnnx();
      if (!ok) return;
      freestyle.enabled = true;
      freestyleBtn.textContent = "✋ freestyle: ON";
      freestyleBtn.classList.add("primary");
      // Clear curated move when entering freestyle
      currentMove = null;
      document.querySelectorAll(".move-card").forEach(c => c.classList.remove("active"));
    } else {
      freestyle.enabled = false;
      freestyle.liveShifts.clear();
      freestyle.cf = null;
      freestyleBtn.textContent = "✋ freestyle: drag any player";
      freestyleBtn.classList.remove("primary");
      setFreestyleStatus("");
    }
    if (currentPlay) renderFrame(currentFrame);
  });
}

let _drag = null;  // {pid, startClientX, startClientY, originX, originY}

function _pitchPointFromEvent(evt) {
  const pt = pitch.createSVGPoint();
  pt.x = evt.clientX; pt.y = evt.clientY;
  const ctm = pitch.getScreenCTM();
  if (!ctm) return null;
  const inv = ctm.inverse();
  return pt.matrixTransform(inv);
}

function onDragStart(evt) {
  if (!freestyle.enabled) return;
  evt.preventDefault();
  const pid = Number(evt.currentTarget.dataset.playerId);
  if (!pid) return;
  const originX = Number(evt.currentTarget.dataset.originX);
  const originY = Number(evt.currentTarget.dataset.originY);
  _drag = { pid, originX, originY };
  evt.currentTarget.setPointerCapture(evt.pointerId);
  evt.currentTarget.style.cursor = "grabbing";
  window.addEventListener("pointermove", onDragMove);
  window.addEventListener("pointerup", onDragEnd, { once: true });
}

function onDragMove(evt) {
  if (!_drag) return;
  const pt = _pitchPointFromEvent(evt);
  if (!pt) return;
  // Clamp to a bit beyond the pitch edges
  const x = Math.min(FREESTYLE_PITCH_RANGE.xMax, Math.max(FREESTYLE_PITCH_RANGE.xMin, pt.x));
  const y = Math.min(FREESTYLE_PITCH_RANGE.yMax, Math.max(FREESTYLE_PITCH_RANGE.yMin, pt.y));
  freestyle.liveShifts.set(_drag.pid, { dx: x - _drag.originX, dy: y - _drag.originY });
  renderFrame(currentFrame);
}

async function onDragEnd(evt) {
  if (!_drag) return;
  window.removeEventListener("pointermove", onDragMove);
  _drag = null;
  await runFreestyleInference();
}

// Build a single-frame input tensor (1, 23, 7) from current frame + live shifts.
function buildFreestyleInput() {
  const frame = currentPlay.frames[currentFrame];
  const data = new Float32Array(23 * 7);
  for (let s = 0; s < 22; s++) {
    const p = frame.players[s];
    let x_m = p.x; let y_m = p.y;
    if (freestyle.liveShifts.has(p.player_id)) {
      const sh = freestyle.liveShifts.get(p.player_id);
      x_m += sh.dx; y_m += sh.dy;
    }
    // Normalize to [-1,1] using PITCH_L/2 and PITCH_W/2
    const x_n = x_m / (PITCH_L / 2);
    const y_n = y_m / (PITCH_W / 2);
    // Velocity & flags: we don't have per-slot vx/vy in the exported per-frame
    // payload (the curated counterfactual run pre-computed without storing
    // those). Use zeros — this approximates a "frozen-time" inference, still
    // sensitive to spatial structure but losing transition info. Acceptable
    // for the drag-and-see freestyle mode.
    const base = s * 7;
    data[base + 0] = x_n;
    data[base + 1] = y_n;
    data[base + 2] = 0; // vx
    data[base + 3] = 0; // vy
    data[base + 4] = p.team_id === currentPlay.home.team_id
                       ? (frame.in_possession_team_id === currentPlay.home.team_id ? 1 : -1)
                       : (frame.in_possession_team_id === currentPlay.home.team_id ? -1 : 1);
    data[base + 5] = p.is_gk ? 1 : 0;
    data[base + 6] = 0; // has_possession heuristic — set later
  }
  // Ball token at slot 22
  const ballBase = 22 * 7;
  data[ballBase + 0] = frame.ball.x / (PITCH_L / 2);
  data[ballBase + 1] = frame.ball.y / (PITCH_W / 2);
  // Ball features 2..6 left at zero (matches the loader convention).

  // has_possession: nearest in-possession player to ball
  let bestSlot = -1, bestD = Infinity;
  for (let s = 0; s < 22; s++) {
    const p = frame.players[s];
    if (p.team_id !== frame.in_possession_team_id) continue;
    const base = s * 7;
    const dx = data[base+0] * (PITCH_L/2) - frame.ball.x;
    const dy = data[base+1] * (PITCH_W/2) - frame.ball.y;
    const d = dx*dx + dy*dy;
    if (d < bestD) { bestD = d; bestSlot = s; }
  }
  if (bestSlot >= 0) data[bestSlot * 7 + 6] = 1;

  return data;
}

async function runFreestyleInference() {
  if (!freestyle.session) return;
  const data = buildFreestyleInput();
  const tensor = new freestyle.ort.Tensor("float32", data, [1, 23, 7]);
  const t0 = performance.now();
  let out;
  try {
    out = await freestyle.session.run({ x: tensor });
  } catch (err) {
    console.error("ort inference failed", err);
    setFreestyleStatus("Inference failed: " + (err.message || err));
    return;
  }
  const dt = performance.now() - t0;
  const ps = out.p_score.data[0];
  const pc = out.p_concede.data[0];
  freestyle.cf = { p_score: ps, p_concede: pc };
  setFreestyleStatus(
    `cf inference: ${dt.toFixed(1)} ms — cf P(score) ${(ps*100).toFixed(1)}% ` +
    `(Δ ${(((ps - currentPlay.frames[currentFrame].p_score) >= 0 ? "+" : "−"))}${Math.abs(ps - currentPlay.frames[currentFrame].p_score).toFixed(3)}), ` +
    `cf P(concede) ${(pc*100).toFixed(1)}% ` +
    `(Δ ${(((pc - currentPlay.frames[currentFrame].p_concede) >= 0 ? "+" : "−"))}${Math.abs(pc - currentPlay.frames[currentFrame].p_concede).toFixed(3)})`
  );
}

init().catch((err) => {
  console.error("whiteboard init failed", err);
  renderEmpty(movesList,
    "Whiteboard failed to load.",
    String(err));
});
