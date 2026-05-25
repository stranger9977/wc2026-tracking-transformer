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
const focusToggle = document.getElementById("focus-toggle");
const linkedToggle = document.getElementById("linked-toggle");
const focusBand = document.getElementById("focus-band");
const scrubOverlay = document.getElementById("scrub-overlay");
const scrubWrap = scrubOverlay ? scrubOverlay.parentElement : null;
const keyDecisionMarker = document.getElementById("key-decision-marker");

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
  // map: player_id -> {dx, dy} (user-dragged primary players)
  liveShifts: new Map(),
  // Derived ripple shifts (teammates pulled along by linked movement). Same
  // shape as liveShifts, recomputed from liveShifts every drag move.
  rippleShifts: new Map(),
  cf: null,            // last live cf result {p_score, p_concede}
  // Per-frame counterfactual trajectories from the live drag, length = focus window.
  // {startFrame, p_score: number[], p_concede: number[]}
  liveTrajectory: null,
};

// Focus mode (10s leadup to goal). Stored per-play to avoid recompute.
// {goalFrame, focusStart, focusEnd, keyDecisionFrame} in absolute frame indices.
let focus = {
  enabled: true,
  linked: true,
  byPlay: new Map(),
};
const FOCUS_WINDOW_FRAMES = 50;   // 10 s at 5 Hz
const FOCUS_GOAL_THRESHOLD = 0.5; // last frame with p_score above this = goal

// Linked-movement parameters. Inverse-distance falloff, capped at α_max with a
// hard cutoff at LINKED_MAX_DIST so faraway teammates don't even twitch.
const LINKED_ALPHA_MAX = 0.4;
const LINKED_FALLOFF_M = 8.0;   // characteristic length scale (m)
const LINKED_MAX_DIST_M = 25.0; // beyond this, no ripple
const LINKED_THRESHOLD_M = 0.5; // ignore drags smaller than this
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
// Focus window — detect the goal frame and the 10 s leadup
// ------------------------------------------------------------
function computeFocusWindow(play) {
  // Goal-frame heuristic: the baseline P(score) curve hits >FOCUS_GOAL_THRESHOLD
  // right before the goal, then collapses to near-zero in the very next frame
  // (post-shot context). The last frame above the threshold is therefore an
  // excellent proxy for "moment the ball crossed the line".
  // Plays don't carry an explicit `events` array yet — when one is added,
  // we'll prefer events[].frame here over the heuristic.
  let goalFrame = play.frames.length - 1;
  for (let i = play.frames.length - 1; i >= 1; i--) {
    if (play.frames[i].p_score > FOCUS_GOAL_THRESHOLD) {
      goalFrame = i;
      break;
    }
  }
  const focusStart = Math.max(0, goalFrame - FOCUS_WINDOW_FRAMES);
  const focusEnd = goalFrame;

  // Key decision frame: steepest positive rise in P(score) over a 3-frame
  // window (smooths out noise) inside the focus window. This is the moment a
  // different choice would have mattered most.
  let bestSlope = -Infinity;
  let keyFrame = focusStart;
  for (let i = focusStart; i <= focusEnd; i++) {
    const lo = Math.max(focusStart, i - 1);
    const hi = Math.min(focusEnd, i + 1);
    if (hi <= lo) continue;
    const slope = (play.frames[hi].p_score - play.frames[lo].p_score) / (hi - lo);
    if (slope > bestSlope) {
      bestSlope = slope;
      keyFrame = i;
    }
  }
  return { goalFrame, focusStart, focusEnd, keyDecisionFrame: keyFrame };
}

function getFocus(play) {
  if (!focus.byPlay.has(play.label)) {
    focus.byPlay.set(play.label, computeFocusWindow(play));
  }
  return focus.byPlay.get(play.label);
}

function focusBounds(play) {
  // Returns {min, max} for the scrubber — full range unless focus mode on.
  const f = getFocus(play);
  if (focus.enabled) return { min: f.focusStart, max: f.focusEnd };
  return { min: 0, max: play.frames.length - 1 };
}

function clampToFocus(idx, play) {
  const { min, max } = focusBounds(play);
  return Math.min(max, Math.max(min, idx));
}

function updateFocusUI() {
  if (!currentPlay || !scrubWrap) return;
  const f = getFocus(currentPlay);
  const n = currentPlay.frames.length;
  if (n < 2) return;
  // Position focus band + key-decision marker as % across the FULL slider range
  // (scrubber still has full domain; we just paint a band and clamp).
  const startPct = (f.focusStart / (n - 1)) * 100;
  const endPct = (f.focusEnd / (n - 1)) * 100;
  const keyPct = (f.keyDecisionFrame / (n - 1)) * 100;
  if (focusBand) {
    focusBand.style.left = startPct + "%";
    focusBand.style.width = Math.max(0, endPct - startPct) + "%";
  }
  if (keyDecisionMarker) {
    keyDecisionMarker.hidden = false;
    keyDecisionMarker.style.left = keyPct + "%";
  }
  scrubWrap.classList.toggle("focus-active", focus.enabled);
}

// ------------------------------------------------------------
// Linked-movement ripple — when a player is dragged, nearby teammates
// shift slightly to maintain compactness. Same team only.
// ------------------------------------------------------------
function computeRippleShifts(play, frame) {
  // For each user-dragged player d, walk every teammate t (not GK, not also
  // being dragged by the user) and apply α(d) · (d.shift) decayed by distance.
  // Multiple simultaneous drags compose additively (rare in practice — the UI
  // is single-pointer — but we handle it for free).
  const out = new Map();
  if (!focus.linked || freestyle.liveShifts.size === 0) return out;
  // Build a player-id → original-position index for fast lookup.
  const byPid = new Map();
  for (const p of frame.players) byPid.set(p.player_id, p);
  for (const [draggedPid, sh] of freestyle.liveShifts.entries()) {
    const d = byPid.get(draggedPid);
    if (!d) continue;
    const mag = Math.hypot(sh.dx, sh.dy);
    if (mag < LINKED_THRESHOLD_M) continue;
    for (const t of frame.players) {
      if (t.player_id === draggedPid) continue;
      if (t.team_id !== d.team_id) continue;        // teammates only
      if (freestyle.liveShifts.has(t.player_id)) continue; // user owns this one
      if (t.is_gk) continue;                         // GKs hold position
      const dist = Math.hypot(t.x - d.x, t.y - d.y);
      if (dist > LINKED_MAX_DIST_M) continue;
      const alpha = LINKED_ALPHA_MAX * Math.exp(-dist / LINKED_FALLOFF_M);
      const prev = out.get(t.player_id) || { dx: 0, dy: 0 };
      out.set(t.player_id, {
        dx: prev.dx + alpha * sh.dx,
        dy: prev.dy + alpha * sh.dy,
      });
    }
  }
  return out;
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

  // Freestyle ripple shifts: derived teammates pulled along by the drag.
  // Cheap to recompute once per render; depends on the current frame's
  // teammate positions (which is the same data we render from).
  if (freestyle.enabled) {
    freestyle.rippleShifts = computeRippleShifts(currentPlay, frame);
  } else {
    freestyle.rippleShifts = new Map();
  }

  for (const p of frame.players) {
    // Curated-move shift takes priority; freestyle live-drag overrides if set.
    let shift = shiftLookup ? shiftLookup.get(p.player_id) : null;
    let isRipple = false;
    if (freestyle.enabled && freestyle.liveShifts.has(p.player_id)) {
      shift = freestyle.liveShifts.get(p.player_id);
    } else if (freestyle.enabled && freestyle.rippleShifts.has(p.player_id)) {
      shift = freestyle.rippleShifts.get(p.player_id);
      isRipple = true;
    }

    // Defensive: never let a bad p.x/p.y silently make a dot disappear to (0,0).
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) {
      console.warn("[whiteboard] player has non-finite x/y, skipping", p);
      continue;
    }

    // Original (pre-shift) dot (ghosted) if shifted
    if (shift) {
      const fromDot = document.createElementNS(SVG_NS, "circle");
      fromDot.setAttribute("cx", p.x);
      fromDot.setAttribute("cy", p.y);
      fromDot.setAttribute("r", 1.55);
      fromDot.setAttribute("class", `player-dot ${teamClass(currentPlay, p)} shifted-from`);
      fromDot.style.fill = fillForTeam(currentPlay, p);
      fromDot.style.opacity = "0.35";
      gPlayers.appendChild(fromDot);

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
    if (shift) cls += isRipple ? " ripple-to" : " shifted-to";
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
      // SVG <title> children produce a native hover tooltip in all browsers.
      const tip = document.createElementNS(SVG_NS, "title");
      tip.textContent = focus.linked
        ? `${p.name || "Player"} — drag me; teammates will shift with you.`
        : `${p.name || "Player"} — drag me to test a new position.`;
      dot.appendChild(tip);
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

  // Live freestyle counterfactual at the current frame, when we have one.
  let psFs = null, pcFs = null;
  if (freestyle.liveTrajectory) {
    const i = t - freestyle.liveTrajectory.startFrame;
    if (i >= 0 && i < freestyle.liveTrajectory.p_score.length) {
      psFs = freestyle.liveTrajectory.p_score[i];
      pcFs = freestyle.liveTrajectory.p_concede[i];
    }
  }

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
  if (psFs != null) {
    const dScore = psFs - psBase;
    const dConcede = pcFs - pcBase;
    html += `
      <span><span class="swatch score-cf"></span>freestyle P(score) ${fmtPct(psFs)} <span class="${dScore >= 0 ? "delta-chip pos" : "delta-chip neg"}">${fmtDelta(dScore)}</span></span>
      <span><span class="swatch concede-cf"></span>freestyle P(concede) ${fmtPct(pcFs)} <span class="${dConcede >= 0 ? "delta-chip neg" : "delta-chip pos"}">${fmtDelta(dConcede)}</span></span>
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

  // Focus band overlay on chart (matches the slider focus band visually).
  const fw = getFocus(play);
  if (focus.enabled) {
    const fx1 = padL + (fw.focusStart / (n - 1)) * plotW;
    const fx2 = padL + (fw.focusEnd / (n - 1)) * plotW;
    ctx.fillStyle = "rgba(255, 209, 102, 0.06)";
    ctx.fillRect(fx1, padT, fx2 - fx1, plotH);
    ctx.strokeStyle = "rgba(255, 209, 102, 0.28)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(fx1, padT); ctx.lineTo(fx1, padT + plotH);
    ctx.moveTo(fx2, padT); ctx.lineTo(fx2, padT + plotH);
    ctx.stroke();
  }

  // y-axis range: scale to include all values
  let yMin = 0, yMax = 1;
  const allVals = [];
  for (const f of play.frames) { allVals.push(f.p_score, f.p_concede); }
  if (move) {
    for (const v of move.per_frame.p_score) allVals.push(v);
    for (const v of move.per_frame.p_concede) allVals.push(v);
  }
  if (freestyle.liveTrajectory) {
    for (const v of freestyle.liveTrajectory.p_score) allVals.push(v);
    for (const v of freestyle.liveTrajectory.p_concede) allVals.push(v);
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

  // Draw a series (with optional range — start/end inclusive)
  function drawSeries(values, color, dashed, opts = {}) {
    const start = opts.start ?? 0;
    const end = opts.end ?? (values.length - 1);
    const offset = opts.offset ?? 0;     // index in `values` corresponding to `start`
    const alpha = opts.alpha ?? 1.0;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = color;
    ctx.lineWidth = opts.lineWidth ?? (dashed ? 1.7 : 1.4);
    ctx.setLineDash(dashed ? [4, 3] : []);
    ctx.beginPath();
    let started = false;
    for (let i = start; i <= end; i++) {
      const v = values[i - start + offset];
      if (v == null || !Number.isFinite(v)) continue;
      const x = xToPx(i);
      const y = yToPx(v);
      if (!started) { ctx.moveTo(x, y); started = true; }
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  // Fade baselines when the user is dragging in freestyle mode so the live
  // counterfactual curves are the visual focus.
  const baselineAlpha = freestyle.liveTrajectory ? 0.45 : 1.0;
  const psBase = play.frames.map(f => f.p_score);
  const pcBase = play.frames.map(f => f.p_concede);
  drawSeries(psBase, "#6dd58c", false, { alpha: baselineAlpha });
  drawSeries(pcBase, "#e98074", false, { alpha: baselineAlpha });

  if (move) {
    drawSeries(move.per_frame.p_score, "#ffd166", true);
    drawSeries(move.per_frame.p_concede, "#ff8c5a", true);
  }

  // Live freestyle trajectory: drawn only over the focus window. Same colours
  // as the curated cf curves (ffd166 / ff8c5a) so the visual language is
  // consistent. Bolder line weight to make it pop against the faded baseline.
  if (freestyle.liveTrajectory) {
    const tr = freestyle.liveTrajectory;
    drawSeries(tr.p_score, "#ffd166", true,
               { start: tr.startFrame, end: tr.startFrame + tr.p_score.length - 1,
                 offset: 0, lineWidth: 2.1 });
    drawSeries(tr.p_concede, "#ff8c5a", true,
               { start: tr.startFrame, end: tr.startFrame + tr.p_concede.length - 1,
                 offset: 0, lineWidth: 2.1 });
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
  if (freestyle.liveTrajectory) {
    legendItem("#ffd166", "P(score) freestyle (focus)", true);
    legendItem("#ff8c5a", "P(concede) freestyle (focus)", true);
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
  // Also clear freestyle drag state, ripple shifts, and live trajectory so
  // "reset" really means "go back to the original timeline".
  freestyle.liveShifts.clear();
  freestyle.rippleShifts = new Map();
  freestyle.liveTrajectory = null;
  freestyle.cf = null;
  // Restore default focus + linked toggles to ON (matches HTML defaults).
  focus.enabled = true;
  focus.linked = true;
  if (focusToggle) focusToggle.checked = true;
  if (linkedToggle) linkedToggle.checked = true;
  setFreestyleStatus(freestyle.enabled ? "Freestyle ready — drag any player." : "");
  if (currentPlay) {
    const start = clampToFocus(currentFrame, currentPlay);
    updateFocusUI();
    renderFrame(start);
  }
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

  frameScrub.min = "0";
  frameScrub.max = String(play.frames.length - 1);
  frameScrub.value = "0";

  // Reset per-play freestyle state when switching plays.
  freestyle.liveShifts.clear();
  freestyle.rippleShifts = new Map();
  freestyle.liveTrajectory = null;
  freestyle.cf = null;

  // Compute and display focus window + key decision marker.
  getFocus(play);
  updateFocusUI();

  renderMoves(play);
  // Start at the focus-window start so the first thing the user sees is the
  // beginning of the 10s leadup (rather than 30s of midfield buildup).
  const startFrame = focus.enabled ? focusBounds(play).min : 0;
  renderFrame(startFrame);
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
    let idx = Number(e.target.value);
    if (currentPlay && focus.enabled) {
      const clamped = clampToFocus(idx, currentPlay);
      if (clamped !== idx) {
        idx = clamped;
        frameScrub.value = String(idx);
      }
    }
    renderFrame(idx);
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
      const maxFrame = focus.enabled
        ? focusBounds(currentPlay).max
        : currentPlay.frames.length - 1;
      if (next > maxFrame) {
        clearInterval(playTimer); playTimer = null; playBtn.textContent = "▶ play";
        return;
      }
      renderFrame(next);
    }, 200);  // 5 Hz playback to match the data rate
  });

  if (focusToggle) {
    focusToggle.addEventListener("change", () => {
      focus.enabled = focusToggle.checked;
      if (currentPlay) {
        const next = clampToFocus(currentFrame, currentPlay);
        updateFocusUI();
        renderFrame(next);
      }
    });
  }
  if (linkedToggle) {
    linkedToggle.addEventListener("change", () => {
      focus.linked = linkedToggle.checked;
      // If we're already dragging, recompute the ripple + re-fire inference.
      if (currentPlay) renderFrame(currentFrame);
      if (freestyle.enabled && freestyle.liveShifts.size > 0) {
        runFreestyleTrajectory();
      }
    });
  }
  if (keyDecisionMarker) {
    keyDecisionMarker.addEventListener("click", () => {
      if (!currentPlay) return;
      const f = getFocus(currentPlay);
      renderFrame(f.keyDecisionFrame);
    });
  }

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
      freestyle.rippleShifts = new Map();
      freestyle.liveTrajectory = null;
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
  // Live trajectory: kick off a batched inference over the focus window.
  // The runFreestyleTrajectory function coalesces concurrent calls so this
  // stays responsive even with rapid pointermove events.
  runFreestyleTrajectory();
}

async function onDragEnd(evt) {
  if (!_drag) return;
  window.removeEventListener("pointermove", onDragMove);
  _drag = null;
  // Final inference call to make sure the chart reflects the released position
  // (handles the case where the last pointermove was coalesced).
  await runFreestyleTrajectory();
}

// Build a per-frame input row (length 23*7 = 161 floats) from a play frame
// plus the current liveShifts/rippleShifts. Pulled out so we can call it for
// each frame in the focus window when building the live trajectory batch.
function writeFreestyleFrame(frame, out, offset) {
  for (let s = 0; s < 22; s++) {
    const p = frame.players[s];
    let x_m = p.x; let y_m = p.y;
    if (freestyle.liveShifts.has(p.player_id)) {
      const sh = freestyle.liveShifts.get(p.player_id);
      x_m += sh.dx; y_m += sh.dy;
    } else if (freestyle.rippleShifts.has(p.player_id)) {
      const sh = freestyle.rippleShifts.get(p.player_id);
      x_m += sh.dx; y_m += sh.dy;
    }
    // Normalize to [-1,1] using PITCH_L/2 and PITCH_W/2
    const x_n = x_m / (PITCH_L / 2);
    const y_n = y_m / (PITCH_W / 2);
    // Velocity & flags: per-frame vx/vy weren't exported. Use zeros (the
    // curated counterfactual run did the same — see the original comment).
    const base = offset + s * 7;
    out[base + 0] = x_n;
    out[base + 1] = y_n;
    out[base + 2] = 0; // vx
    out[base + 3] = 0; // vy
    out[base + 4] = p.team_id === currentPlay.home.team_id
                       ? (frame.in_possession_team_id === currentPlay.home.team_id ? 1 : -1)
                       : (frame.in_possession_team_id === currentPlay.home.team_id ? -1 : 1);
    out[base + 5] = p.is_gk ? 1 : 0;
    out[base + 6] = 0; // has_possession heuristic — set below
  }
  // Ball token at slot 22 (after the 22 player tokens)
  const ballBase = offset + 22 * 7;
  out[ballBase + 0] = frame.ball.x / (PITCH_L / 2);
  out[ballBase + 1] = frame.ball.y / (PITCH_W / 2);
  // Ball features 2..6 stay at zero.

  // has_possession: nearest in-possession player to ball
  let bestSlot = -1, bestD = Infinity;
  for (let s = 0; s < 22; s++) {
    const p = frame.players[s];
    if (p.team_id !== frame.in_possession_team_id) continue;
    const base = offset + s * 7;
    const dx = out[base + 0] * (PITCH_L / 2) - frame.ball.x;
    const dy = out[base + 1] * (PITCH_W / 2) - frame.ball.y;
    const d = dx * dx + dy * dy;
    if (d < bestD) { bestD = d; bestSlot = s; }
  }
  if (bestSlot >= 0) out[offset + bestSlot * 7 + 6] = 1;
}

// Build a per-frame ripple map for an arbitrary frame index. The dragged
// player's shift comes from liveShifts (constant across frames — the
// counterfactual is "they hold this offset throughout the leadup"), but the
// teammates' ripple is computed against THAT frame's positions, so the
// teammate that's closest in frame t responds in frame t.
function computeRippleForFrame(play, frame) {
  if (!focus.linked || freestyle.liveShifts.size === 0) return new Map();
  const byPid = new Map();
  for (const p of frame.players) byPid.set(p.player_id, p);
  const out = new Map();
  for (const [draggedPid, sh] of freestyle.liveShifts.entries()) {
    const d = byPid.get(draggedPid);
    if (!d) continue;
    const mag = Math.hypot(sh.dx, sh.dy);
    if (mag < LINKED_THRESHOLD_M) continue;
    for (const t of frame.players) {
      if (t.player_id === draggedPid) continue;
      if (t.team_id !== d.team_id) continue;
      if (freestyle.liveShifts.has(t.player_id)) continue;
      if (t.is_gk) continue;
      const dist = Math.hypot(t.x - d.x, t.y - d.y);
      if (dist > LINKED_MAX_DIST_M) continue;
      const alpha = LINKED_ALPHA_MAX * Math.exp(-dist / LINKED_FALLOFF_M);
      const prev = out.get(t.player_id) || { dx: 0, dy: 0 };
      out.set(t.player_id, {
        dx: prev.dx + alpha * sh.dx,
        dy: prev.dy + alpha * sh.dy,
      });
    }
  }
  return out;
}

// Run model across the full focus window in a single batched call. Used for
// the live overlay chart. Coalesced with requestAnimationFrame so rapid drag
// events don't pile up: only the most-recent state actually runs.
let _trajPending = false;
let _trajInflight = false;
async function runFreestyleTrajectory() {
  if (!freestyle.session || !currentPlay) return;
  if (_trajInflight) { _trajPending = true; return; }
  _trajInflight = true;
  try {
    const { min, max } = focusBounds(currentPlay);
    const n = max - min + 1;
    if (n <= 0) return;
    const data = new Float32Array(n * 23 * 7);
    // Save & restore freestyle.rippleShifts so the per-frame ripple used for
    // inference is computed against that frame's actual positions (not the
    // currently-rendered frame's).
    const savedRipple = freestyle.rippleShifts;
    for (let i = 0; i < n; i++) {
      const f = currentPlay.frames[min + i];
      freestyle.rippleShifts = computeRippleForFrame(currentPlay, f);
      writeFreestyleFrame(f, data, i * 23 * 7);
    }
    freestyle.rippleShifts = savedRipple;
    const tensor = new freestyle.ort.Tensor("float32", data, [n, 23, 7]);
    const t0 = performance.now();
    let out;
    try {
      out = await freestyle.session.run({ x: tensor });
    } catch (err) {
      console.error("ort batched inference failed", err);
      setFreestyleStatus("Inference failed: " + (err.message || err));
      return;
    }
    const dt = performance.now() - t0;
    const ps = Array.from(out.p_score.data);
    const pc = Array.from(out.p_concede.data);
    freestyle.liveTrajectory = { startFrame: min, p_score: ps, p_concede: pc };
    // Single-frame cf for the prob-strip at the current frame.
    const here = currentFrame - min;
    if (here >= 0 && here < n) {
      freestyle.cf = { p_score: ps[here], p_concede: pc[here] };
    }
    const base = currentPlay.frames[currentFrame];
    const dScore = (freestyle.cf?.p_score ?? base.p_score) - base.p_score;
    setFreestyleStatus(
      `cf inference: ${dt.toFixed(0)} ms over ${n} frames — ` +
      `live Δ P(score) at this frame ${dScore >= 0 ? "+" : "−"}${Math.abs(dScore).toFixed(3)}`
    );
    drawDeltaChart(currentPlay, currentMove, currentFrame);
    updateProbStrip(currentPlay.frames[currentFrame]);
  } finally {
    _trajInflight = false;
    if (_trajPending) {
      _trajPending = false;
      // Coalesce: schedule the next run on the animation frame.
      requestAnimationFrame(() => runFreestyleTrajectory());
    }
  }
}

// Back-compat shim: any caller that wants a single-frame run gets the
// trajectory, which is a superset.
async function runFreestyleInference() {
  return runFreestyleTrajectory();
}

init().catch((err) => {
  console.error("whiteboard init failed", err);
  renderEmpty(movesList,
    "Whiteboard failed to load.",
    String(err));
});
