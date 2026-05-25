/* ============================================================
   Interactive Plays — vanilla-JS SVG renderer.

   Bugs fixed (from per-frame PNG renderer → live SVG):
     • Stable slot↔player mapping (slots now come from kloppy in
       the data file, not nearest-neighbor on event snapshots).
     • Team colours pinned at clip-load time (no per-frame flicker).
     • Label collision avoidance — labels offset perpendicular to
       velocity, deterministic per frame.
     • Goal mouth highlighted on the scoring team's attacking end
       when an event_in_frame is a goal.

   Enhancements added:
     • Auto-pause for ~1.0s when an event lands during play mode.
     • Attention edges + halos smoothly interpolated across frames.
     • Pulsing halo on the top-attended player(s).
     • P(score)/P(concede) line chart under the slider with a
       cursor following the scrub position.
   ============================================================ */

import { loadJSON, escapeHTML, fmtNum, renderEmpty } from "./site.js";

const listEl = document.getElementById("play-list");

// Tunables (kept here so they're easy to find).
const TICK_MS = 200;            // frame step at 5 Hz playback
const EVENT_PAUSE_MS = 1000;    // auto-pause on event-in-frame
const SMOOTH_TAU_MS = 150;      // ease for edge widths / halo radii
const PULSE_PERIOD_MS = 600;    // halo pulse cycle
const PITCH_LENGTH_M = 105;
const PITCH_WIDTH_M = 68;
const SVG_W = 900;              // pitch SVG viewport (logical units)
const SVG_H = 600;
const PITCH_PAD = 14;           // margin inside the SVG for labels
const CHART_H = 110;

// Global state for page-level controls. Each clip registers callbacks so
// changing a single dropdown refreshes every chart / pitch on the page.
const chartRedraws = [];
const frameRedraws = [];   // re-renders the pitch overlay (attention edges, halos, etc.)
const focusUpdates = [];   // updates focus-mode min/max on each clip's scrubber

function currentPerspective() {
  const el = document.getElementById("iplay-perspective");
  return el ? el.value : "raw";
}
function focusEnabled() {
  const el = document.getElementById("iplay-focus-toggle");
  return !!(el && el.checked);
}
function currentTopN() {
  const el = document.getElementById("iplay-top-n");
  const v = el ? el.value : "3";
  return v === "all" ? 22 : parseInt(v, 10) || 3;
}
function currentIncludeGk() {
  const el = document.getElementById("iplay-include-gk");
  return !!(el && el.checked);
}
function currentEdgeFilter() {
  const el = document.getElementById("iplay-edge-filter");
  return el ? el.value : "all";
}

function registerChartRedraw(fn) { chartRedraws.push(fn); }
function registerFrameRedraw(fn) { frameRedraws.push(fn); }
function registerFocusUpdate(fn) { focusUpdates.push(fn); }

document.getElementById("iplay-perspective")?.addEventListener("change", () => {
  for (const fn of chartRedraws) { try { fn(); } catch (e) { console.warn(e); } }
});
function refreshAllFrames() {
  for (const fn of frameRedraws) { try { fn(); } catch (e) { console.warn(e); } }
}
function refreshAllFocus() {
  for (const fn of focusUpdates) { try { fn(); } catch (e) { console.warn(e); } }
}
document.getElementById("iplay-focus-toggle")?.addEventListener("change", refreshAllFocus);
document.getElementById("iplay-top-n")?.addEventListener("change", refreshAllFrames);
document.getElementById("iplay-include-gk")?.addEventListener("change", refreshAllFrames);
document.getElementById("iplay-edge-filter")?.addEventListener("change", refreshAllFrames);

// Suppress junk event labels — raw PFF event codes the renderer couldn't
// resolve to a human label. "None" comes from f"{None}" stringification;
// "IT" is a PFF event-type code (likely "indirect touch") not handled
// upstream. Treat both as missing.
function cleanEventLabel(s) {
  if (!s) return "";
  const t = String(s).trim();
  if (!t || t === "None" || t === "IT" || t.endsWith(" — None") || t.endsWith(" — ")) return "";
  return t;
}

const idx = await loadJSON("data/clips/index.json").catch(() => null);

if (!idx || !Array.isArray(idx) || idx.length === 0) {
  renderEmpty(listEl,
    "Clips not yet rendered.",
    "Run scripts/render_interactive_clip.py for each play you want to publish.");
} else {
  listEl.innerHTML = idx.map((c) => `
    <section class="card iplay" id="clip-${escapeHTML(c.label)}">
      <h2 class="mt-0">${escapeHTML(c.title)}</h2>
      <p class="dim small">${escapeHTML(c.summary || "")}</p>
      <div class="clip-viewer" data-clip="${escapeHTML(c.label)}">
        <div class="iplay-stage" id="stage-${escapeHTML(c.label)}"></div>
        <div class="clip-controls">
          <button class="btn small" data-clip="${escapeHTML(c.label)}" data-action="prev">◀ prev</button>
          <button class="btn small" data-clip="${escapeHTML(c.label)}" data-action="play">▶ play</button>
          <button class="btn small" data-clip="${escapeHTML(c.label)}" data-action="next">next ▶</button>
          <button class="btn small" data-clip="${escapeHTML(c.label)}" data-action="goal" title="Jump to the goal frame">⚽ goal</button>
          <div class="scrub-wrap" style="flex:1; position:relative;">
            <input type="range" id="scrub-${escapeHTML(c.label)}" min="0" max="0" value="0" style="width:100%;">
            <div class="scrub-markers" id="markers-${escapeHTML(c.label)}"></div>
          </div>
        </div>
        <div class="iplay-chart" id="chart-${escapeHTML(c.label)}"></div>
        <div id="event-${escapeHTML(c.label)}" class="event-strip"></div>
        <div id="meta-${escapeHTML(c.label)}" class="clip-meta small dim"></div>
      </div>
    </section>`).join("");

  for (const c of idx) {
    const detail = await loadJSON(`data/clips/${c.label}.json`).catch(() => null);
    if (!detail) continue;
    initClip(c, detail);
  }
}

/* ============================================================
   Per-clip controller.
   ============================================================ */

function initClip(c, detail) {
  const stage   = document.getElementById(`stage-${c.label}`);
  const scrub   = document.getElementById(`scrub-${c.label}`);
  const meta    = document.getElementById(`meta-${c.label}`);
  const evtStrip = document.getElementById(`event-${c.label}`);
  const markersEl = document.getElementById(`markers-${c.label}`);
  const chartEl = document.getElementById(`chart-${c.label}`);
  if (!stage || !scrub) return;

  const frames = detail.frames || [];
  const n = frames.length;
  if (n === 0) return;
  scrub.max = String(n - 1);

  /* ---------- team colour map: pinned once, never per frame ---------- */
  // First-frame lineup is the source of truth. If a single frame later
  // mis-tags a slot's team_id (rare data-side bug), the colour stays
  // anchored to the FIRST team_id that slot was seen with — i.e. a
  // single team_id → colour map persists for the whole clip.
  const teamColors = new Map();
  if (detail.team_colors) {
    for (const [k, v] of Object.entries(detail.team_colors)) teamColors.set(k, v);
  }
  if (detail.home_team?.id) teamColors.set(String(detail.home_team.id), detail.home_team.color || "#5eead4");
  if (detail.away_team?.id) teamColors.set(String(detail.away_team.id), detail.away_team.color || "#f87171");

  // Pin each slot's team to whatever its team_id was on frame 0.
  // This protects against frame-to-frame team_id flips.
  const slotTeam = new Map();
  (frames[0].players || []).forEach((p) => {
    if (p.team_id) slotTeam.set(p.slot, String(p.team_id));
  });
  const teamColorFor = (slot, fallback) => {
    const tid = slotTeam.get(slot);
    if (tid && teamColors.has(tid)) return teamColors.get(tid);
    if (fallback && teamColors.has(String(fallback))) return teamColors.get(String(fallback));
    return "#5eead4";
  };

  /* ---------- build the SVG skeleton once ---------- */
  stage.innerHTML = pitchSvgScaffold(detail);
  const svg = stage.querySelector("svg.iplay-pitch");
  const gPlayers = svg.querySelector("#g-players");
  const gEdges = svg.querySelector("#g-edges");
  const gHalos = svg.querySelector("#g-halos");
  const gBall = svg.querySelector("#g-ball");
  const gLabels = svg.querySelector("#g-labels");
  const gGoalHighlight = svg.querySelector("#g-goal-highlight");

  /* ---------- scrub markers + goal frame ---------- */
  const goalFrame = frames.findIndex((f) => f.is_goal_event);
  if (markersEl) {
    const marks = [];
    frames.forEach((f, i) => {
      const left = (i / Math.max(1, n - 1)) * 100;
      if (f.is_goal_event) {
        marks.push(`<span class="marker goal" style="left:${left}%" title="GOAL"></span>`);
      } else if (f.event_label) {
        marks.push(`<span class="marker event" style="left:${left}%" title="${escapeHTML(f.event_label)}"></span>`);
      }
    });
    markersEl.innerHTML = marks.join("");
  }

  /* ---------- P-chart under the slider ---------- */
  let chartCursor = null;
  function renderChart() {
    if (!chartEl) return;
    const perspective = currentPerspective();
    let povTeamId = null, povName = "team";
    if (perspective === "home") {
      povTeamId = c.home_team?.team_id || c.home_team?.id || c.home_team?.short;
      povName = c.home_team?.short || c.home_team?.name || "home";
    } else if (perspective === "away") {
      povTeamId = c.away_team?.team_id || c.away_team?.id || c.away_team?.short;
      povName = c.away_team?.short || c.away_team?.name || "away";
    }
    chartEl.innerHTML = pChartSvg(frames, { perspective, povTeamId, povName });
    chartCursor = chartEl.querySelector(".chart-cursor");
  }
  renderChart();
  registerChartRedraw(renderChart);

  /* ---------- playback state ---------- */
  let i = 0;
  let playTimer = null;
  let pauseUntil = 0;
  let lastEventIdxShown = -1;
  // Smoothed attention vector (length 22) for edge widths + halo radii.
  let smoothAttn = (frames[0].attention || new Array(22).fill(0)).slice();
  // Track wall-clock start of the current dwell on a particular frame
  // so the pulsing halo phase is continuous across frames.
  const pulseStart = performance.now();
  let rafId = null;

  /* ---------- helpers ---------- */
  function mToSvg(xm, ym) {
    // pitch xm in [-L/2, L/2], ym in [-W/2, W/2] → SVG coords with PITCH_PAD margin.
    const innerW = SVG_W - 2 * PITCH_PAD;
    const innerH = SVG_H - 2 * PITCH_PAD;
    const sx = ((xm + PITCH_LENGTH_M / 2) / PITCH_LENGTH_M) * innerW + PITCH_PAD;
    const sy = (1 - (ym + PITCH_WIDTH_M / 2) / PITCH_WIDTH_M) * innerH + PITCH_PAD;
    return [sx, sy];
  }

  function easeStep(prev, target, dtMs) {
    const k = 1 - Math.exp(-dtMs / SMOOTH_TAU_MS);
    return prev + (target - prev) * k;
  }

  /* ---------- main render ---------- */
  let lastFrameTime = performance.now();

  function renderFrame(force = false) {
    const f = frames[i];
    if (!f) return;
    const now = performance.now();
    const dt = Math.max(0, Math.min(500, now - lastFrameTime));
    lastFrameTime = now;

    // Smooth the attention vector toward the current frame's attention.
    const tgt = f.attention || smoothAttn;
    for (let s = 0; s < 22; s++) {
      smoothAttn[s] = easeStep(smoothAttn[s] || 0, tgt[s] || 0, dt);
    }

    // Player dots + labels (with collision avoidance).
    const players = f.players || [];
    const placed = []; // {x, y, w, h} of placed labels for overlap checks
    // Index playerDOM by slot index (not iteration index) so the rest of
    // the code can use `playerDOM[slot]` regardless of how the JSON orders
    // the players array.
    const playerDOM = new Array(22).fill(null);
    for (const p of players) {
      const [sx, sy] = mToSvg(p.x, p.y);
      const color = teamColorFor(p.slot, p.team_id);
      playerDOM[p.slot] = { p, sx, sy, color };
    }

    // --- player circles
    let dotsHTML = "";
    for (const entry of playerDOM) {
      if (!entry) continue;
      const { p, sx, sy, color } = entry;
      const radius = p.is_gk ? 9 : 8;
      const stroke = p.is_gk ? "#00d68f" : "#ffffffcc";
      const sw = p.is_gk ? 2.0 : 1.0;
      // Velocity arrow tail — 0.5s lookahead, deterministic.
      const lead = 0.5; // seconds
      const [ex, ey] = mToSvg(p.x + p.vx * lead, p.y + p.vy * lead);
      const v = Math.hypot(ex - sx, ey - sy);
      const arrow = v > 4
        ? `<line x1="${sx}" y1="${sy}" x2="${ex}" y2="${ey}" stroke="${color}" stroke-opacity="0.55" stroke-width="1.4" />`
        : "";
      dotsHTML += `${arrow}<circle cx="${sx}" cy="${sy}" r="${radius}" fill="${color}" stroke="${stroke}" stroke-width="${sw}" />`;
    }
    gPlayers.innerHTML = dotsHTML;

    // --- attention edges to top-N attended players, with user-controlled
    // GK inclusion + offense/defense category filter.
    const topK = currentTopN();
    const includeGk = currentIncludeGk();
    const edgeFilter = currentEdgeFilter();
    const isOff = (p) => p && (p.position === "FWD" || p.position === "MID"
                               || /^(CF|ST|LW|RW|AM|CM|DM|LM|RM)$/i.test(String(p.position || "")));
    const isDef = (p) => p && (p.position === "DEF" || p.position === "GK"
                               || /^(CB|LB|RB|LCB|RCB|GK)$/i.test(String(p.position || "")));
    const topIdx = smoothAttn
      .map((v, i) => [v, i])
      .filter(([, i]) => {
        const t = playerDOM[i] && playerDOM[i].p;
        if (!t) return false;
        if (!includeGk && t.is_gk) return false;
        if (edgeFilter === "off" && !isOff(t)) return false;
        if (edgeFilter === "def" && !isDef(t)) return false;
        return true;
      })
      .sort((a, b) => b[0] - a[0])
      .slice(0, topK)
      .map(([, i]) => i);
    const bxy = mToSvg(f.ball.x, f.ball.y);
    let edgesHTML = "";
    for (const s of topIdx) {
      const target = playerDOM[s];
      if (!target) continue;
      const a = smoothAttn[s] || 0;
      // Map attention to edge thickness 0.8..5.5
      const w = 0.8 + Math.min(0.6, a) * 8.0;
      const opacity = 0.35 + Math.min(0.6, a) * 0.8;
      // Same-team vs cross-team (relative to the ball-carrying team if known).
      const carrierTeam = ballCarrierTeamId(f, players);
      const same = carrierTeam && String(target.p.team_id) === String(carrierTeam);
      const stroke = same ? "#facc15" : "#fb923c";
      edgesHTML += `<line x1="${bxy[0]}" y1="${bxy[1]}" x2="${target.sx}" y2="${target.sy}" stroke="${stroke}" stroke-width="${w.toFixed(2)}" stroke-opacity="${opacity.toFixed(2)}" stroke-linecap="round" />`;
    }
    gEdges.innerHTML = edgesHTML;

    // --- halos on top-K (smoothed radius + pulse on rank-0)
    let halosHTML = "";
    const pulse = 1 + 0.15 * Math.sin(((performance.now() - pulseStart) / PULSE_PERIOD_MS) * Math.PI * 2);
    topIdx.forEach((s, rank) => {
      const target = playerDOM[s];
      if (!target) return;
      const a = smoothAttn[s] || 0;
      const r = 14 + Math.min(0.5, a) * 28;       // base radius
      const rPulse = rank === 0 ? r * pulse : r;
      halosHTML += `<circle cx="${target.sx}" cy="${target.sy}" r="${rPulse.toFixed(1)}" fill="none" stroke="#fde047" stroke-width="2" stroke-opacity="${(0.65 - rank * 0.15).toFixed(2)}" />`;
    });
    gHalos.innerHTML = halosHTML;

    // --- ball: a clear white-and-black soccer ball, well above player dots.
    // Outer "glow" ring makes it pop against a halo-rich scene; the central
    // disc + a couple of pentagon-style chips give it the visual signature of
    // a real ball without needing a raster image.
    const bx = bxy[0], by = bxy[1];
    const R = 8.5;
    gBall.innerHTML = `
      <circle cx="${bx}" cy="${by}" r="${R + 3.5}" fill="none" stroke="#000" stroke-width="1.2" stroke-opacity="0.55" />
      <circle cx="${bx}" cy="${by}" r="${R}" fill="#ffffff" stroke="#111" stroke-width="1.6" />
      <polygon points="${bx},${by - R * 0.55} ${bx + R * 0.52},${by - R * 0.17} ${bx + R * 0.32},${by + R * 0.45} ${bx - R * 0.32},${by + R * 0.45} ${bx - R * 0.52},${by - R * 0.17}" fill="#111" />
      <circle cx="${bx - R * 0.62}" cy="${by + R * 0.55}" r="${R * 0.18}" fill="#111" />
      <circle cx="${bx + R * 0.62}" cy="${by + R * 0.55}" r="${R * 0.18}" fill="#111" />
      <circle cx="${bx}" cy="${by - R * 0.78}" r="${R * 0.16}" fill="#111" />`;

    // --- labels with collision avoidance
    let labelsHTML = "";
    // Order labels by attention (high-attention players draw first → others
    // get nudged around them, not the reverse).
    const orderedSlots = [...players].map((p) => p.slot).sort((a, b) => (smoothAttn[b] || 0) - (smoothAttn[a] || 0));
    for (const slot of orderedSlots) {
      const dom = playerDOM[slot];
      if (!dom) continue;
      const { p, sx, sy, color } = dom;
      const surname = (p.name || `slot ${p.slot}`).split(" ").slice(-1)[0];
      const txt = p.position ? `${surname} · ${p.position}` : surname;
      const labelW = txt.length * 5.1 + 8;
      const labelH = 11;
      const { lx, ly } = pickLabelPos(sx, sy, p.vx, p.vy, labelW, labelH, placed);
      placed.push({ x: lx, y: ly, w: labelW, h: labelH });
      labelsHTML += `<g class="iplay-label"><rect x="${lx}" y="${ly}" width="${labelW}" height="${labelH}" fill="#0b1220" fill-opacity="0.7" rx="2.5" /><text x="${lx + 4}" y="${ly + 8}" fill="#ffffff" font-size="8.5" font-family="-apple-system,Segoe UI,sans-serif">${escapeSvg(txt)}</text></g>`;
    }
    gLabels.innerHTML = labelsHTML;

    // --- goal-mouth highlight (~1s window after goal frame)
    let highlightHTML = "";
    const goalIdxNear = nearestGoalFrameWithin(frames, i, 5); // 5 frames @ 5Hz ≈ 1s
    if (goalIdxNear >= 0) {
      const gf = frames[goalIdxNear];
      const scoringTeam = gf.scoring_team_id || gf.in_possession_team_id;
      const color = scoringTeam ? (teamColors.get(String(scoringTeam)) || "#ffd166") : "#ffd166";
      // Which goal mouth? Use the average of the scoring team's x at the goal frame:
      // attackers tend to cluster forward of midfield, so >0 means right goal.
      const team_xs = (gf.players || []).filter((p) => String(p.team_id) === String(scoringTeam)).map((p) => p.x);
      const meanX = team_xs.length ? team_xs.reduce((a, b) => a + b, 0) / team_xs.length : (gf.ball.x || 0);
      const rightGoal = meanX > 0;
      const [gx0, gy0] = mToSvg(rightGoal ? PITCH_LENGTH_M / 2 : -PITCH_LENGTH_M / 2, -PITCH_WIDTH_M / 2);
      const [gx1, gy1] = mToSvg(rightGoal ? PITCH_LENGTH_M / 2 : -PITCH_LENGTH_M / 2,  PITCH_WIDTH_M / 2);
      const w = 14;
      const x = Math.min(gx0, gx1) + (rightGoal ? 0 : -w);
      const yA = Math.min(gy0, gy1);
      const hRect = Math.abs(gy1 - gy0);
      // Penalty area sized rectangle around the goal mouth.
      const padX = rightGoal ? -16 : 0;
      const penY = SVG_H * 0.20; // visible band, not the full pitch height
      highlightHTML = `<rect x="${x + padX - 4}" y="${yA + penY}" width="${w + 24}" height="${hRect - penY * 2}" fill="${color}" fill-opacity="0.12" stroke="${color}" stroke-width="3" rx="3" />`;
    }
    gGoalHighlight.innerHTML = highlightHTML;

    // --- event strip + auto-pause when an event lands
    const evLabel = cleanEventLabel(f.event_label);
    if (evLabel && lastEventIdxShown !== i) {
      lastEventIdxShown = i;
      if (playTimer) {
        // Auto-pause for EVENT_PAUSE_MS
        pauseUntil = performance.now() + EVENT_PAUSE_MS;
      }
      evtStrip.classList.add("flash");
      setTimeout(() => evtStrip.classList.remove("flash"), 350);
    }
    if (f.is_goal_event) {
      evtStrip.className = "event-strip goal";
      evtStrip.innerHTML = `⚽ <strong>GOAL</strong> — ${escapeHTML(cleanEventLabel(f.event_label) || "")}`;
    } else if (evLabel) {
      evtStrip.className = "event-strip";
      evtStrip.innerHTML = escapeHTML(evLabel);
    } else if (goalFrame >= 0) {
      const ahead = goalFrame - i;
      if (ahead > 0) {
        evtStrip.className = "event-strip muted";
        evtStrip.innerHTML = `⚽ goal in ${(ahead * 0.2).toFixed(1)}s →`;
      } else {
        evtStrip.className = "event-strip muted";
        evtStrip.innerHTML = `after goal`;
      }
    } else {
      evtStrip.className = "event-strip muted";
      evtStrip.innerHTML = "&nbsp;";
    }

    // --- meta line
    const topChips = topIdx.map((s) => {
      const p = players[s];
      if (!p) return "";
      const n = p.name ? p.name.split(" ").slice(-1)[0] + (p.position ? " · " + p.position : "") : `slot ${s}`;
      return `<span class="chip">${escapeHTML(n)} <span class="muted">${fmtNum(smoothAttn[s], 2)}</span></span>`;
    }).join(" ");
    meta.innerHTML = `
      <strong>Frame ${i + 1}/${n}</strong> &nbsp;•&nbsp;
      P(score, next&nbsp;10&nbsp;s) <span class="chip green tabular">${fmtNum(f.p_score, 3)}</span> &nbsp;
      P(concede, next&nbsp;10&nbsp;s) <span class="chip red tabular">${fmtNum(f.p_concede, 3)}</span> &nbsp;
      Frame-VAEP (Δ&nbsp;P) <span class="chip tabular">${fmtNum(f.vaep, 3)}</span><br>
      <span class="small muted">Top attended (ball→player attention):</span>
      <div class="top-attn-row">${topChips || "<span class='muted'>—</span>"}</div>`;

    // --- chart cursor
    if (chartCursor) {
      const xPct = (i / Math.max(1, n - 1)) * 100;
      chartCursor.setAttribute("x1", String(xPct) + "%");
      chartCursor.setAttribute("x2", String(xPct) + "%");
    }
  }

  function clampToFocus(j) {
    if (!focusEnabled() || goalFrame < 0) return Math.max(0, Math.min(n - 1, j));
    const lo = Math.max(0, goalFrame - 50);    // 10s @ 5 Hz
    const hi = Math.min(n - 1, goalFrame);
    return Math.max(lo, Math.min(hi, j));
  }
  function setFrame(j) {
    i = clampToFocus(j);
    scrub.value = String(i);
    renderFrame(true);
  }
  function applyFocus() {
    if (focusEnabled() && goalFrame >= 0) {
      scrub.min = String(Math.max(0, goalFrame - 50));
      scrub.max = String(Math.min(n - 1, goalFrame));
      setFrame(Number(scrub.value));
    } else {
      scrub.min = "0";
      scrub.max = String(n - 1);
    }
  }
  registerFocusUpdate(applyFocus);
  registerFrameRedraw(() => renderFrame(true));

  // RAF loop for smooth halo pulse + attention easing even when not stepping.
  function tick() {
    renderFrame(false);
    rafId = requestAnimationFrame(tick);
  }
  rafId = requestAnimationFrame(tick);

  setFrame(0);
  applyFocus();

  scrub.addEventListener("input", (e) => setFrame(Number(e.target.value)));

  document.querySelectorAll(`[data-clip="${c.label}"]`).forEach((btn) => {
    btn.addEventListener("click", () => {
      const a = btn.dataset.action;
      if (a === "prev") setFrame(i - 1);
      else if (a === "next") setFrame(i + 1);
      else if (a === "goal") { if (goalFrame >= 0) setFrame(goalFrame); }
      else if (a === "play") {
        if (playTimer) {
          clearInterval(playTimer);
          playTimer = null;
          btn.textContent = "▶ play";
        } else {
          btn.textContent = "⏸ pause";
          playTimer = setInterval(() => {
            if (performance.now() < pauseUntil) return; // auto-paused on event
            if (i + 1 >= n) {
              clearInterval(playTimer);
              playTimer = null;
              btn.textContent = "▶ play";
              return;
            }
            setFrame(i + 1);
          }, TICK_MS);
        }
      }
    });
  });
}

/* ============================================================
   SVG scaffolding helpers
   ============================================================ */

function pitchSvgScaffold(detail) {
  // Pitch lines + groups for everything we paint per frame.
  // mToSvgRaw flips Y (top-of-pitch = small sy, bottom = large sy), so we
  // must use min/abs for rect x/y/width/height — a negative-height <rect>
  // doesn't render in SVG, which is why the previous version showed no
  // pitch fill, no penalty boxes, and no goal mouths.
  const HL = PITCH_LENGTH_M / 2, HW = PITCH_WIDTH_M / 2;
  const [ax, ay] = mToSvgRaw(-HL, -HW);
  const [bx, by] = mToSvgRaw(HL, HW);
  const px = Math.min(ax, bx);
  const py = Math.min(ay, by);
  const w  = Math.abs(bx - ax);
  const h  = Math.abs(by - ay);
  const cx = px + w / 2;
  const cy = py + h / 2;
  const sixYardW  = (5.5  / PITCH_LENGTH_M) * w;
  const sixYardH  = (18.32 / PITCH_WIDTH_M) * h;
  const penBoxW   = (16.5 / PITCH_LENGTH_M) * w;
  const penBoxH   = (40.32 / PITCH_WIDTH_M) * h;
  const goalDepth = (2.0  / PITCH_LENGTH_M) * w;
  const goalH     = (7.32 / PITCH_WIDTH_M) * h;
  const penSpotR  = Math.max(1.4, (0.3 / PITCH_LENGTH_M) * w);
  const xLeft  = px;
  const xRight = px + w;
  const lines = `
    <rect x="${px}" y="${py}" width="${w}" height="${h}" fill="#1f7a3f" stroke="#f4fbf6" stroke-width="2.2" />
    <line x1="${cx}" y1="${py}" x2="${cx}" y2="${py + h}" stroke="#f4fbf6" stroke-width="1.4" />
    <circle cx="${cx}" cy="${cy}" r="${(9.15 / PITCH_LENGTH_M) * w}" fill="none" stroke="#f4fbf6" stroke-width="1.4" />
    <circle cx="${cx}" cy="${cy}" r="1.6" fill="#f4fbf6" />
    <rect x="${xLeft}" y="${cy - penBoxH / 2}" width="${penBoxW}" height="${penBoxH}" fill="none" stroke="#f4fbf6" stroke-width="1.6" />
    <rect x="${xRight - penBoxW}" y="${cy - penBoxH / 2}" width="${penBoxW}" height="${penBoxH}" fill="none" stroke="#f4fbf6" stroke-width="1.6" />
    <rect x="${xLeft}" y="${cy - sixYardH / 2}" width="${sixYardW}" height="${sixYardH}" fill="none" stroke="#f4fbf6" stroke-width="1.2" />
    <rect x="${xRight - sixYardW}" y="${cy - sixYardH / 2}" width="${sixYardW}" height="${sixYardH}" fill="none" stroke="#f4fbf6" stroke-width="1.2" />
    <circle cx="${xLeft + (11.0 / PITCH_LENGTH_M) * w}" cy="${cy}" r="${penSpotR}" fill="#f4fbf6" />
    <circle cx="${xRight - (11.0 / PITCH_LENGTH_M) * w}" cy="${cy}" r="${penSpotR}" fill="#f4fbf6" />
    <rect x="${xLeft - goalDepth}" y="${cy - goalH / 2}" width="${goalDepth}" height="${goalH}" fill="#f4fbf6" stroke="#f4fbf6" stroke-width="1.4" opacity="0.95" />
    <rect x="${xRight}" y="${cy - goalH / 2}" width="${goalDepth}" height="${goalH}" fill="#f4fbf6" stroke="#f4fbf6" stroke-width="1.4" opacity="0.95" />`;
  const homeColor = detail.home_team?.color || "#5eead4";
  const awayColor = detail.away_team?.color || "#f87171";
  const homeShort = detail.home_team?.short || "HOM";
  const awayShort = detail.away_team?.short || "AWY";
  return `
    <div class="iplay-titlebar">
      <span class="iplay-team" style="color:${homeColor}">● ${escapeHTML(homeShort)}</span>
      <span class="iplay-title">${escapeHTML(detail.title || "")}</span>
      <span class="iplay-team" style="color:${awayColor}">${escapeHTML(awayShort)} ●</span>
    </div>
    <svg class="iplay-pitch" viewBox="0 0 ${SVG_W} ${SVG_H}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
      ${lines}
      <g id="g-goal-highlight"></g>
      <g id="g-edges"></g>
      <g id="g-halos"></g>
      <g id="g-players"></g>
      <g id="g-ball"></g>
      <g id="g-labels"></g>
    </svg>`;
}

function mToSvgRaw(xm, ym) {
  const innerW = SVG_W - 2 * PITCH_PAD;
  const innerH = SVG_H - 2 * PITCH_PAD;
  const sx = ((xm + PITCH_LENGTH_M / 2) / PITCH_LENGTH_M) * innerW + PITCH_PAD;
  const sy = (1 - (ym + PITCH_WIDTH_M / 2) / PITCH_WIDTH_M) * innerH + PITCH_PAD;
  return [sx, sy];
}

/* ============================================================
   Label collision avoidance.
   Strategy: candidate positions are (1) along velocity vector,
   (2) opposite velocity, (3) ±perpendicular to velocity. Each
   candidate is rejected if it overlaps any already-placed label.
   First non-overlapping candidate wins. Deterministic per frame.
   ============================================================ */

function pickLabelPos(sx, sy, vx, vy, w, h, placed) {
  const offset = 12;
  let dx = vx, dy = -vy; // SVG y is flipped from pitch y
  let m = Math.hypot(dx, dy);
  if (m < 0.5) { dx = 1; dy = 0; m = 1; }
  dx /= m; dy /= m;
  const px = -dy, py = dx; // perpendicular
  const candidates = [
    [sx + dx * offset, sy + dy * offset],                   // along velocity
    [sx + px * offset, sy + py * offset],                   // perpendicular +
    [sx - px * offset, sy - py * offset],                   // perpendicular -
    [sx - dx * offset, sy - dy * offset],                   // opposite velocity
    [sx + dx * offset * 1.8, sy + dy * offset * 1.8],       // farther along
    [sx + offset, sy - offset],                              // upper-right fallback
    [sx - offset - w, sy - offset],                          // upper-left
    [sx + offset, sy + offset],                              // lower-right
    [sx - offset - w, sy + offset],                          // lower-left
  ];
  for (const [cx, cy] of candidates) {
    const lx = cx - w / 2;
    const ly = cy - h / 2;
    if (!overlapsAny(lx, ly, w, h, placed)) return { lx, ly };
  }
  // No clear candidate — pick the one with minimum overlap area.
  let best = candidates[0];
  let bestScore = Infinity;
  for (const [cx, cy] of candidates) {
    const lx = cx - w / 2;
    const ly = cy - h / 2;
    const score = overlapArea(lx, ly, w, h, placed);
    if (score < bestScore) { bestScore = score; best = [cx, cy]; }
  }
  return { lx: best[0] - w / 2, ly: best[1] - h / 2 };
}

function overlapsAny(x, y, w, h, placed) {
  for (const r of placed) {
    if (x < r.x + r.w && x + w > r.x && y < r.y + r.h && y + h > r.y) return true;
  }
  return false;
}

function overlapArea(x, y, w, h, placed) {
  let s = 0;
  for (const r of placed) {
    const ox = Math.max(0, Math.min(x + w, r.x + r.w) - Math.max(x, r.x));
    const oy = Math.max(0, Math.min(y + h, r.y + r.h) - Math.max(y, r.y));
    s += ox * oy;
  }
  return s;
}

/* ============================================================
   P-chart helpers
   ============================================================ */

function pChartSvg(frames, opts = {}) {
  const n = frames.length;
  if (n === 0) return "";
  const w = 100, h = CHART_H;
  const pad = 4;
  const perspective = opts.perspective || "raw";
  const povTeamId = opts.povTeamId;
  const povName = opts.povName || "team";

  // Event markers along the time axis
  const evMarks = frames.map((f, i) => {
    if (!f.event_label) return "";
    const px = (i / Math.max(1, n - 1)) * (w - 2 * pad) + pad;
    const color = f.is_goal_event ? "#ffd166" : "#9aa5b1";
    const dy = f.is_goal_event ? 6 : 4;
    return `<line x1="${px}" y1="${h - dy}" x2="${px}" y2="${h}" stroke="${color}" stroke-width="${f.is_goal_event ? 0.9 : 0.4}" />`;
  }).join("");

  if (perspective === "raw") {
    const pathFor = (key, color) => {
      const ys = frames.map((f) => f[key] || 0);
      const ymax = Math.max(0.05, ...ys, ...frames.map((f) => f.p_concede || 0), ...frames.map((f) => f.p_score || 0));
      const pts = ys.map((y, i) => {
        const px = (i / Math.max(1, n - 1)) * (w - 2 * pad) + pad;
        const py = h - pad - (y / ymax) * (h - 2 * pad);
        return `${px.toFixed(2)},${py.toFixed(2)}`;
      });
      return `<polyline fill="none" stroke="${color}" stroke-width="0.6" stroke-linecap="round" points="${pts.join(" ")}" />`;
    };
    return `
      <div class="chart-title">
        <span><span class="dot" style="background:#54c875"></span>P(score)</span>
        <span><span class="dot" style="background:#e07474"></span>P(concede)</span>
        <span class="dim small">events tick the bottom; goal in gold</span>
      </div>
      <svg class="chart-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="0" y="0" width="${w}" height="${h}" fill="#0b1220" />
        ${pathFor("p_concede", "#e07474")}
        ${pathFor("p_score", "#54c875")}
        ${evMarks}
        <line class="chart-cursor" x1="0%" y1="0" x2="0%" y2="${h}" stroke="#fde047" stroke-width="0.4" stroke-opacity="0.85" />
      </svg>`;
  }

  // Net mode: single smoothed curve from chosen team's POV, fixed [-1, +1] range.
  const netRaw = frames.map((f) => {
    const possIsPov = String(f.in_possession_team_id) === String(povTeamId);
    const ps = f.p_score || 0, pc = f.p_concede || 0;
    const myScore = possIsPov ? ps : pc;
    const myConcede = possIsPov ? pc : ps;
    return myScore - myConcede;
  });
  // Centered 7-frame smoothing (~1.4s at 5 Hz).
  const win = 7, half = Math.floor(win / 2);
  const net = netRaw.map((_, i) => {
    let s = 0, c = 0;
    for (let j = Math.max(0, i - half); j <= Math.min(netRaw.length - 1, i + half); j++) {
      if (Number.isFinite(netRaw[j])) { s += netRaw[j]; c++; }
    }
    return c > 0 ? s / c : 0;
  });
  const yToPy = (v) => h - pad - ((v + 1) / 2) * (h - 2 * pad);  // map [-1, +1] → plot
  const pts = net.map((v, i) => {
    const px = (i / Math.max(1, n - 1)) * (w - 2 * pad) + pad;
    return `${px.toFixed(2)},${yToPy(v).toFixed(2)}`;
  });
  const zeroY = yToPy(0).toFixed(2);
  return `
    <div class="chart-title">
      <span><span class="dot" style="background:#54c875"></span>Net P · from ${escapeHTML(povName)} (smoothed)</span>
      <span class="dim small">+1 = about to score &nbsp;·&nbsp; −1 = about to concede</span>
    </div>
    <svg class="chart-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="0" width="${w}" height="${h}" fill="#0b1220" />
      <line x1="${pad}" y1="${zeroY}" x2="${w - pad}" y2="${zeroY}" stroke="#3a4554" stroke-width="0.2" />
      <polyline fill="none" stroke="#54c875" stroke-width="0.7" stroke-linecap="round" points="${pts.join(" ")}" />
      ${evMarks}
      <line class="chart-cursor" x1="0%" y1="0" x2="0%" y2="${h}" stroke="#fde047" stroke-width="0.4" stroke-opacity="0.85" />
    </svg>`;
}

/* ============================================================
   Misc helpers
   ============================================================ */

function topKIndices(arr, k) {
  const idx = arr.map((v, i) => [v, i]).sort((a, b) => b[0] - a[0]);
  return idx.slice(0, k).map((p) => p[1]);
}

function ballCarrierTeamId(frame, players) {
  // The slot flagged has_possession is the carrier. Return their team_id.
  for (const p of players) {
    if (p.has_possession) return p.team_id;
  }
  return frame.in_possession_team_id || null;
}

function nearestGoalFrameWithin(frames, i, windowFrames) {
  // Returns the index of a goal frame at or before i within `windowFrames` of i.
  // Highlighting persists for ~1s AFTER the goal lands.
  for (let k = 0; k <= windowFrames; k++) {
    const j = i - k;
    if (j < 0) break;
    if (frames[j] && frames[j].is_goal_event) return j;
  }
  return -1;
}

function escapeSvg(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
