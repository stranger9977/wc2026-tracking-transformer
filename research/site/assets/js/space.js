// space.js — "Space — Soccer's Dark Matter" (rebuild).
// Intro: what is space / what is control (FIFA WC2026 data).
// Act 0: xT reference heatmap (the value of space — Singh model).
// Act 1 (CHASE): Defensive Gravity. Act 2 (P-OBSO): Dangerous Space — pitch control x Expected Threat.
//   Each: a LIVE scrubbable canvas heatmap (pitch underneath, per-cell color), a leaderboard, a team
//   scatter, and an xG-receipt "so what" panel.
// Closing: live FIFA EFI 2026 (threat/xG leaders) + the space-not-distance note + a CV-tracking tie-in.
// SMS + SAR are stashed to space-wip.html (function defs kept, exposed via window.__spaceWIP).
// All paths relative to the document (site root). Pre-normalized 0..1 surfaces.

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

async function loadJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

const teamColor = (t) => ({
  Argentina: "#6cb4ee", France: "#3f6bd6", Morocco: "#c1272d", Croatia: "#e23b3b",
  Germany: "#d8d8d8", Spain: "#f0b429", Portugal: "#2e8b57", England: "#dfe7f0",
  Netherlands: "#e7872b", Japan: "#d24b6a", Australia: "#f0c419", Brazil: "#f7d716",
  Switzerland: "#e64545", Poland: "#d83a56", Belgium: "#e6b400", Egypt: "#1f8a5b",
  USA: "#3c6fd1", Mexico: "#1f9d55", Turkey: "#e23b3b", Uruguay: "#56b0e6",
}[t] || "#9aa6b6");

// 3-digit code -> readable for the EFI act
const CODE = { BEL: "Belgium", EGY: "Egypt", TUR: "Turkey", ESP: "Spain", URU: "Uruguay",
  CAN: "Canada", SUI: "Switzerland", NED: "Netherlands", USA: "USA", MEX: "Mexico",
  GER: "Germany", BRA: "Brazil", JPN: "Japan", KOR: "S.Korea", MAR: "Morocco",
  AUS: "Australia", SWE: "Sweden", IRN: "Iran", QAT: "Qatar", PAR: "Paraguay" };
const codeName = (c) => CODE[c] || c;

/* ---------------- reveal-on-scroll ---------------- */
function initReveal() {
  const io = new IntersectionObserver((es) => {
    for (const e of es) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }, { threshold: 0.1 });
  $$(".reveal").forEach((el) => io.observe(el));
}

/* =================================================================
   CANVAS HEATMAP RENDERER + SCRUBBER
   A pitch is drawn underneath; per-cell color over it; players overlaid.
   Surfaces are pre-normalized 0..1 (attacking left->right, +x = opp goal).
   Pitch is 105 x 68 m, center origin in source coords.
   ================================================================= */

// viridis-ish ramp for "danger / control" surfaces (dark->bright)
function rampHot(t) {
  t = clamp(t, 0, 1);
  // dark navy -> teal -> green -> yellow -> hot
  const stops = [
    [14, 16, 20], [26, 52, 92], [33, 122, 140], [60, 184, 120], [190, 220, 70], [255, 196, 60], [255, 107, 107],
  ];
  const x = t * (stops.length - 1), i = Math.floor(x), f = x - i;
  const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}
// cool ramp for DEFENDER control (CHASE) — the block owns space in blue/violet
function rampCool(t) {
  t = clamp(t, 0, 1);
  const stops = [[14, 16, 20], [30, 34, 64], [58, 60, 150], [120, 96, 220], [180, 150, 245], [220, 205, 255]];
  const x = t * (stops.length - 1), i = Math.floor(x), f = x - i;
  const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

// meters (center origin) -> pixel on a W x H canvas (attacking +x = right)
function m2px(x, y, W, H) {
  return [(x + 52.5) / 105 * W, (34 - y) / 68 * H];
}

function drawPitchLines(ctx, W, H) {
  ctx.save();
  ctx.strokeStyle = "rgba(190,210,230,0.22)";
  ctx.lineWidth = Math.max(1, W / 520);
  const pad = 0;
  ctx.strokeRect(pad, pad, W - 2 * pad, H - 2 * pad);
  // halfway
  ctx.beginPath(); ctx.moveTo(W / 2, 0); ctx.lineTo(W / 2, H); ctx.stroke();
  // center circle
  ctx.beginPath(); ctx.arc(W / 2, H / 2, 9.15 / 105 * W, 0, Math.PI * 2); ctx.stroke();
  // boxes (18-yard ~ 16.5m deep, 40.3m wide) both ends
  const boxW = 16.5 / 105 * W, boxH = 40.3 / 68 * H;
  ctx.strokeRect(0, (H - boxH) / 2, boxW, boxH);
  ctx.strokeRect(W - boxW, (H - boxH) / 2, boxW, boxH);
  // 6-yard
  const sixW = 5.5 / 105 * W, sixH = 18.3 / 68 * H;
  ctx.strokeRect(0, (H - sixH) / 2, sixW, sixH);
  ctx.strokeRect(W - sixW, (H - sixH) / 2, sixW, sixH);
  ctx.restore();
}

// Render a single normalized surface (2D array [ny][rows] of 0..1) onto ctx, with the pitch on top.
// opts: ramp(fn), gamma(contrast — lower = brighter), threshold(only cells>thr lit), alpha(max cell alpha)
// A subtle additive bloom pass on the brightest cells makes hot pockets pop without washing the pitch.
function paintSurface(ctx, surface, W, H, opts = {}) {
  const ramp = opts.ramp || rampHot;
  const gamma = opts.gamma ?? 0.6;
  const thr = opts.threshold ?? 0;
  const aMax = opts.alpha ?? 0.96;
  const ny = surface.length, nx = surface[0].length;
  // offscreen pixel buffer at grid resolution, then scale up smoothly
  const off = paintSurface._off || (paintSurface._off = document.createElement("canvas"));
  off.width = nx; off.height = ny;
  const octx = off.getContext("2d");
  const img = octx.createImageData(nx, ny);
  for (let r = 0; r < ny; r++) {
    for (let c = 0; c < nx; c++) {
      let v = surface[r][c];
      const i = (r * nx + c) * 4;
      if (v <= thr) { img.data[i + 3] = 0; continue; }
      const t = Math.pow(clamp(v, 0, 1), gamma);
      const [rr, gg, bb] = ramp(t);
      img.data[i] = rr; img.data[i + 1] = gg; img.data[i + 2] = bb;
      // clamp the alpha curve up so even mid-value cells are clearly lit
      img.data[i + 3] = Math.round(255 * aMax * clamp(t * 1.35, 0.12, 1));
    }
  }
  octx.putImageData(img, 0, 0);
  ctx.clearRect(0, 0, W, H);
  // base = a dim, uniform PITCH GREEN (not near-black) so areas the team doesn't
  // control read as neutral grass, never a scary growing "dark void". Danger then
  // glows brighter than the grass instead of holes opening in black.
  const felt = ctx.createLinearGradient(0, 0, 0, H);
  felt.addColorStop(0, opts.felt || "#16241b"); felt.addColorStop(1, opts.felt2 || "#101a14");
  ctx.fillStyle = felt; ctx.fillRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  // NOTE: source surface row 0 = top of pitch already in screen orientation (ny rows top->bottom),
  // and column 0 = -x (left). Source orientation is attacking +x to the right, so no flip needed.
  ctx.drawImage(off, 0, 0, nx, ny, 0, 0, W, H);
  // additive bloom: redraw the surface lightly with 'lighter' compositing so hot cells glow
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.globalAlpha = 0.28;
  ctx.drawImage(off, 0, 0, nx, ny, 0, 0, W, H);
  ctx.restore();
  drawPitchLines(ctx, W, H);
}

function drawBall(ctx, ball, W, H) {
  if (!ball) return;
  const [bx, by] = m2px(ball[0], ball[1], W, H);
  ctx.beginPath(); ctx.arc(bx, by, Math.max(3, W / 220), 0, Math.PI * 2);
  ctx.fillStyle = "#fff"; ctx.strokeStyle = "#000"; ctx.lineWidth = 1;
  ctx.fill(); ctx.stroke();
}

// players: [{x,y,att,gk,name}]; opts.highlightName pins one (kept full-opacity + white ring);
// opts.labelName draws a persistent name pill above the matching player so the key figure is obvious.
function drawPlayers(ctx, players, ball, W, H, opts = {}) {
  if (!players) return;
  const r = Math.max(6, W / 120);           // bigger, clearly-visible dots
  let labeled = null;                        // defer the label so it paints on top of every dot
  for (const p of players) {
    const [px, py] = m2px(p.x, p.y, W, H);
    const isHi = opts.highlightName && p.name === opts.highlightName;
    let alpha = 1;
    if (opts.highlightName && !isHi) alpha = 0.55;  // mild de-emphasis only; all dots stay visible
    const col = p.att ? (opts.attColor || "#7ec8ff") : (opts.defColor || "#ff9a9a");
    ctx.globalAlpha = alpha;
    ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2);
    ctx.fillStyle = p.gk ? "#6dd58c" : col;
    ctx.fill();
    // strong dark outline so dots read against the bright surface
    ctx.lineWidth = Math.max(1.6, W / 320); ctx.strokeStyle = "#0a0c10";
    ctx.stroke();
    if (isHi) {
      ctx.globalAlpha = 1;
      ctx.beginPath(); ctx.arc(px, py, r + 3.5, 0, Math.PI * 2);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke();
    }
    if (opts.labelName && p.name === opts.labelName) labeled = { px, py, name: p.name };
  }
  ctx.globalAlpha = 1;
  if (labeled) drawNamePill(ctx, labeled.px, labeled.py - r - 4, labeled.name);
}

// a small filled name pill anchored above a player dot (always visible for the key figure).
function drawNamePill(ctx, cx, baseY, name) {
  ctx.save();
  ctx.font = "600 13px Inter, system-ui, sans-serif";
  const tw = ctx.measureText(name).width;
  const padX = 7, padY = 4, w = tw + padX * 2, h = 18;
  const x = cx - w / 2, y = baseY - h;
  const rr = 6;
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
  ctx.fillStyle = "rgba(10,12,16,0.85)"; ctx.fill();
  ctx.lineWidth = 1; ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.stroke();
  // little pointer down to the dot
  ctx.beginPath();
  ctx.moveTo(cx - 4, y + h); ctx.lineTo(cx + 4, y + h); ctx.lineTo(cx, y + h + 5); ctx.closePath();
  ctx.fillStyle = "rgba(10,12,16,0.85)"; ctx.fill();
  ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(name, cx, y + h / 2 + 0.5);
  ctx.restore();
}

// CHASE: draw spokes from each defender within 12m of the gravity attacker, colored by inward speed.
// We don't have per-player velocity in the surface, so spokes are static lines (geometry of the pull).
function drawGravitySpokes(ctx, players, focus, W, H) {
  if (!focus) return;
  const f = players.find((p) => p.name === focus);
  if (!f) return;
  const [fx, fy] = m2px(f.x, f.y, W, H);
  for (const p of players) {
    if (p.att || p.gk) continue;
    const d = Math.hypot(p.x - f.x, p.y - f.y);
    if (d > 12) continue;
    const [px, py] = m2px(p.x, p.y, W, H);
    const t = 1 - d / 12;
    ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(fx, fy);
    ctx.strokeStyle = `rgba(255,${Math.round(180 - 120 * t)},90,${0.25 + 0.55 * t})`;
    ctx.lineWidth = 1 + 2.4 * t; ctx.stroke();
  }
  // gravity radius
  ctx.beginPath(); ctx.arc(fx, fy, 12 / 105 * W, 0, Math.PI * 2);
  ctx.strokeStyle = "rgba(255,107,107,0.45)"; ctx.setLineDash([4, 3]); ctx.lineWidth = 1.4;
  ctx.stroke(); ctx.setLineDash([]);
}

// Generic scrubbable canvas player. `cfg` describes the metric.
// SMOOTH SCRUB: a float playhead is tweened by requestAnimationFrame; renderAt(fFloat) LERPs player
// positions (matched by .name), the ball, and the surface cell-by-cell between the two bracketing frames.
function buildScrubber(el, surf, cfg) {
  const frames = surf.frames;
  const n = frames.length;
  const W = 640, H = Math.round(640 * 68 / 105);
  el.innerHTML = `
    <div class="hstage"><canvas width="${W}" height="${H}" id="cv-${cfg.id}"></canvas></div>
    <div class="hctrls">
      <button class="play" id="pl-${cfg.id}" aria-label="play">&#9654;</button>
      <input type="range" id="rg-${cfg.id}" min="0" max="${(n - 1) * 1000}" value="0" />
      <span class="tlabel" id="tl-${cfg.id}"></span>
    </div>
    <div class="htoggles" id="tg-${cfg.id}"></div>
    <div class="hreadout" id="ro-${cfg.id}"></div>`;
  const cv = $(`#cv-${cfg.id}`), rg = $(`#rg-${cfg.id}`), pl = $(`#pl-${cfg.id}`),
        tl = $(`#tl-${cfg.id}`), ro = $(`#ro-${cfg.id}`), tgEl = $(`#tg-${cfg.id}`);
  const ctx = cv.getContext("2d");

  // toggle state
  const state = { highlight: null, mode: cfg.defaultMode || "surface" };

  // build toggle buttons
  const toggles = cfg.toggles || [];
  tgEl.innerHTML = toggles.map((t) => `<button class="htog" data-k="${t.key}">${t.label}</button>`).join("");
  $$(".htog", tgEl).forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.k;
    state.mode = state.mode === k ? (cfg.defaultMode || "surface") : k;
    $$(".htog", tgEl).forEach((x) => x.classList.toggle("on", x.dataset.k === state.mode));
    renderAt(playhead);
  }));

  // total span in seconds — playback advances at ~real time from the frames' t_s timestamps
  const spanSec = Math.max(0.5, frames[n - 1].t_s - frames[0].t_s);
  const fracPerSec = (n - 1) / spanSec;

  // apply the active "mode" transform to a (possibly interpolated) surface
  function applyMode(surface) {
    // P-OBSO 'reveal danger' mode: multiply surface by xt_reference to keep only dangerous cells
    if (cfg.id === "pobso" && state.mode === "reveal" && surf.xt_reference) {
      const xt = surf.xt_reference, out = surface.map((row, r) => row.map((v, c) => v * (xt[r] ? xt[r][c] : 0)));
      let mx = 0; out.forEach((row) => row.forEach((v) => { if (v > mx) mx = v; }));
      if (mx > 0) for (let r = 0; r < out.length; r++) for (let c = 0; c < out[r].length; c++) out[r][c] /= mx;
      return out;
    }
    // SAR 'vs replacement' mode: subtract the baseline contour from the bright surface
    if (cfg.id === "sar" && state.mode === "replacement" && surf.baseline_overlay) {
      const bl = surf.baseline_overlay;
      return surface.map((row, r) => row.map((v, c) => clamp(v - 0.55 * (bl[r] ? bl[r][c] : 0), 0, 1)));
    }
    return surface;
  }

  // LERP the surface cell-by-cell between two frames at fraction f
  function lerpSurface(a, b, f) {
    if (f <= 0 || a === b || !b) return a;
    const out = new Array(a.length);
    for (let r = 0; r < a.length; r++) {
      const ar = a[r], br = b[r] || ar, row = new Array(ar.length);
      for (let c = 0; c < ar.length; c++) row[c] = ar[c] * (1 - f) + (br[c] ?? ar[c]) * f;
      out[r] = row;
    }
    return out;
  }

  // LERP players by matching on .name across the two frames
  function lerpPlayers(pa, pb, f) {
    if (!pa) return null;
    if (!pb || f <= 0) return pa;
    const idx = new Map(pb.map((p) => [p.name, p]));
    return pa.map((p) => {
      const q = idx.get(p.name);
      if (!q) return p;
      return { ...p, x: p.x * (1 - f) + q.x * f, y: p.y * (1 - f) + q.y * f };
    });
  }
  const lerpPt = (a, b, f) => (a && b) ? [a[0] * (1 - f) + b[0] * f, a[1] * (1 - f) + b[1] * f] : (a || b);

  // render at a fractional frame index
  function renderAt(fFloat) {
    fFloat = clamp(fFloat, 0, n - 1);
    const i0 = Math.floor(fFloat), i1 = Math.min(i0 + 1, n - 1), f = fFloat - i0;
    const fr = frames[i0], frNext = frames[i1];
    const ramp = cfg.ramp || rampHot;
    const surface = applyMode(lerpSurface(fr.surface, frNext.surface, f));
    paintSurface(ctx, surface, W, H, { ramp, gamma: cfg.gamma ?? 0.6, threshold: cfg.threshold ?? 0.04 });
    const ball = lerpPt(fr.ball_xy, frNext.ball_xy, f);
    drawBall(ctx, ball, W, H);
    if (fr.players) {
      const players = lerpPlayers(fr.players, frNext.players, f);
      const opts = { highlightName: state.highlight || cfg.labelName, labelName: cfg.labelName,
                     attColor: "#7ec8ff", defColor: "#ff9a9a" };
      if (cfg.id === "chase" && state.mode === "gravity") drawGravitySpokes(ctx, players, cfg.gravityFocus, W, H);
      drawPlayers(ctx, players, ball, W, H, opts);
    } else if (fr.hero_xy) {
      const hp = lerpPt(fr.hero_xy, frNext.hero_xy, f);
      const [hx, hy] = m2px(hp[0], hp[1], W, H);
      ctx.beginPath(); ctx.arc(hx, hy, Math.max(6, W / 120), 0, Math.PI * 2);
      ctx.fillStyle = "#fff"; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = "#6cb4ee"; ctx.stroke();
    }
    const ts = fr.t_s * (1 - f) + frNext.t_s * f;
    tl.textContent = `${i0 + 1}/${n} · ${ts.toFixed(1)}s`;
    ro.innerHTML = cfg.readout ? cfg.readout(fr, state) : "";
  }

  // float playhead (0..n-1) + rAF tween loop (~60fps)
  let playhead = 0, playing = false, raf = null, lastTs = 0;
  function syncSlider() { rg.value = Math.round(playhead * 1000); }
  function loop(now) {
    if (!playing) return;
    if (!lastTs) lastTs = now;
    const dt = Math.min(0.1, (now - lastTs) / 1000); lastTs = now;
    playhead += dt * fracPerSec;
    if (playhead >= n - 1) playhead = 0;        // loop at end
    syncSlider();
    renderAt(playhead);
    raf = requestAnimationFrame(loop);
  }
  function stop() { playing = false; pl.innerHTML = "&#9654;"; if (raf) { cancelAnimationFrame(raf); raf = null; } lastTs = 0; }
  function play() {
    if (playing) return stop();
    playing = true; pl.innerHTML = "&#10074;&#10074;"; lastTs = 0;
    raf = requestAnimationFrame(loop);
  }
  pl.addEventListener("click", play);
  rg.addEventListener("input", () => { stop(); playhead = (+rg.value) / 1000; renderAt(playhead); });
  // expose highlight setter so leaderboard hover can pin a player onto the surface
  el._setHighlight = (name) => { state.highlight = name; renderAt(playhead); };
  renderAt(0);
}

/* =================================================================
   INTRO — "What is space? What is control?" (precursor to the xT act)
   Two host divs:
     #intro-shape — an SVG mini-pitch with BRA vs MAR build-up & final-third
       blocks (width x length in metres = the pitch a team actually occupies).
     #intro-efi  — a live 2026 "offers to receive in behind, per match" bar board.
   Grounds the plain-English definitions in FIFA's own WC2026 numbers.
   ================================================================= */
async function buildIntro() {
  const shapeEl = $("#intro-shape"), efiEl = $("#intro-efi");
  if (!shapeEl && !efiEl) return;
  let d;
  try { d = await loadJSON("data/intro_efi.json"); }
  catch (e) {
    if (shapeEl) shapeEl.innerHTML = `<p class="caption">Intro data unavailable: ${e.message}</p>`;
    return;
  }

  /* ---- team-SHAPE: TWO side-by-side mini-pitches (one per team) so the
         build-up vs final-third blocks never overlap and labels stay legible ---- */
  if (shapeEl) {
    const shp = d.example_match.in_possession_shape;
    const teams = ["Brazil", "Morocco"];
    const phases = [
      { key: "build_up_low", label: "build-up", dash: false },
      { key: "final_third_phase", label: "final third", dash: true },
    ];
    const PL = 105, PW = 68, PAD = 12, W = 400, scale = (W - 2 * PAD) / PL, H = PW * scale + 2 * PAD;
    const sx = (m) => PAD + m * scale;                  // own goal x=0 .. opp goal x=105
    const sy = (m) => PAD + (PW / 2 - m) * scale;        // width 0 = centre
    const boxL = 16.5 * scale, boxW = 40.3 * scale;
    function pitch(team) {
      const col = teamColor(team);
      let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" class="ishape-svg" role="img" aria-label="${team} team shape, build-up vs final third">`;
      s += `<rect x="${PAD}" y="${PAD}" width="${W - 2 * PAD}" height="${(PW * scale).toFixed(1)}" fill="#0b160f" stroke="#2a313d" stroke-width="1.2"/>`;
      s += `<line x1="${W / 2}" y1="${PAD}" x2="${W / 2}" y2="${(PAD + PW * scale).toFixed(1)}" stroke="#2a313d" stroke-width="1"/>`;
      s += `<circle cx="${W / 2}" cy="${(PAD + PW * scale / 2).toFixed(1)}" r="${(9.15 * scale).toFixed(1)}" fill="none" stroke="#2a313d" stroke-width="1"/>`;
      s += `<rect x="${(W - PAD - boxL).toFixed(1)}" y="${(PAD + (PW * scale - boxW) / 2).toFixed(1)}" width="${boxL.toFixed(1)}" height="${boxW.toFixed(1)}" fill="none" stroke="#2a313d" stroke-width="1"/>`;
      s += `<text x="${W - PAD - 4}" y="${PAD + 12}" fill="#6a7486" font-size="10" text-anchor="end">attack →</text>`;
      for (const ph of phases) {
        const b = shp[team][ph.key]; if (!b) continue;
        const x = sx(b.d2g - b.l / 2), y = sy(b.w / 2), w = b.l * scale, h = b.w * scale;
        s += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="3"
          fill="${col}" fill-opacity="${ph.dash ? 0.05 : 0.17}" stroke="${col}" stroke-width="${ph.dash ? 1.5 : 2.2}" ${ph.dash ? 'stroke-dasharray="5 4"' : ""}/>`;
        // label just ABOVE the block top edge (never at centre -> no overlap)
        s += `<text x="${sx(b.d2g).toFixed(1)}" y="${(y - 4).toFixed(1)}" fill="${col}" font-size="11" font-weight="600" text-anchor="middle" class="ishape-dim">${b.w}×${b.l} m</text>`;
      }
      s += `</svg>`;
      return `<div class="ishape-cell"><div class="ishape-team"><span class="iswatch" style="background:${col}"></span>${team}</div>${s}</div>`;
    }
    shapeEl.innerHTML = `<div class="ishape-grid">${teams.map(pitch).join("")}</div>
      <div class="legend">
        <span><span class="iswatch solid"></span>solid = build-up shape</span>
        <span><span class="iswatch dash"></span>dashed = final-third shape</span>
        <span class="ileg-sep">·</span><span>each block = width × length the team occupies, in metres</span>
      </div>`;
  }

  /* ---- live 2026 EFI: offers to receive IN BEHIND, per match ---- */
  if (efiEl) {
    const rows = (d.efi_2026.offers_in_behind || []).slice(0, 8);
    const mx = Math.max(1, ...rows.map((r) => r.per_match));
    const bars = rows.map((r) => {
      const nm = (typeof r.team === "string" && r.team.length === 3) ? codeName(r.team) : r.team;
      const w = clamp(r.per_match / mx * 100, 3, 100);
      return `<div class="tbrow">
        <span class="tbname">${nm} <span class="lteam">${r.team}</span></span>
        <span class="tbtrack"><span class="tbfill" style="width:${w.toFixed(1)}%;background:${teamColor(nm)}"></span></span>
        <span class="tbval">${r.per_match.toFixed(0)}/match</span></div>`;
    }).join("");
    efiEl.innerHTML = `<div class="tbars">${bars}</div>`;
  }
}

/* =================================================================
   ACT 0 — xT reference (static heatmap, its own story)
   ================================================================= */
async function buildXT() {
  const el = $("#xt-canvas"); if (!el) return;
  try {
    const d = await loadJSON("data/surfaces/xt_reference.json");
    const W = 640, H = Math.round(640 * 68 / 105);
    el.innerHTML = `<div class="hstage"><canvas width="${W}" height="${H}" id="cv-xt"></canvas></div>`;
    const ctx = $("#cv-xt").getContext("2d");
    paintSurface(ctx, d.surface_norm, W, H, { ramp: rampHot, gamma: 0.85, threshold: 0, felt: "#0b160f", felt2: "#0b160f" });
    // mark the peak
    let pr = 0, pc = 0, mx = 0;
    d.surface_norm.forEach((row, r) => row.forEach((v, c) => { if (v > mx) { mx = v; pr = r; pc = c; } }));
    const nx = d.grid.nx, ny = d.grid.ny;
    const px = (pc + 0.5) / nx * W, py = (pr + 0.5) / ny * H;
    ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI * 2);
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = "#fff"; ctx.font = "12px sans-serif"; ctx.textAlign = "left";
    ctx.fillText(`peak xT ${d.max_xt.toFixed(3)}`, px + 11, py + 4);
    // goal arrow
    ctx.fillStyle = "rgba(255,255,255,.5)"; ctx.font = "11px sans-serif"; ctx.textAlign = "right";
    ctx.fillText("opponent goal →", W - 8, 16);
  } catch (e) { el.innerHTML = `<p class="caption">xT surface unavailable: ${e.message}</p>`; }
}

// xT-created leaderboards (teams + players by threat added through open-play passing)
async function buildXTcreated() {
  const tEl = $("#xt-teams"), pEl = $("#xt-players");
  if (!tEl && !pEl) return;
  let d;
  try { d = await loadJSON("data/xt_created.json"); } catch (e) { return; }
  const NAMEFIX = {
    "Lionel Andrés Messi Cuccittini": "Lionel Messi",
    "Kylian Mbappé Lottin": "Kylian Mbappé",
    "Pedro González López": "Pedri",
    "Ángel Fabián Di María Hernández": "Ángel Di María",
    "Theo Bernard François Hernández": "Theo Hernández",
  };
  const shortName = (n) => {
    if (NAMEFIX[n]) return NAMEFIX[n];
    const w = n.split(" ");
    return w.length <= 2 ? n : `${w[0]} ${w[w.length - 1]}`;
  };
  const bars = (rows, valOf, labelOf, colOf, fmt) => {
    const mx = Math.max(1e-6, ...rows.map(valOf));
    return rows.map((r) => `<div class="tbrow"><span class="tbname">${labelOf(r)}</span>
      <span class="tbtrack"><span class="tbfill" style="width:${clamp(valOf(r) / mx * 100, 4, 100)}%;background:${colOf(r)}"></span></span>
      <span class="tbval">${fmt(valOf(r))}</span></div>`).join("");
  };
  if (tEl) {
    tEl.innerHTML = bars(d.teams.slice(0, 8), (r) => r.xt_per_match,
      (r) => r.team, (r) => teamColor(r.team), (v) => v.toFixed(2));
  }
  if (pEl) {
    pEl.innerHTML = bars(d.players.slice(0, 10), (r) => r.xt_total,
      (r) => `${shortName(r.name)} <span class="lteam">${r.team}</span>`,
      (r) => teamColor(r.team), (v) => v.toFixed(1));
  }
}

/* =================================================================
   LEADERBOARD
   Renders rank groups (tiers). Tier labels are plain ("clear leader: X" / "the
   chasing group" / "tier N"). No interval whiskers, no per-row estimation badges.
   Hover pins the player onto the surface (if a scrubber exists).
   ================================================================= */
function leaderboard(rows, cfg) {
  // rows already sorted; group by tier key into tiers
  const wrap = document.createElement("div"); wrap.className = "lboard";
  const mx = Math.max(...rows.map((r) => cfg.val(r)));
  const tiers = new Map();
  for (const r of rows) {
    const g = cfg.tier(r);
    if (!tiers.has(g)) tiers.set(g, []);
    tiers.get(g).push(r);
  }
  const order = [...tiers.keys()];
  order.forEach((g, gi) => {
    const members = tiers.get(g);
    const tier = document.createElement("div"); tier.className = "ltier";
    const single = members.length === 1;
    const lab = cfg.tierLabel ? cfg.tierLabel(g, members, gi) :
      (gi === 0 ? `clear leader: ${members[0] ? cfg.name(members[0]) : ""}` : (single ? `tier ${gi + 1}` : "the chasing group"));
    tier.innerHTML = `<div class="ltier-lab">${lab}</div>`;
    for (const r of members) {
      const v = cfg.val(r);
      const row = document.createElement("div"); row.className = "lrow";
      row.dataset.name = cfg.name(r);
      const pctW = clamp(v / mx * 100, 3, 100);
      const note = cfg.note ? cfg.note(r) : "";
      const pos = cfg.pos ? cfg.pos(r) : "";
      row.innerHTML = `
        <span class="lname"><span class="fl" style="background:${teamColor(cfg.team(r))}"></span>${cfg.name(r)}
          <span class="lteam">${cfg.team(r)}</span>${pos ? `<span class="lpos">${pos}</span>` : ""}</span>
        <span class="ltrack"><span class="lfill" style="width:${pctW}%;background:${cfg.barColor || "#6cb4ee"}"></span></span>
        <span class="lval">${cfg.fmt(v)}</span>`;
      if (note) row.innerHTML += `<span class="lnote">${note}</span>`;
      tier.appendChild(row);
    }
    wrap.appendChild(tier);
  });
  // hover pin
  if (cfg.scrubberEl) {
    wrap.addEventListener("mouseover", (e) => {
      const row = e.target.closest(".lrow"); if (!row) return;
      if (cfg.scrubberEl._setHighlight) cfg.scrubberEl._setHighlight(row.dataset.name);
    });
    wrap.addEventListener("mouseleave", () => { if (cfg.scrubberEl._setHighlight) cfg.scrubberEl._setHighlight(null); });
  }
  return wrap;
}

function teamBars(rows, cfg) {
  const wrap = document.createElement("div"); wrap.className = "tbars";
  const vals = rows.map((r) => cfg.val(r));
  const mxv = Math.max(...vals), mnv = Math.min(...vals);
  const range = mxv - mnv;
  // Rescale so the bars actually differentiate: start the floor below the min by a fraction of the
  // data range (never below 0). With a near-flat metric this gives every row a visibly distinct bar.
  let mn = mnv - 0.12 * range;
  if (mnv >= 0) mn = Math.max(0, mn);
  const span = (mxv - mn) || 1;
  for (const r of rows) {
    const v = cfg.val(r);
    const row = document.createElement("div"); row.className = "tbrow";
    const w = clamp((v - mn) / span * 100, 6, 100);
    const tied = cfg.tied && cfg.tied(r);
    row.innerHTML = `<span class="tbname">${cfg.name(r)}${tied ? ` <span class="tieflag">tied</span>` : ""}</span>
      <span class="tbtrack"><span class="tbfill" style="width:${w}%;background:${teamColor(cfg.name(r))}"></span></span>
      <span class="tbval">${cfg.fmt(v)}</span>`;
    wrap.appendChild(row);
  }
  return wrap;
}

/* =================================================================
   TEAM SCATTER (R5)
   Dark-style canvas scatter: points = [{team,x,y}], team-coloured dots + labels,
   a least-squares trend line, labelled axes, and a corner annotation (cfg.annot).
   ================================================================= */
function scatterPlot(host, points, cfg) {
  if (!host || !points || !points.length) return;
  const W = 640, H = 380, PAD_L = 58, PAD_R = 18, PAD_T = 18, PAD_B = 46;
  host.innerHTML = `<div class="hstage"><canvas width="${W}" height="${H}" id="sc-${cfg.id}"></canvas></div>`;
  const ctx = $(`#sc-${cfg.id}`).getContext("2d");
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const xpad = (x1 - x0) * 0.12 || 1, ypad = (y1 - y0) * 0.12 || 1;
  x0 -= xpad; x1 += xpad; y0 -= ypad; y1 += ypad;
  const sx = (x) => PAD_L + (x - x0) / (x1 - x0) * (W - PAD_L - PAD_R);
  const sy = (y) => H - PAD_B - (y - y0) / (y1 - y0) * (H - PAD_T - PAD_B);

  ctx.fillStyle = "#0a0c10"; ctx.fillRect(0, 0, W, H);
  // grid + axes
  ctx.strokeStyle = "rgba(190,210,230,0.10)"; ctx.lineWidth = 1;
  ctx.fillStyle = "#69748699"; ctx.font = "11px Inter, system-ui, sans-serif";
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const yy = PAD_T + i / 4 * (H - PAD_T - PAD_B);
    ctx.beginPath(); ctx.moveTo(PAD_L, yy); ctx.lineTo(W - PAD_R, yy); ctx.stroke();
    const yval = y1 - i / 4 * (y1 - y0);
    ctx.fillText(yval.toFixed(yval >= 10 ? 0 : 1), PAD_L - 6, yy);
  }
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let i = 0; i <= 4; i++) {
    const xx = PAD_L + i / 4 * (W - PAD_L - PAD_R);
    const xval = x0 + i / 4 * (x1 - x0);
    ctx.fillText(xval.toFixed(xval >= 10 ? 0 : (x1 - x0 < 1 ? 2 : 1)), xx, H - PAD_B + 6);
  }
  // axis labels
  ctx.fillStyle = "#9aa6b6"; ctx.font = "600 12px Inter, system-ui, sans-serif";
  ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  ctx.fillText(cfg.xLabel || "x", PAD_L + (W - PAD_L - PAD_R) / 2, H - 6);
  ctx.save();
  ctx.translate(14, PAD_T + (H - PAD_T - PAD_B) / 2); ctx.rotate(-Math.PI / 2);
  ctx.textBaseline = "top"; ctx.fillText(cfg.yLabel || "y", 0, 0);
  ctx.restore();

  // least-squares trend line
  const nP = points.length;
  const mxAvg = xs.reduce((a, b) => a + b, 0) / nP, myAvg = ys.reduce((a, b) => a + b, 0) / nP;
  let num = 0, den = 0;
  for (let i = 0; i < nP; i++) { num += (xs[i] - mxAvg) * (ys[i] - myAvg); den += (xs[i] - mxAvg) ** 2; }
  if (den > 0) {
    const slope = num / den, intercept = myAvg - slope * mxAvg;
    const lx0 = x0, lx1 = x1;
    ctx.strokeStyle = "rgba(124,200,255,0.55)"; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.moveTo(sx(lx0), sy(slope * lx0 + intercept)); ctx.lineTo(sx(lx1), sy(slope * lx1 + intercept)); ctx.stroke();
    ctx.setLineDash([]);
  }
  // points + labels
  ctx.font = "11px Inter, system-ui, sans-serif"; ctx.textBaseline = "middle";
  for (const p of points) {
    const px = sx(p.x), py = sy(p.y), col = teamColor(p.team);
    ctx.beginPath(); ctx.arc(px, py, 5.5, 0, Math.PI * 2);
    ctx.fillStyle = col; ctx.fill();
    ctx.lineWidth = 1.4; ctx.strokeStyle = "#0a0c10"; ctx.stroke();
    ctx.fillStyle = "#cdd6e2"; ctx.textAlign = px > W - 90 ? "right" : "left";
    ctx.fillText(p.team, px > W - 90 ? px - 9 : px + 9, py);
  }
  // corner annotation
  if (cfg.annot) {
    ctx.fillStyle = "#e8edf4"; ctx.font = "600 13px Inter, system-ui, sans-serif";
    ctx.textAlign = "right"; ctx.textBaseline = "top";
    ctx.fillText(cfg.annot, W - PAD_R - 4, PAD_T + 2);
  }
}

function xgPanel(host, rcpt, extra = "") {
  if (!host) return;
  const rho = rcpt.rho;
  const reading = rcpt.reading || "";
  const sign = rho > 0.15 ? "good" : rho < -0.15 ? "warn" : "muted";
  host.innerHTML = `
    <div class="xgrow">
      <div class="xgstat"><div class="xgv ${sign}">ρ = ${rho > 0 ? "+" : ""}${rho}</div><div class="xgl">rank correlation with StatsBomb 2022 xG (per match)</div></div>
    </div>
    <p class="xgunit">${rcpt.unit || rcpt.unit_x || ""}</p>
    <p class="xgread">${reading}</p>${extra}`;
}

/* =================================================================
   ACT BUILDERS
   ================================================================= */
async function buildSMS() {
  const surf = await loadJSON("data/surfaces/sms.json");
  const data = await loadJSON("data/space_sms.json");
  const scEl = $("#sms-canvas");
  buildScrubber(scEl, surf, {
    id: "sms", ramp: rampHot, gamma: 0.6, threshold: 0.05,
    defaultMode: "surface",
    readout: (fr) => {
      const own = fr.in_possession_team === "Argentina";
      return `<b>${fr.in_possession_team}</b> in possession · top off-ball space-holder:
        <b style="color:${teamColor(fr.in_possession_team)}">${fr.top_offball}</b>
        ${own ? "" : `<span class="hint">(non-Argentina frame — surface re-orients to the team in possession)</span>`}`;
    },
  });
  // total-area leaderboard (top 12), tie-grouped by tie_group
  const top = data.players.slice(0, 12);
  const lb = leaderboard(top, {
    name: (r) => r.name, team: (r) => r.team, val: (r) => r.sms_total_area_m2,
    fmt: (v) => `${v.toFixed(0)} m²`,
    tier: (r) => r.tie_group, barColor: "#6cb4ee",
    scrubberEl: scEl,
    tierLabel: (g, m) => g === 1 ? `top group — ${m.length} players close together` : `tier ${g} (${m.length})`,
  });
  $("#sms-board").appendChild(lb);
  // self-made cut (resort) — top 6
  const sm = [...data.players].sort((a, b) => b.sms_self_made_m2 - a.sms_self_made_m2).slice(0, 6);
  const smlb = leaderboard(sm, {
    name: (r) => r.name, team: (r) => r.team, val: (r) => r.sms_self_made_m2,
    fmt: (v) => `${v.toFixed(0)} m²`,
    tier: () => 1, barColor: "#9b8cff", scrubberEl: scEl,
    tierLabel: () => "self-made (movement) cut — Correa, Foyth and Ziyech share the top",
  });
  $("#sms-selfmade").appendChild(smlb);
  // teams
  const tb = teamBars(data.teams.slice(0, 8), {
    name: (r) => r.team, val: (r) => r.sms_team_offball_area_m2, fmt: (v) => `${v.toFixed(0)}`,
  });
  $("#sms-teams").appendChild(tb);
  xgPanel($("#sms-xg"), data.xg_receipt);
}

async function buildCHASE() {
  const surf = await loadJSON("data/surfaces/chase.json");
  const data = await loadJSON("data/space_chase.json");
  const scEl = $("#chase-canvas");
  const heroName = (surf.hero && surf.hero.name) || "the focal attacker";
  buildScrubber(scEl, surf, {
    id: "chase", ramp: rampCool, gamma: 0.6, threshold: 0.0,
    gravityFocus: heroName, labelName: heroName, defaultMode: "surface",
    toggles: [
      { key: "gravity", label: "show gravity spokes" },
    ],
    readout: (fr, st) => st.mode === "gravity"
      ? `Spokes link every defender within 12 m of <b>${heroName}</b> toward him — the deeper the colour, the closer the marker. Watch the violet block (defender control) collapse as he drifts.`
      : `Surface = <b>defender</b> pitch-control (where the block owns space). Bright violet = defence in control. Highlighted: <b>${heroName}</b>.`,
  });
  // name the auto-picked gravity attacker in the card title + caption
  const chTitle = $("#chase-hero-title"); if (chTitle && surf.hero) chTitle.textContent = `${surf.hero.name} (${surf.hero.team})`;
  const top = data.players.slice(0, 12);
  const lb = leaderboard(top, {
    name: (r) => r.name, team: (r) => r.team, pos: (r) => r.position, val: (r) => r.gravity,
    fmt: (v) => v.toFixed(2),
    tier: (r) => r.rank, barColor: "#9b8cff", scrubberEl: scEl,
    note: (r) => `<span class="comp">drawn ${r.drawn_markers.toFixed(2)} · pull ${r.chase_pull_ms.toFixed(2)} m/s</span>`,
    tierLabel: (g, m, gi) => gi === 0 && m.length === 1
      ? `clear leader: Pedro`
      : (m.length > 1 ? `the chasing group` : `tier ${g}`),
  });
  $("#chase-board").appendChild(lb);
  const tb = teamBars(data.teams.slice(0, 8), {
    name: (r) => r.team, val: (r) => r.team_gravity, fmt: (v) => v.toFixed(2),
  });
  $("#chase-teams").appendChild(tb);
  // team-level scatter: x = team gravity, y = team xG-for per match
  const pts = data.teams
    .filter((t) => data.team_xg_for_per_match[t.team] != null)
    .map((t) => ({ team: t.team, x: t.team_gravity, y: data.team_xg_for_per_match[t.team] }));
  scatterPlot($("#chase-scatter"), pts, {
    id: "chase", xLabel: "team defensive gravity", yLabel: "StatsBomb xG / match",
    annot: `ρ=${data.xg_receipt.rho > 0 ? "+" : ""}${data.xg_receipt.rho}`,
  });
  xgPanel($("#chase-xg"), { ...data.xg_receipt,
    reading: "A mild positive link (ρ=+0.38) — suggestive, not proof. The scatter above is the evidence: teams whose attackers exert more defensive gravity tend to generate a little more xG.",
  });
}

async function buildPOBSO() {
  const surf = await loadJSON("data/surfaces/pobso.json");
  const data = await loadJSON("data/space_pobso.json");
  const scEl = $("#pobso-canvas");
  buildScrubber(scEl, surf, {
    id: "pobso", ramp: rampHot, gamma: 0.55, threshold: 0.02,
    labelName: surf.hero.name, defaultMode: "surface",
    toggles: [
      { key: "reveal", label: "reveal danger (× xT)" },
    ],
    readout: (fr, st) => st.mode === "reveal"
      ? `Only the cells off-ball attackers control <b>and</b> that carry threat (× xT) stay lit — the dangerous space forming before the pass exists.`
      : `Dangerous space — control × xT — for <b>${surf.hero.name}</b>'s run: he controls ${surf.hero.obso_owned.toFixed(1)} xT-weighted m² of dangerous space at the peak. The pocket blooms <b>ahead</b> of the run, not at the ball.`,
  });
  // name the auto-picked runner in the card title
  const pbTitle = $("#pobso-hero-title");
  if (pbTitle && surf.hero) pbTitle.textContent = `${surf.hero.name} (${surf.hero.team})`;
  // PLAYER board — substantial-minutes players LEAD; cameo subs (<15 min, ~one match) are
  // shown separately so they don't headline (matches the caption's claim).
  const QUALMIN = 15;
  const players = [...data.players].sort((a, b) => {
    const qa = a.minutes_sampled >= QUALMIN, qb = b.minutes_sampled >= QUALMIN;
    if (qa !== qb) return qa ? -1 : 1;   // qualified first
    return b.pobso - a.pobso;            // then by dangerous-space desc within each tier
  }).slice(0, 14);
  const lb = leaderboard(players, {
    name: (r) => r.name, team: (r) => r.team, pos: (r) => r.position, val: (r) => r.pobso,
    fmt: (v) => `${v.toFixed(1)} m²`,
    tier: (r) => (r.minutes_sampled < 15 ? "cameo" : "full"),
    barColor: "#ff6b6b", scrubberEl: scEl,
    note: (r) => r.minutes_sampled < 15
      ? `<span class="comp warn">${r.minutes_sampled.toFixed(1)} min — single match</span>`
      : `<span class="comp">${r.minutes_sampled.toFixed(0)} min · ${r.n_frames} fr</span>`,
    tierLabel: (g) => g === "cameo"
      ? `cameo subs (&lt;15 min, one match) — shown separately`
      : `substantial-minutes dangerous-space controllers (≥15 min sampled)`,
  });
  $("#pobso-board").appendChild(lb);
  // TEAM flow board — the result that actually tracks chances
  const tb = teamBars(data.teams, {
    name: (r) => r.team, val: (r) => r.danger_moments_per_min, fmt: (v) => v.toFixed(1),
    tied: (r) => r.tied_with_leader,
  });
  $("#pobso-teams").appendChild(tb);
  // team-level scatter: x = danger moments / min, y = StatsBomb xG / match
  const pts = (data.xg_receipt.detail || []).map((d) => ({ team: d.team, x: d.danger_moments_per_min, y: d.sb_xg_per_match }));
  scatterPlot($("#pobso-scatter"), pts, {
    id: "pobso", xLabel: "danger-moments / min", yLabel: "StatsBomb xG / match",
    annot: `ρ=+${data.xg_receipt.rho}`,
  });
  xgPanel($("#pobso-xg"), { ...data.xg_receipt,
    reading: `Owning dangerous space tracks chances (ρ=+${data.xg_receipt.rho}). The scatter above is the payoff — every team that creates more controlled-danger pockets off the ball generates more xG.`,
  });
}

async function buildSAR() {
  const surf = await loadJSON("data/surfaces/sar.json");
  const data = await loadJSON("data/space_sar.json");
  const scEl = $("#sar-canvas");
  buildScrubber(scEl, surf, {
    id: "sar", ramp: rampHot, gamma: 0.6, threshold: 0.04,
    labelName: surf.hero.name, defaultMode: "surface",
    toggles: [
      { key: "replacement", label: "vs replacement (dissolve to baseline)" },
    ],
    readout: (fr, st) => st.mode === "replacement"
      ? `Messi's footprint dissolved toward the flat positional <b>replacement</b> baseline — the bright excess that remains is the space he wins beyond expectation.`
      : `<b>${surf.hero.name}</b>'s off-ball controllable footprint (bright) over the translucent zone-replacement contour. Hero SAR for the sample: <b>+${surf.hero.sar_m2} m²</b>.`,
  });
  const top = data.leaderboard.slice(0, 12);
  const lb = leaderboard(top, {
    name: (r) => r.name, team: (r) => r.team, val: (r) => r.sar_m2,
    fmt: (v) => `+${v.toFixed(0)} m²`,
    tier: (r) => (r.tied_with_leader ? "lead" : "rest"),
    barColor: "#6dd58c", scrubberEl: scEl,
    tierLabel: (g, m) => g === "lead"
      ? `clear leader: ${m[0].name}`
      : `the chasing group`,
  });
  $("#sar-board").appendChild(lb);
  const tb = teamBars(data.teams.slice(0, 11), {
    name: (r) => r.team, val: (r) => r.sar_m2, fmt: (v) => `${v > 0 ? "+" : ""}${v.toFixed(0)}`,
  });
  $("#sar-teams").appendChild(tb);
  xgPanel($("#sar-xg"), data.xg_receipt);
}

/* =================================================================
   CLOSING ACT — live FIFA EFI 2026
   ================================================================= */
// CLOSING — two lenses on the 2022 final (FIFA EFI vs our tracking), then the same metrics live in 2026.
async function buildLive() {
  const lensEl = $("#final-2lens"), liveEl = $("#live-efi");
  if (!lensEl && !liveEl) return;
  const ARG = teamColor("Argentina"), FRA = teamColor("France");

  /* ---- 2022 final: FIFA EFI lens vs our tracking lens ---- */
  if (lensEl) {
    try {
      const f = await loadJSON("data/efi_2022_final.json");
      const pob = await loadJSON("data/space_pobso.json");
      const ks = f.key_stats || {};
      const lb = {}; (f.line_breaks || []).forEach((r) => (lb[r.team] = r));
      const mv = {}; (f.movement_to_receive || []).forEach((r) => (mv[r.team] = r));
      const of = {}; (f.offers_to_receive || []).forEach((r) => (of[r.team] = r));
      const danger = {}; (pob.teams || []).forEach((t) => (danger[t.team] = t.danger_moments_per_min));
      const xg = f.real_xg_statsbomb || {};

      // one metric = two bars (ARG, FRA), normalized to the larger of the pair
      const cmp = (label, a, b, fmt) => {
        const mx = Math.max(a, b, 1);
        const bar = (name, v, col) => `<div class="cmprow"><span class="ck">${name}</span>
          <span class="ctrack"><span class="cfill" style="width:${clamp(v / mx * 100, 4, 100)}%;background:${col}"></span></span>
          <span class="cval">${fmt(v)}</span></div>`;
        const winner = a > b ? "Argentina" : (b > a ? "France" : null);
        return `<div class="cmp"><div class="clab">${label}</div>
          ${bar("ARG", a, ARG)}${bar("FRA", b, FRA)}
          ${winner ? `<div class="cmpwin">▲ ${winner} more</div>` : ""}</div>`;
      };
      const num = (v) => (v == null ? "—" : (Math.round(v * 10) / 10).toString());

      lensEl.innerHTML = `<div class="lens">
        <div class="lcol">
          <h4>FIFA EFI<span class="src">official — read off the 2022 match-report PDF</span></h4>
          ${cmp("Completed line breaks", lb.Argentina?.completed, lb.France?.completed, num)}
          ${cmp("Receptions in the final third", ks["Receptions in the Final Third"]?.home, ks["Receptions in the Final Third"]?.away, num)}
          ${cmp("Movements to receive in behind", mv.Argentina?.in_behind, mv.France?.in_behind, num)}
          ${cmp("Offers to receive (made)", of.Argentina?.made, of.France?.made, num)}
        </div>
        <div class="lcol">
          <h4>Our tracking<span class="src">pitch-control reconstruction from raw PFF tracking</span></h4>
          ${cmp("Dangerous space — danger-moments / min", danger.Argentina, danger.France, num)}
          <div class="lcallout">France's danger was concentrated: <b>Mbappé</b>'s hat-trick, and France's late surges into dangerous space (the kind you scrubbed in <b>Act 2</b>). The team rate favours Argentina; France's biggest moments were a handful of individual runs.</div>
          <div class="lcallout" style="border-left-color:var(--accent2)">Both lenses agree on the shape of the game: <b>Argentina created more, more often</b>, off two completely independent measurement systems.</div>
        </div>
      </div>`;
      // the outcome — real StatsBomb xG (the page's "so what", at match level)
      if (xg.Argentina && xg.France) {
        const a = xg.Argentina, b = xg.France, mx = Math.max(a.xg, b.xg, 1);
        const xbar = (name, v, np, col) => `<div class="cmprow"><span class="ck">${name}</span>
          <span class="ctrack"><span class="cfill" style="width:${clamp(v / mx * 100, 4, 100)}%;background:${col}"></span></span>
          <span class="cval">${v.toFixed(2)}</span></div>
          <div class="cmprow"><span class="ck"></span><span class="cmpsub">open-play (non-penalty) xG: <b>${np.toFixed(2)}</b></span></div>`;
        lensEl.innerHTML += `<div class="card lxg">
          <div class="clab"><b>The outcome — real expected goals</b> <span class="lteam">StatsBomb 2022, penalty shootout excluded</span></div>
          ${xbar("ARG", a.xg, a.npxg, ARG)}${xbar("FRA", b.xg, b.npxg, FRA)}
          <p class="caption">The space dominance showed up on the scoreboard of chances: Argentina out-created France on xG (2.76 vs 2.27) — and in <b>open play it isn't close</b> (1.97 vs 0.71). France's xG was penalty-driven; their open-play danger really did run through Mbappé. Three independent measurements — FIFA's counts, our tracking, StatsBomb's xG — all point the same way.</p>
        </div>`;
      }
    } catch (e) {
      lensEl.innerHTML = `<p class="caption">2022-final EFI comparison unavailable (${e.message}).</p>`;
    }
  }

  /* ---- 2026 live: the same space metrics, straight from FIFA's feed ---- */
  if (liveEl) {
    try {
      const d = await loadJSON("data/intro_efi.json");
      const e26 = d.efi_2026 || {};
      const board = (rows, fmt) => {
        rows = (rows || []).slice(0, 6);
        const mx = Math.max(1, ...rows.map((r) => r.per_match));
        return `<div class="tbars">` + rows.map((r) => {
          const nm = (typeof r.team === "string" && r.team.length === 3) ? codeName(r.team) : r.team;
          return `<div class="tbrow"><span class="tbname">${nm} <span class="lteam">${r.team}</span></span>
            <span class="tbtrack"><span class="tbfill" style="width:${clamp(r.per_match / mx * 100, 4, 100)}%;background:${teamColor(nm)}"></span></span>
            <span class="tbval">${fmt(r.per_match)}</span></div>`;
        }).join("") + `</div>`;
      };
      liveEl.innerHTML = `
        <div class="livechip"><span class="dot live"></span> LIVE · ${e26.n_matches_played || "—"} WC2026 matches played · FIFA EFI</div>
        <div class="liveboards">
          <div><h4>Completed line breaks · per match</h4>${board(e26.linebreaks_completed, (v) => v.toFixed(0))}</div>
          <div><h4>Offers to receive in behind · per match</h4>${board(e26.offers_in_behind, (v) => v.toFixed(0))}</div>
        </div>`;
    } catch (e) {
      liveEl.innerHTML = `<p class="caption">Live WC2026 EFI feed unavailable right now (${e.message}). The 2022 lens above stands on its own.</p>`;
    }
  }
}

/* =====================================================================
   HOW-IT'S-CALCULATED EXPLAINER WIDGETS  (inline SVG + light animation)
   Self-contained; each early-returns if its host div is absent.
   ===================================================================== */

/* 1) xT — ball hops midfield -> half-space -> central pocket; threat ticks up. */
function buildXtExplainer() {
  const host = $("#xt-explainer"); if (!host) return;
  // midfield (open grass) -> edge of the box -> right in front of goal (inside the box).
  const stops = [{ x: 80, y: 62, v: 0.02 }, { x: 176, y: 40, v: 0.11 }, { x: 224, y: 52, v: 0.26 }];
  host.innerHTML = `
    <div class="xpl-head">how it's built · <b>xT</b></div>
    <svg class="xpl-svg" viewBox="0 0 240 110" role="img" aria-label="ball moving into higher-value zone">
      <rect x="4" y="4" width="232" height="102" rx="6" fill="#0b160f" stroke="#2a313d"/>
      <defs>
        <radialGradient id="xtPocket" cx="95%" cy="50%" r="40%">
          <stop offset="0%" stop-color="#ff6b6b" stop-opacity=".55"/>
          <stop offset="45%" stop-color="#f0b429" stop-opacity=".30"/>
          <stop offset="100%" stop-color="#1a8c8c" stop-opacity="0"/>
        </radialGradient>
      </defs>
      <rect x="4" y="4" width="232" height="102" rx="6" fill="url(#xtPocket)"/>
      <line x1="120" y1="4" x2="120" y2="106" stroke="#bcd2e6" stroke-opacity=".18"/>
      <rect x="200" y="28" width="36" height="54" fill="none" stroke="#bcd2e6" stroke-opacity=".22"/>
      ${stops.map(s => `<circle cx="${s.x}" cy="${s.y}" r="2.4" fill="#9aa6b6" fill-opacity=".5"/>`).join("")}
      <circle id="xtBall" cx="${stops[0].x}" cy="${stops[0].y}" r="4.5" fill="#fff" stroke="#000" stroke-width="1"/>
      <text x="226" y="16" text-anchor="end" font-size="8" fill="#9aa6b6">goal →</text>
    </svg>
    <div class="xpl-num">threat <span id="xtVal">0.02</span></div>
    <p class="xpl-cap">The ball climbs from midfield, to the edge of the box, to <b>right in front of goal</b> — same move, far more <b>threat</b>, because the zone is worth more. xT peaks at the goal.</p>`;
  const valEl = $("#xtVal", host);
  const T = 3600, seg = T / 3;
  let raf;
  const tick = (now) => {
    const i = Math.floor((now % T) / seg);
    const v = stops[clamp(i, 0, 2)].v;
    valEl.textContent = v.toFixed(2);
    valEl.style.color = v > 0.2 ? "var(--hot)" : v > 0.05 ? "var(--warn)" : "var(--muted)";
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  host._stop = () => cancelAnimationFrame(raf);
}

/* 2) CHASE — attacker dot with ~12m dashed radius; 3 defenders pulled inward. */
function buildChaseExplainer() {
  const host = $("#chase-explainer"); if (!host) return;
  const cx = 120, cy = 55;
  const defs = [{ x: 64, y: 30 }, { x: 188, y: 44 }, { x: 96, y: 92 }];
  host.innerHTML = `
    <div class="xpl-head">how it's built · <b>gravity</b></div>
    <svg class="xpl-svg" viewBox="0 0 240 110" role="img" aria-label="defenders pulled toward an attacker">
      <rect x="4" y="4" width="232" height="102" rx="6" fill="#0b0f14" stroke="#2a313d"/>
      <circle cx="${cx}" cy="${cy}" r="44" fill="#ff6b6b" fill-opacity=".05"
              stroke="#ff6b6b" stroke-opacity=".5" stroke-dasharray="5 4"/>
      <text x="${cx}" y="${cy - 47}" text-anchor="middle" font-size="8" fill="#ff6b6b" fill-opacity=".8">~12 m</text>
      ${defs.map((d, i) => `
        <line class="chase-arrow" style="animation-delay:${i * 0.4}s"
              x1="${d.x}" y1="${d.y}" x2="${cx}" y2="${cy}"
              stroke="#ff9a3a" stroke-width="2" marker-end="url(#chaseHead)"/>`).join("")}
      <defs>
        <marker id="chaseHead" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#ff9a3a"/>
        </marker>
      </defs>
      ${defs.map(d => `<circle cx="${d.x}" cy="${d.y}" r="5" fill="#ff9a9a" stroke="#0b0f14"/>`).join("")}
      <circle cx="${cx}" cy="${cy}" r="6" fill="#7ec8ff" stroke="#0b0f14" stroke-width="1.2"/>
    </svg>
    <p class="xpl-cap"><b>Gravity</b> = how many defenders you pull within ~12 m (<b>drawn</b>) × how hard they close on you (<b>chase-pull</b> m/s). Target men pin markers; roamers like Messi score lower.</p>`;
}

/* 3) DANGEROUS — control blob × xT gradient -> a bright danger pocket. */
function buildDangerExplainer() {
  const host = $("#pobso-explainer"); if (!host) return;
  host.innerHTML = `
    <div class="xpl-head">how it's built · <b>Dangerous Space</b></div>
    <svg class="xpl-svg xpl-mult" viewBox="0 0 300 96" role="img" aria-label="control times value equals dangerous space">
      <defs>
        <radialGradient id="ctrlBlob" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#9b8cff" stop-opacity=".85"/>
          <stop offset="70%" stop-color="#5848c0" stop-opacity=".25"/>
          <stop offset="100%" stop-color="#5848c0" stop-opacity="0"/>
        </radialGradient>
        <linearGradient id="xtGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#1a8c8c" stop-opacity=".1"/>
          <stop offset="60%" stop-color="#f0b429" stop-opacity=".5"/>
          <stop offset="100%" stop-color="#ff6b6b" stop-opacity=".85"/>
        </linearGradient>
        <radialGradient id="dangerPocket" cx="62%" cy="44%" r="42%">
          <stop offset="0%" stop-color="#ff6b6b" stop-opacity="1"/>
          <stop offset="55%" stop-color="#ff9a3a" stop-opacity=".55"/>
          <stop offset="100%" stop-color="#ff9a3a" stop-opacity="0"/>
        </radialGradient>
      </defs>
      <g><rect x="6" y="14" width="72" height="58" rx="6" fill="#0e1014" stroke="#2a313d"/>
         <ellipse cx="42" cy="43" rx="26" ry="20" fill="url(#ctrlBlob)"/>
         <text x="42" y="86" text-anchor="middle" font-size="9" fill="#9aa6b6">control</text></g>
      <text x="100" y="48" text-anchor="middle" font-size="20" fill="#e8edf4">×</text>
      <g><rect x="120" y="14" width="72" height="58" rx="6" fill="#0e1014" stroke="#2a313d"/>
         <rect x="122" y="16" width="68" height="54" rx="5" fill="url(#xtGrad)"/>
         <text x="156" y="86" text-anchor="middle" font-size="9" fill="#9aa6b6">value (xT)</text></g>
      <text x="214" y="48" text-anchor="middle" font-size="18" fill="#e8edf4">=</text>
      <g><rect x="234" y="14" width="60" height="58" rx="6" fill="#0e1014" stroke="#2a313d"/>
         <circle id="dangerBloom" cx="264" cy="40" r="20" fill="url(#dangerPocket)"/>
         <text x="264" y="86" text-anchor="middle" font-size="9" fill="#ff6b6b">danger pocket</text></g>
    </svg>
    <p class="xpl-cap"><b>pitch control × xT = dangerous space.</b> Control over low-value grass = nothing; control over the danger pocket = everything.</p>`;
}

/* ---------------- WIP export ----------------
   space-wip.html (the parked archive) imports this module and drives the two
   stashed builders explicitly. Expose them on window so that page can call
   them after the module loads. */
window.__spaceWIP = { buildSMS, buildSAR, buildCHASE, buildPOBSO, buildXT, buildIntro, buildLive };

/* ---------------- boot ----------------
   Full narrative auto-boot. Skipped on the WIP archive page (which sets
   window.__spaceWIPPage before loading this module) so SMS/SAR are built once,
   on demand, against the archive's own host IDs — not twice. */
if (!window.__spaceWIPPage) {
  (async function () {
    initReveal();
    await buildIntro();
    await buildXT();
    buildXtExplainer();
    buildXTcreated();
    await Promise.allSettled([buildCHASE(), buildPOBSO()]);
    buildChaseExplainer();
    buildDangerExplainer();
    await buildLive();
  })();
}
