// space.js — "Space — Soccer's Dark Matter" (rebuild).
// Act 0: xT reference heatmap (where the danger lives — Singh model, its own story).
// Acts 1-4: SMS, CHASE, P-OBSO, SAR — each a LIVE scrubbable canvas heatmap (pitch underneath,
//   per-cell color), a tie-aware leaderboard (no false #1), and an xG-receipt "so what" panel.
// Closing: live FIFA EFI 2026 (threat/xG leaders) + the space-not-distance note.
//
// Honesty contract:
//   - boards render tie groups; a player is only a clean #1 when its CI clears every rival's.
//   - occlusion-flagged players carry a visible badge.
//   - xT is its own story; it meets space only at the P-OBSO bridge.
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

/* ---------------- confidence rail ---------------- */
function initRail() {
  const fill = $("#rail-fill"), pctEl = $("#rail-pct");
  if (!fill) return;
  const states = {
    xt:    { v: 1.0,  t: "model — xT reference" },
    sms:   { v: 0.637, t: "64% off-ball filmed" },
    chase: { v: 0.591, t: "59% filmed · 10 matches" },
    pobso: { v: 0.613, t: "61% filmed · the bridge" },
    sar:   { v: 0.612, t: "61% filmed · openness" },
    live:  { v: 0.95, t: "live · FIFA EFI 2026" },
  };
  const io = new IntersectionObserver((es) => {
    for (const e of es) if (e.isIntersecting) {
      const s = states[e.target.id]; if (!s) continue;
      fill.style.height = `${(s.v * 100).toFixed(0)}%`;
      pctEl.textContent = s.t;
    }
  }, { threshold: 0.4 });
  Object.keys(states).forEach((id) => { const el = $("#" + id); if (el) io.observe(el); });
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
// opts: ramp(fn), gamma(contrast), threshold(only cells>thr lit), alpha(max cell alpha)
function paintSurface(ctx, surface, W, H, opts = {}) {
  const ramp = opts.ramp || rampHot;
  const gamma = opts.gamma ?? 0.75;
  const thr = opts.threshold ?? 0;
  const aMax = opts.alpha ?? 0.92;
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
      img.data[i + 3] = Math.round(255 * aMax * clamp(t * 1.15, 0, 1));
    }
  }
  octx.putImageData(img, 0, 0);
  ctx.clearRect(0, 0, W, H);
  // base felt
  ctx.fillStyle = "#0b160f"; ctx.fillRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  // NOTE: source surface row 0 = top of pitch already in screen orientation (ny rows top->bottom),
  // and column 0 = -x (left). Source orientation is attacking +x to the right, so no flip needed.
  ctx.drawImage(off, 0, 0, nx, ny, 0, 0, W, H);
  drawPitchLines(ctx, W, H);
}

function drawBall(ctx, ball, W, H) {
  if (!ball) return;
  const [bx, by] = m2px(ball[0], ball[1], W, H);
  ctx.beginPath(); ctx.arc(bx, by, Math.max(3, W / 220), 0, Math.PI * 2);
  ctx.fillStyle = "#fff"; ctx.strokeStyle = "#000"; ctx.lineWidth = 1;
  ctx.fill(); ctx.stroke();
}

// players: [{x,y,att,gk,name,est|vis}]; opts.dimEstimated toggles occlusion dimming;
// opts.highlightName pins one (others greyed); opts.spokesFrom draws gravity spokes (CHASE)
function drawPlayers(ctx, players, ball, W, H, opts = {}) {
  if (!players) return;
  const r = Math.max(4, W / 150);
  for (const p of players) {
    const est = p.est === true || p.vis === "ESTIMATED";
    const [px, py] = m2px(p.x, p.y, W, H);
    let alpha = 1;
    if (opts.dimEstimated && est) alpha = 0.35;
    if (opts.highlightName && p.name !== opts.highlightName) alpha *= 0.3;
    const col = p.att ? (opts.attColor || "#6cb4ee") : (opts.defColor || "#ff9a9a");
    ctx.globalAlpha = alpha;
    ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2);
    ctx.fillStyle = p.gk ? "#6dd58c" : col;
    ctx.fill();
    ctx.lineWidth = 1.2; ctx.strokeStyle = est ? "#ffd27a" : "#0b0f14";
    if (est) ctx.setLineDash([2, 1.5]);
    ctx.stroke(); ctx.setLineDash([]);
    if (opts.highlightName && p.name === opts.highlightName) {
      ctx.globalAlpha = 1;
      ctx.beginPath(); ctx.arc(px, py, r + 3, 0, Math.PI * 2);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.6; ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;
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
function buildScrubber(el, surf, cfg) {
  const frames = surf.frames;
  const n = frames.length;
  const W = 640, H = Math.round(640 * 68 / 105);
  el.innerHTML = `
    <div class="hstage"><canvas width="${W}" height="${H}" id="cv-${cfg.id}"></canvas></div>
    <div class="hctrls">
      <button class="play" id="pl-${cfg.id}" aria-label="play">&#9654;</button>
      <input type="range" id="rg-${cfg.id}" min="0" max="${n - 1}" value="0" />
      <span class="tlabel" id="tl-${cfg.id}"></span>
    </div>
    <div class="htoggles" id="tg-${cfg.id}"></div>
    <div class="hreadout" id="ro-${cfg.id}"></div>`;
  const cv = $(`#cv-${cfg.id}`), rg = $(`#rg-${cfg.id}`), pl = $(`#pl-${cfg.id}`),
        tl = $(`#tl-${cfg.id}`), ro = $(`#ro-${cfg.id}`), tgEl = $(`#tg-${cfg.id}`);
  const ctx = cv.getContext("2d");

  // toggle state
  const state = { dimEstimated: false, highlight: null, mode: cfg.defaultMode || "surface" };

  // build toggle buttons
  const toggles = cfg.toggles || [];
  tgEl.innerHTML = toggles.map((t) => `<button class="htog" data-k="${t.key}">${t.label}</button>`).join("");
  $$(".htog", tgEl).forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.k;
    if (k === "occlusion") { state.dimEstimated = !state.dimEstimated; b.classList.toggle("on", state.dimEstimated); }
    else { state.mode = state.mode === k ? (cfg.defaultMode || "surface") : k;
           $$(".htog", tgEl).forEach((x) => { if (x.dataset.k !== "occlusion") x.classList.toggle("on", x.dataset.k === state.mode); }); }
    show(+rg.value);
  }));

  function frameSurface(fr) {
    // P-OBSO 'reveal danger' mode: multiply surface by xt_reference to keep only dangerous cells
    if (cfg.id === "pobso" && state.mode === "reveal" && surf.xt_reference) {
      const xt = surf.xt_reference, out = fr.surface.map((row, r) => row.map((v, c) => v * (xt[r] ? xt[r][c] : 0)));
      // renormalize for visibility
      let mx = 0; out.forEach((row) => row.forEach((v) => { if (v > mx) mx = v; }));
      if (mx > 0) for (let r = 0; r < out.length; r++) for (let c = 0; c < out[r].length; c++) out[r][c] /= mx;
      return out;
    }
    // SMS / SAR 'self-made / vs replacement' mode: subtract the baseline contour from the bright surface
    if (cfg.id === "sar" && state.mode === "replacement" && surf.baseline_overlay) {
      const bl = surf.baseline_overlay;
      return fr.surface.map((row, r) => row.map((v, c) => clamp(v - 0.55 * (bl[r] ? bl[r][c] : 0), 0, 1)));
    }
    return fr.surface;
  }

  function show(i) {
    i = clamp(i, 0, n - 1);
    rg.value = i;
    const fr = frames[i];
    const ramp = cfg.ramp || rampHot;
    paintSurface(ctx, frameSurface(fr), W, H, { ramp, gamma: cfg.gamma ?? 0.7, threshold: cfg.threshold ?? 0.04 });
    // SAR baseline contour underneath when not in replacement mode
    if (cfg.id === "sar" && surf.baseline_overlay && state.mode !== "replacement") {
      // faint translucent baseline as a second pass
      paintSurface._noop;
    }
    drawBall(ctx, fr.ball_xy, W, H);
    if (fr.players) {
      const opts = { dimEstimated: state.dimEstimated, highlightName: state.highlight,
                     attColor: "#7ec8ff", defColor: "#ff9a9a" };
      if (cfg.id === "chase" && state.mode === "gravity") drawGravitySpokes(ctx, fr.players, cfg.gravityFocus, W, H);
      drawPlayers(ctx, fr.players, fr.ball_xy, W, H, opts);
    } else if (fr.hero_xy) {
      // SAR / SMS hero dot
      const [hx, hy] = m2px(fr.hero_xy[0], fr.hero_xy[1], W, H);
      ctx.beginPath(); ctx.arc(hx, hy, Math.max(5, W / 120), 0, Math.PI * 2);
      ctx.fillStyle = "#fff"; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = "#6cb4ee"; ctx.stroke();
    }
    tl.textContent = `${i + 1}/${n} · ${(fr.t_s).toFixed(1)}s`;
    ro.innerHTML = cfg.readout ? cfg.readout(fr, state) : "";
  }

  let timer = null, playing = false;
  function stop() { playing = false; pl.innerHTML = "&#9654;"; if (timer) { clearInterval(timer); timer = null; } }
  function play() {
    if (playing) return stop();
    playing = true; pl.innerHTML = "&#10074;&#10074;";
    timer = setInterval(() => { let i = +rg.value + 1; if (i >= n) i = 0; show(i); }, 130);
  }
  pl.addEventListener("click", play);
  rg.addEventListener("input", () => { stop(); show(+rg.value); });
  // expose highlight setter so leaderboard hover can pin a player onto the surface
  el._setHighlight = (name) => { state.highlight = name; show(+rg.value); };
  show(0);
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
    paintSurface(ctx, d.surface_norm, W, H, { ramp: rampHot, gamma: 0.85, threshold: 0 });
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

/* =================================================================
   TIE-AWARE LEADERBOARD
   Renders rank groups; rows whose CI overlaps the group leader share a tier.
   Bars carry CI whiskers; occlusion-flagged rows carry a badge.
   Hover pins the player onto the surface (if a scrubber exists for this act).
   ================================================================= */
function leaderboard(rows, cfg) {
  // rows already sorted; group by `tieKey` (rank or tie_group) into tiers
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
      (single ? (gi === 0 ? "clean leader — CI clears all rivals" : `rank ${gi + 1}`) : `${members.length}-way tie (CIs overlap) — no single #1`);
    tier.innerHTML = `<div class="ltier-lab">${lab}</div>`;
    for (const r of members) {
      const v = cfg.val(r), ci = cfg.ci ? cfg.ci(r) : null;
      const row = document.createElement("div"); row.className = "lrow";
      row.dataset.name = cfg.name(r);
      const pctW = clamp(v / mx * 100, 3, 100);
      const occ = cfg.occ && cfg.occ(r);
      const note = cfg.note ? cfg.note(r) : "";
      let ciHtml = "";
      if (ci) {
        const lo = clamp(ci[0] / mx * 100, 0, 100), hi = clamp(ci[1] / mx * 100, 0, 100);
        ciHtml = `<span class="ci" style="left:${lo}%;width:${Math.max(1, hi - lo)}%"></span>`;
      }
      row.innerHTML = `
        <span class="lname"><span class="fl" style="background:${teamColor(cfg.team(r))}"></span>${cfg.name(r)}
          <span class="lteam">${cfg.team(r)}</span>${occ ? `<span class="occ" title="majority ESTIMATED positions — occlusion-inflated">est</span>` : ""}</span>
        <span class="ltrack"><span class="lfill" style="width:${pctW}%;background:${cfg.barColor || "#6cb4ee"}"></span>${ciHtml}</span>
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
  const mn = Math.min(0, ...vals), mx = Math.max(...vals);
  const span = mx - mn || 1;
  for (const r of rows) {
    const v = cfg.val(r);
    const row = document.createElement("div"); row.className = "tbrow";
    const w = clamp((v - mn) / span * 100, 2, 100);
    const tied = cfg.tied && cfg.tied(r);
    row.innerHTML = `<span class="tbname">${cfg.name(r)}${tied ? ` <span class="tieflag">tied</span>` : ""}</span>
      <span class="tbtrack"><span class="tbfill" style="width:${w}%;background:${teamColor(cfg.name(r))}"></span></span>
      <span class="tbval">${cfg.fmt(v)}</span>`;
    wrap.appendChild(row);
  }
  return wrap;
}

function xgPanel(host, rcpt, extra = "") {
  if (!host) return;
  const rho = rcpt.rho, ci = typeof rcpt.ci === "string" ? rcpt.ci : (rcpt.ci95 ? `[${rcpt.ci95[0]}, ${rcpt.ci95[1]}]` : "");
  const sig = rcpt.p_value != null ? ` · p=${rcpt.p_value}` : "";
  const reading = rcpt.reading || "";
  const sign = rho > 0.15 ? "good" : rho < -0.15 ? "warn" : "muted";
  host.innerHTML = `
    <div class="xgrow">
      <div class="xgstat"><div class="xgv ${sign}">ρ = ${rho > 0 ? "+" : ""}${rho}</div><div class="xgl">Spearman vs StatsBomb 2022 xG</div></div>
      <div class="xgstat"><div class="xgv">${ci}${sig}</div><div class="xgl">95% bootstrap CI · n=${rcpt.n} teams</div></div>
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
    id: "sms", ramp: rampHot, gamma: 0.7, threshold: 0.05,
    defaultMode: "surface",
    toggles: [
      { key: "occlusion", label: "occlusion: grey ESTIMATED" },
    ],
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
    ci: (r) => r.sms_total_ci, fmt: (v) => `${v.toFixed(0)} m²`,
    tier: (r) => r.tie_group, occ: (r) => r.occlusion_flag, barColor: "#6cb4ee",
    scrubberEl: scEl,
    tierLabel: (g, m) => g === 1 ? `tie tier 1 — ${m.length} players, CIs overlap (no single #1)` : `tier ${g} (${m.length})`,
  });
  $("#sms-board").appendChild(lb);
  // self-made cut (resort) — top 6, all one tie-flagged tier (CIs broad/overlapping)
  const sm = [...data.players].sort((a, b) => b.sms_self_made_m2 - a.sms_self_made_m2).slice(0, 6);
  const smlb = leaderboard(sm, {
    name: (r) => r.name, team: (r) => r.team, val: (r) => r.sms_self_made_m2,
    ci: (r) => r.sms_self_made_ci, fmt: (v) => `${v.toFixed(0)} m²`,
    tier: () => 1, occ: (r) => r.occlusion_flag, barColor: "#9b8cff", scrubberEl: scEl,
    tierLabel: () => "self-made (movement) cut — CIs broadly overlap; Correa/Foyth/Ziyech share the top, not a clean #1",
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
  buildScrubber(scEl, surf, {
    id: "chase", ramp: rampCool, gamma: 0.9, threshold: 0.0,
    gravityFocus: "Lionel Messi", defaultMode: "surface",
    toggles: [
      { key: "gravity", label: "show gravity spokes" },
      { key: "occlusion", label: "occlusion: grey ESTIMATED" },
    ],
    readout: (fr, st) => st.mode === "gravity"
      ? `Spokes link every defender within 12 m of <b>Messi</b> toward him — the deeper the colour, the closer the marker. Watch the violet block (defender control) collapse as he drifts.`
      : `Surface = <b>defender</b> pitch-control (where the block owns space). Bright violet = defence in control.`,
  });
  const top = data.players.slice(0, 12);
  const lb = leaderboard(top, {
    name: (r) => r.name, team: (r) => r.team, val: (r) => r.gravity,
    ci: (r) => r.gravity_ci90, fmt: (v) => v.toFixed(2),
    tier: (r) => r.rank, occ: (r) => r.occlusion_flag, barColor: "#9b8cff", scrubberEl: scEl,
    note: (r) => `<span class="comp">drawn ${r.drawn_markers.toFixed(2)} · pull ${r.chase_pull_ms.toFixed(2)} m/s</span>`,
    tierLabel: (g, m, gi) => gi === 0 && m.length === 1
      ? `clean #1 — CI clears the field (Pedro)`
      : `rank ${g} — ${m.length > 1 ? `${m.length}-way tier (CIs overlap)` : "single"}`,
  });
  $("#chase-board").appendChild(lb);
  const tb = teamBars(data.teams.slice(0, 8), {
    name: (r) => r.team, val: (r) => r.team_gravity, fmt: (v) => v.toFixed(2),
  });
  $("#chase-teams").appendChild(tb);
  xgPanel($("#chase-xg"), data.xg_receipt);
}

async function buildPOBSO() {
  const surf = await loadJSON("data/surfaces/pobso.json");
  const data = await loadJSON("data/space_pobso.json");
  const scEl = $("#pobso-canvas");
  buildScrubber(scEl, surf, {
    id: "pobso", ramp: rampHot, gamma: 0.7, threshold: 0.04,
    defaultMode: "surface",
    toggles: [
      { key: "reveal", label: "reveal danger (× xT)" },
      { key: "occlusion", label: "occlusion: grey ESTIMATED" },
    ],
    readout: (fr, st) => st.mode === "reveal"
      ? `Only the cells off-ball attackers control <b>and</b> that carry threat (× xT) stay lit — the scoring opportunity forming before the pass exists.`
      : `Control × xT for <b>${surf.hero.name}</b>'s run (${surf.hero.obso_owned.toFixed(1)} xT-weighted m² at ${surf.hero.speed_mps} m/s). The danger pocket blooms <b>ahead</b> of the run, not at the ball.`,
  });
  // PLAYER board — substantial-minutes players LEAD; cameo-subs (<15 min, ~one match) are
  // demoted to the flagged small-sample tier so they never headline (matches the caption's claim).
  const QUALMIN = 15;
  const players = [...data.players].sort((a, b) => {
    const qa = a.minutes_sampled >= QUALMIN, qb = b.minutes_sampled >= QUALMIN;
    if (qa !== qb) return qa ? -1 : 1;   // qualified first
    return b.pobso - a.pobso;            // then by P-OBSO desc within each tier
  }).slice(0, 14);
  const lb = leaderboard(players, {
    name: (r) => r.name, team: (r) => r.team, val: (r) => r.pobso,
    ci: (r) => r.ci, fmt: (v) => `${v.toFixed(1)} m²`,
    tier: (r) => (r.minutes_sampled < 15 ? "cameo" : "full"),
    occ: (r) => r.occlusion_flag, barColor: "#ff6b6b", scrubberEl: scEl,
    note: (r) => r.minutes_sampled < 15
      ? `<span class="comp warn">${r.minutes_sampled.toFixed(1)} min — single-match basis</span>`
      : `<span class="comp">${r.minutes_sampled.toFixed(0)} min · ${r.n_frames} fr</span>`,
    tierLabel: (g, m) => g === "cameo"
      ? `small-sample / cameo-sub basis (&lt;15 min) — high-variance, read with caution`
      : `substantial-minutes off-ball danger controllers (≥15 min sampled)`,
  });
  $("#pobso-board").appendChild(lb);
  // TEAM flow board — the result that actually tracks xG
  const tb = teamBars(data.teams, {
    name: (r) => r.team, val: (r) => r.danger_moments_per_min, fmt: (v) => v.toFixed(1),
    tied: (r) => r.tied_with_leader,
  });
  $("#pobso-teams").appendChild(tb);
  xgPanel($("#pobso-xg"), data.xg_receipt,
    `<p class="xgnote"><b>The bug I caught:</b> the naïve all-periods version gives ρ = −0.20 (null) because penalty-shootout xG (~0.78/pen) pollutes knockout xG-for. Restricting StatsBomb xG to regulation (periods 1–2) to match the tracking sample fixes it. The time-<i>average</i> OBSO <i>stock</i> does NOT predict xG (ρ −0.2 to −0.4) — only the <i>flow</i> (danger-moment rate) does, because controlled space is necessary but not sufficient for a shot.</p>`);
}

async function buildSAR() {
  const surf = await loadJSON("data/surfaces/sar.json");
  const data = await loadJSON("data/space_sar.json");
  const scEl = $("#sar-canvas");
  buildScrubber(scEl, surf, {
    id: "sar", ramp: rampHot, gamma: 0.7, threshold: 0.04,
    defaultMode: "surface",
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
    ci: (r) => [r.ci_low, r.ci_high], fmt: (v) => `+${v.toFixed(0)} m²`,
    tier: (r) => (r.tied_with_leader ? "lead" : "rest"),
    occ: (r) => r.est_share > 0.5, barColor: "#6dd58c", scrubberEl: scEl,
    tierLabel: (g, m) => g === "lead"
      ? `leader — CI separates from #2 (clean single leader: ${m[0].name})`
      : `the chasing pack (each below the leader's CI floor)`,
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
async function buildLive() {
  const host = $("#live-body"); if (!host) return;
  try {
    const d = await loadJSON("data/efi_2026.json");
    const teamThreat = d.team_threat_leaders.slice(0, 8);
    const tmx = Math.max(...teamThreat.map((t) => t.threat));
    const distLead = d.team_distance_leaders.slice(0, 8);
    const dmx = Math.max(...distLead.map((t) => t.dist_km));
    const players = d.player_threat_leaders.slice(0, 8);
    const pmx = Math.max(...players.map((p) => p.threat));
    const tRows = (arr, valK, mx, fmt, col) => arr.map((r) => {
      const nm = r.team ? codeName(r.team) : r.player;
      const v = r[valK];
      return `<div class="tbrow"><span class="tbname">${r.team ? codeName(r.team) : r.player}${r.player ? ` <span class="lteam">${codeName(r.team)}</span>` : ""}</span>
        <span class="tbtrack"><span class="tbfill" style="width:${clamp(v / mx * 100, 3, 100)}%;background:${teamColor(codeName(r.team))}"></span></span>
        <span class="tbval">${fmt(v)}</span></div>`;
    }).join("");
    host.innerHTML = `
      <div class="livestat">
        <span class="dot live"></span> LIVE · ${d.n_matches} WC2026 matches played · ${d.n_teams} teams · FIFA EFI
      </div>
      <div class="livegrid">
        <div class="card">
          <h3>Team threat (FIFA EFI, summed)</h3>
          <div class="tbars">${tRows(teamThreat, "threat", tmx, (v) => v.toFixed(1), "")}</div>
          <p class="caption">EFI <span class="mono">threat</span> is FIFA's live off-ball-and-on danger model — the closest public cousin to the P-OBSO bridge above. <b>${codeName(teamThreat[0].team)}</b> lead it early.</p>
        </div>
        <div class="card">
          <h3>Player threat leaders</h3>
          <div class="tbars">${tRows(players, "threat", pmx, (v) => v.toFixed(1), "")}</div>
        </div>
      </div>
      <div class="card">
        <h3>Space ≠ distance — the 2022 thesis, live in 2026</h3>
        <div class="tbars">${tRows(distLead, "dist_km", dmx, (v) => v.toFixed(0) + " km", "")}</div>
        <p class="caption"><b>${codeName(distLead[0].team)}</b> covers the most ground (${distLead[0].dist_km} km), yet <b>${codeName(teamThreat[0].team)}</b> — the threat leader — sits mid-pack on distance. ${d.space_not_distance}</p>
        <p class="caption faintnote">Source: ${d.source}, fetched ${d.fetched}. 2026 EFI is rich + live (threat, xG); 2022 EFI was physical-only (distance, sprints, top speed), which is why "space" had to be reconstructed from tracking + labels in the acts above.</p>
      </div>`;
  } catch (e) {
    host.innerHTML = `<p class="caption">Live FIFA EFI 2026 feed unavailable right now (${e.message}). The 2022 acts above stand on their own.</p>`;
  }
}

/* ---------------- boot ---------------- */
(async function () {
  initReveal();
  initRail();
  await buildXT();
  await Promise.allSettled([buildSMS(), buildCHASE(), buildPOBSO(), buildSAR()]);
  await buildLive();
})();
