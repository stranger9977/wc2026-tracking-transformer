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
// "2026-06-18" -> "18 Jun 2026" (no Date() parsing — avoids TZ surprises)
const fmtDate = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ""); if (!m) return iso || "";
  const mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][+m[2] - 1];
  return `${+m[3]} ${mon} ${m[1]}`;
};

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
      // linear alpha: a cell's opacity tracks the value it encodes (no decorative lift)
      img.data[i + 3] = Math.round(255 * aMax * t);
    }
  }
  octx.putImageData(img, 0, 0);
  ctx.clearRect(0, 0, W, H);
  // base = a dim, uniform PITCH GREEN (not near-black) so areas the team doesn't
  // control read as neutral grass, never a scary growing "dark void". Danger then
  // glows brighter than the grass instead of holes opening in black.
  // flat dark base: areas the team doesn't control read as neutral low-value grass.
  // (Source row 0 = top of pitch, col 0 = -x/left; attacking +x to the right, no flip.)
  ctx.fillStyle = opts.felt || "#101a14"; ctx.fillRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  ctx.drawImage(off, 0, 0, nx, ny, 0, 0, W, H);
  drawPitchLines(ctx, W, H);
}

// label the two goal ends so it's obvious which way the attacking team is going.
// Surfaces are locked so the attacking team always attacks +x (toward the RIGHT goal).
function drawGoalLabels(ctx, W, H, teams) {
  if (!teams || (!teams.attack && !teams.defend)) return;
  ctx.save();
  ctx.font = "700 12px Inter, system-ui, sans-serif";
  ctx.textBaseline = "middle";
  const chip = (txt, cx, cy, align) => {
    const tw = ctx.measureText(txt).width;
    const x = align === "left" ? cx + 6 : align === "right" ? cx - tw : cx - tw / 2;
    ctx.lineWidth = 3; ctx.strokeStyle = "rgba(8,10,14,0.7)";
    ctx.fillStyle = "#cdd6e2"; ctx.textAlign = "left";
    ctx.strokeText(txt, x, cy); ctx.fillText(txt, x, cy);
  };
  // own goal (left) and target goal (right); the byline labels carry the direction,
  // so the central "attacking ->" chip (which overlapped players) is dropped.
  if (teams.attack) chip(`◂ ${teams.attack}'s goal`, 6, H / 2, "left");
  if (teams.defend) chip(`${teams.defend}'s goal ▸`, W - 6, H / 2, "right");
  ctx.restore();
}

function drawBall(ctx, ball, W, H, opts = {}) {
  if (!ball) return;
  const [bx, by] = m2px(ball[0], ball[1], W, H);
  if (opts.emphasize) {
    // a dashed "contest" ring (~3 m) so the 50-50 zone is explicit, plus a glow
    ctx.save();
    ctx.beginPath(); ctx.arc(bx, by, (3 / 105) * W, 0, Math.PI * 2);
    ctx.setLineDash([4, 3]); ctx.strokeStyle = "rgba(255,255,255,0.6)"; ctx.lineWidth = 1.4;
    ctx.stroke(); ctx.setLineDash([]);
    ctx.shadowColor = "#fff"; ctx.shadowBlur = W / 36;
    ctx.beginPath(); ctx.arc(bx, by, Math.max(5, W / 150), 0, Math.PI * 2);
    ctx.fillStyle = "#fff"; ctx.strokeStyle = "#000"; ctx.lineWidth = 1.5;
    ctx.fill(); ctx.stroke();
    ctx.restore();
    return;
  }
  ctx.beginPath(); ctx.arc(bx, by, Math.max(3, W / 220), 0, Math.PI * 2);
  ctx.fillStyle = "#fff"; ctx.strokeStyle = "#000"; ctx.lineWidth = 1;
  ctx.fill(); ctx.stroke();
}

// players: [{x,y,att,gk,name}]; opts.highlightName pins one (kept full-opacity + white ring);
// opts.labelName draws a persistent name pill above the matching player so the key figure is obvious.
function drawPlayers(ctx, players, ball, W, H, opts = {}) {
  if (!players) return;
  const r = Math.max(6, W / 120);           // bigger, clearly-visible dots
  const duo = opts.duo;                      // {winner, loser} → ring + label BOTH contestants
  const ringSet = opts.ringSet;              // pass-receivers get a green/red space-owned ring
  const labels = [];                         // defer labels so they paint on top of every dot
  const tags = [];                           // defer the % control tags so they sit on top
  for (const p of players) {
    const [px, py] = m2px(p.x, p.y, W, H);
    const isHi = opts.highlightName && p.name === opts.highlightName;
    const role = duo ? (p.name === duo.winner ? "win" : p.name === duo.loser ? "lose" : null) : null;
    let alpha = 1;
    if (opts.highlightName && !isHi) alpha = 0.55;  // mild de-emphasis only; all dots stay visible
    if (duo && !role) alpha = 0.5;                  // duel: fade everyone but the two contestants
    const col = p.att ? (opts.attColor || "#7ec8ff") : (opts.defColor || "#ff9a9a");
    ctx.globalAlpha = alpha;
    ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2);
    ctx.fillStyle = p.gk ? "#6dd58c" : col;
    ctx.fill();
    // strong dark outline so dots read against the bright surface
    ctx.lineWidth = Math.max(1.6, W / 320); ctx.strokeStyle = "#0a0c10";
    ctx.stroke();
    // GKs are green for both teams → add a thin team-colored ring so the keeper's side still reads
    if (p.gk) {
      ctx.beginPath(); ctx.arc(px, py, r + 1.6, 0, Math.PI * 2);
      ctx.strokeStyle = col; ctx.lineWidth = Math.max(1.4, W / 360); ctx.stroke();
    }
    if (isHi && !(ringSet && ringSet.has(p.name))) {   // the green/red ring replaces the white one
      ctx.globalAlpha = 1;
      ctx.beginPath(); ctx.arc(px, py, r + 3.5, 0, Math.PI * 2);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke();
    }
    if (role) {                               // duel contestants: bold outcome-colored ring
      ctx.globalAlpha = 1;
      ctx.beginPath(); ctx.arc(px, py, r + 4.5, 0, Math.PI * 2);
      ctx.strokeStyle = role === "win" ? "#ffd23c" : "#ff5d5d";
      ctx.lineWidth = 3; if (role === "lose") ctx.setLineDash([4, 3]);
      ctx.stroke(); ctx.setLineDash([]);
      labels.push({ px, py, role, name: role === "win" ? `${p.name} — won` : p.name,
                    accent: role === "win" ? "#ffd23c" : "#ff8a8a" });
    }
    // pass-receivers: ring colored by whether the player's team owns the grass he's in
    // (attacker control at his cell), with a live "% of his space he controls" tag.
    if (ringSet && ringSet.has(p.name)) {
      const winning = (p.ctrl ?? 0) >= 0.5;
      ctx.globalAlpha = 1;
      ctx.beginPath(); ctx.arc(px, py, r + 4, 0, Math.PI * 2);
      ctx.strokeStyle = winning ? "#5fd38a" : "#ff6b6b"; ctx.lineWidth = 3; ctx.stroke();
      tags.push({ px, py, r, pct: Math.round((p.ctrl ?? 0) * 100), win: winning });
    }
    if (!duo && opts.labelName && p.name === opts.labelName) labels.push({ px, py, name: p.name });
  }
  ctx.globalAlpha = 1;
  // two contestants close together (e.g. a corner duel) → stack the loser pill clear of the winner's
  if (duo && labels.length === 2 && Math.abs(labels[0].px - labels[1].px) < 90
      && Math.abs(labels[0].py - labels[1].py) < 46) {
    const lose = labels.find((l) => l.role === "lose"); if (lose) lose.stack = 1;
  }
  for (const l of labels) drawNamePill(ctx, l.px, l.py, r, l.name, W, H, l.accent, l.stack || 0);
  for (const t of tags) drawCtrlTag(ctx, t.px, t.py, t.r, t.pct, t.win, W, H);
}

// a small filled name pill anchored at a player dot. Stays IN-FRAME: clamps horizontally
// and flips BELOW the dot when there's no room above (edge-of-pitch heroes stay readable).
function drawNamePill(ctx, cx, dotY, r, name, W, H, accent, stack = 0) {
  ctx.save();
  ctx.font = "600 13px Inter, system-ui, sans-serif";
  const tw = ctx.measureText(name).width;
  const w = tw + 14, h = 18, rr = 6, pad = 4;
  // place above by default; flip below if it would clip the top edge
  const below = (dotY - r - 4 - h) < pad;
  // `stack` pushes the pill further AWAY from the dot (down if below, up if above)
  // so two contestants' pills don't paint on top of each other.
  const y = (below ? (dotY + r + 9) : (dotY - r - 4 - h)) + stack * (h + 5) * (below ? 1 : -1);
  const x = clamp(cx - w / 2, pad, Math.max(pad, W - w - pad));
  const ptrX = clamp(cx, x + rr + 2, x + w - rr - 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
  ctx.fillStyle = "rgba(10,12,16,0.88)"; ctx.fill();
  ctx.lineWidth = 1; ctx.strokeStyle = accent || "rgba(255,255,255,0.55)"; ctx.stroke();
  // pointer toward the dot (down if pill is above, up if below)
  ctx.beginPath();
  if (below) { ctx.moveTo(ptrX - 4, y); ctx.lineTo(ptrX + 4, y); ctx.lineTo(ptrX, y - 5); }
  else { ctx.moveTo(ptrX - 4, y + h); ctx.lineTo(ptrX + 4, y + h); ctx.lineTo(ptrX, y + h + 5); }
  ctx.closePath();
  ctx.fillStyle = "rgba(10,12,16,0.88)"; ctx.fill();
  ctx.fillStyle = accent || "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(name, x + w / 2, y + h / 2 + 0.5);
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

// A pass that just happened: dashed arrow origin->receiver that fades over ~1.5s, with the
// xT it ADDED tagged at the midpoint. `passes` is ordered by t_s; ts is the live clock.
function drawPassArrow(ctx, passes, ts, W, H) {
  let p = null;
  for (const q of passes) { if (q.t_s <= ts + 0.05) p = q; else break; }
  if (!p) return;
  const age = ts - p.t_s;
  if (age > 2.8) return;                       // linger so the assist arrow survives to the finish
  const a = clamp(1 - age / 2.8, 0.22, 1);
  const [x0, y0] = m2px(p.x0, p.y0, W, H), [x1, y1] = m2px(p.x1, p.y1, W, H);
  ctx.save();
  ctx.globalAlpha = a;
  ctx.strokeStyle = "#ffe08a"; ctx.lineWidth = 2.4; ctx.setLineDash([6, 4]);
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  ctx.setLineDash([]);
  const ang = Math.atan2(y1 - y0, x1 - x0), hl = 10;
  ctx.beginPath(); ctx.moveTo(x1, y1);
  ctx.lineTo(x1 - hl * Math.cos(ang - 0.42), y1 - hl * Math.sin(ang - 0.42));
  ctx.lineTo(x1 - hl * Math.cos(ang + 0.42), y1 - hl * Math.sin(ang + 0.42));
  ctx.closePath(); ctx.fillStyle = "#ffe08a"; ctx.fill();
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
  const txt = `${p.xt_added >= 0 ? "+" : ""}${p.xt_added.toFixed(2)} xT`;
  ctx.font = "700 12px Inter, system-ui, sans-serif";
  const tw = ctx.measureText(txt).width;
  ctx.fillStyle = "rgba(10,12,16,0.9)"; ctx.fillRect(mx - tw / 2 - 5, my - 9, tw + 10, 17);
  ctx.fillStyle = p.xt_added >= 0 ? "#ffe08a" : "#ff8a8a";
  ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(txt, mx, my);
  ctx.restore();
}

// live xT tag on the ball (Karun Singh grid value of the ball's current spot).
function drawBallXt(ctx, ball, xt, W, H) {
  const [bx, by] = m2px(ball[0], ball[1], W, H);
  const txt = `xT ${xt.toFixed(2)}`;
  ctx.save();
  ctx.font = "700 11px Inter, system-ui, sans-serif";
  const tw = ctx.measureText(txt).width, w = tw + 10, h = 16;
  const x = clamp(bx + 9, 2, W - w - 2), y = clamp(by - h - 7, 2, H - h - 2);
  ctx.fillStyle = "rgba(10,12,16,0.92)"; ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = "rgba(255,255,255,0.32)"; ctx.lineWidth = 1; ctx.strokeRect(x, y, w, h);
  ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(txt, x + w / 2, y + h / 2 + 0.5);
  ctx.restore();
}

// small "% of his space his team controls" tag below a ringed receiver (green=winning, red=losing).
function drawCtrlTag(ctx, cx, dotY, r, pct, win, W, H) {
  ctx.save();
  ctx.font = "700 11px Inter, system-ui, sans-serif";
  const txt = `${pct}%`, tw = ctx.measureText(txt).width, w = tw + 10, h = 15;
  const x = clamp(cx - w / 2, 2, W - w - 2), y = clamp(dotY + r + 3, 2, H - h - 2);
  ctx.fillStyle = win ? "rgba(20,60,38,0.95)" : "rgba(70,20,24,0.95)";
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = win ? "#5fd38a" : "#ff6b6b"; ctx.lineWidth = 1; ctx.strokeRect(x, y, w, h);
  ctx.fillStyle = win ? "#9ff0bf" : "#ffb3b3"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(txt, x + w / 2, y + h / 2 + 0.5);
  ctx.restore();
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
    <div class="hreadout" id="ro-${cfg.id}"></div>
    <div class="hpasses" id="px-${cfg.id}"></div>`;
  const cv = $(`#cv-${cfg.id}`), rg = $(`#rg-${cfg.id}`), pl = $(`#pl-${cfg.id}`),
        tl = $(`#tl-${cfg.id}`), ro = $(`#ro-${cfg.id}`), tgEl = $(`#tg-${cfg.id}`),
        pxEl = $(`#px-${cfg.id}`);
  const ctx = cv.getContext("2d");

  // toggle state
  const state = { highlight: null, mode: cfg.defaultMode || "surface" };

  // receivers ringed green/red; passes laid out as a running ledger of xT added.
  // Only the CURRENT receiver (most-recent pass target) is ringed each frame, so the ring
  // tracks the ball and matches the ledger's timeline (not all receivers for the whole clip).
  const hasReceivers = !!(cfg.receivers && cfg.receivers.length);
  const passes = (cfg.passes && cfg.passes.length) ? cfg.passes.slice().sort((a, b) => a.t_s - b.t_s) : null;
  if (passes && pxEl) {
    pxEl.innerHTML = `<div class="px-head">Passes in the move<span class="px-tot" id="pt-${cfg.id}">+0.00 xT</span></div>`
      + `<ol class="px-list">` + passes.map((p, i) =>
        `<li data-i="${i}"><span class="px-nm">${p.passer ? p.passer + " → " : ""}<b>${p.receiver}</b></span>`
        + (p.control != null ? `<span class="px-ctrl">${Math.round(p.control * 100)}% ctrl</span>` : "")
        + `<span class="px-xt ${p.xt_added >= 0 ? "pos" : "neg"}">${p.xt_added >= 0 ? "+" : ""}${p.xt_added.toFixed(2)} xT</span></li>`
      ).join("") + `</ol>`;
  }

  // build toggle buttons
  const toggles = cfg.toggles || [];
  tgEl.innerHTML = toggles.map((t) => `<button class="htog" data-k="${t.key}">${t.label}</button>`).join("");
  $$(".htog", tgEl).forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.k;
    state.mode = state.mode === k ? (cfg.defaultMode || "surface") : k;
    $$(".htog", tgEl).forEach((x) => x.classList.toggle("on", x.dataset.k === state.mode));
    renderAt(playhead);
  }));

  // total span in seconds — playback advances at ~real time from the frames' t_s timestamps,
  // scaled by cfg.speed (<1 = slow-mo, e.g. for a fast sprint so it's watchable).
  const spanSec = Math.max(0.5, frames[n - 1].t_s - frames[0].t_s);
  const fracPerSec = (n - 1) / spanSec * (cfg.speed || 1);

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
      const c = (p.ctrl != null && q.ctrl != null) ? p.ctrl * (1 - f) + q.ctrl * f : (q.ctrl ?? p.ctrl);
      return { ...p, x: p.x * (1 - f) + q.x * f, y: p.y * (1 - f) + q.y * f, ctrl: c };
    });
  }
  const lerpPt = (a, b, f) => (a && b) ? [a[0] * (1 - f) + b[0] * f, a[1] * (1 - f) + b[1] * f] : (a || b);

  // render at a fractional frame index
  function renderAt(fFloat) {
    fFloat = clamp(fFloat, 0, n - 1);
    const i0 = Math.floor(fFloat), i1 = Math.min(i0 + 1, n - 1), f = fFloat - i0;
    const fr = frames[i0], frNext = frames[i1];
    const ts = fr.t_s * (1 - f) + frNext.t_s * f;
    // ring only the receiver of the most-recent pass (the ball-holder/target right now)
    let activeReceiver = null;
    if (passes && hasReceivers) {
      for (const p of passes) { if (p.t_s <= ts + 0.05) activeReceiver = p.receiver; else break; }
    }
    const frameRingSet = activeReceiver ? new Set([activeReceiver]) : null;
    const ramp = cfg.ramp || rampHot;
    const surface = applyMode(lerpSurface(fr.surface, frNext.surface, f));
    const ball = lerpPt(fr.ball_xy, frNext.ball_xy, f);
    paintSurface(ctx, surface, W, H, { ramp, gamma: cfg.gamma ?? 0.6, threshold: cfg.threshold ?? 0.04,
                                       alpha: cfg.surfaceAlpha });
    // duel: radial focus-dim around the contest so the dominating control field recedes
    // and the 50-50 pops. Drawn AFTER the surface+bloom, BEFORE the players (they stay bright).
    if (cfg.focusBall && ball) {
      const [bx, by] = m2px(ball[0], ball[1], W, H);
      const g = ctx.createRadialGradient(bx, by, W * 0.07, bx, by, W * 0.42);
      g.addColorStop(0, "rgba(8,10,14,0)"); g.addColorStop(1, "rgba(8,10,14,0.64)");
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    }
    if (passes) drawPassArrow(ctx, passes, ts, W, H);
    drawBall(ctx, ball, W, H, { emphasize: cfg.emphasizeBall });
    if (fr.players) {
      const players = lerpPlayers(fr.players, frNext.players, f);
      const opts = { highlightName: cfg.duo ? null : (state.highlight || cfg.labelName),
                     labelName: cfg.labelName, duo: cfg.duo, ringSet: frameRingSet,
                     attColor: "#7ec8ff", defColor: "#ff9a9a" };
      if (cfg.id === "chase" && state.mode === "gravity") drawGravitySpokes(ctx, players, cfg.gravityFocus, W, H);
      drawPlayers(ctx, players, ball, W, H, opts);
    } else if (fr.hero_xy) {
      const hp = lerpPt(fr.hero_xy, frNext.hero_xy, f);
      const [hx, hy] = m2px(hp[0], hp[1], W, H);
      ctx.beginPath(); ctx.arc(hx, hy, Math.max(6, W / 120), 0, Math.PI * 2);
      ctx.fillStyle = "#fff"; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = "#6cb4ee"; ctx.stroke();
    }
    if (surf.teams) drawGoalLabels(ctx, W, H, surf.teams);
    if (cfg.ballXt && ball) {
      const bxt = (fr.xt != null) ? (fr.xt * (1 - f) + (frNext.xt ?? fr.xt) * f) : null;
      if (bxt != null) drawBallXt(ctx, ball, bxt, W, H);
    }
    tl.textContent = `${i0 + 1}/${n} · ${ts.toFixed(1)}s`;
    ro.innerHTML = cfg.readout ? cfg.readout(fr, state) : "";
    // running ledger: light up each pass once the playhead reaches it, sum the xT added.
    if (passes && pxEl) {
      let tot = 0;
      passes.forEach((p, i) => {
        const on = p.t_s <= ts + 1e-6;
        const li = pxEl.querySelector(`li[data-i="${i}"]`);
        if (li) li.classList.toggle("on", on);
        if (on) tot += p.xt_added;
      });
      const pt = $(`#pt-${cfg.id}`);
      if (pt) pt.textContent = `${tot >= 0 ? "+" : ""}${tot.toFixed(2)} xT`;
    }
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
  try { d = await loadJSON("data/intro_efi.json?v=2"); }
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
    const d = await loadJSON("data/surfaces/xt_reference.json?v=2");
    const W = 640, H = Math.round(640 * 68 / 105);
    el.innerHTML = `<div class="hstage"><canvas width="${W}" height="${H}" id="cv-xt" style="cursor:crosshair"></canvas></div>
      <div class="hreadout" id="xt-read"><span class="hint">Hover anywhere on the pitch to read its xT (like Karun Singh's original).</span></div>`;
    const cv = $("#cv-xt"), ctx = cv.getContext("2d"), readEl = $("#xt-read");
    const S = d.surface_norm, mxv = d.max_xt, ny = S.length, nx = S[0].length;
    function paintBase() {
      paintSurface(ctx, S, W, H, { ramp: rampHot, gamma: 0.85, threshold: 0, felt: "#0b160f", felt2: "#0b160f" });
      // peak marker
      let pr = 0, pc = 0, m = 0;
      S.forEach((row, r) => row.forEach((v, c) => { if (v > m) { m = v; pr = r; pc = c; } }));
      const px = (pc + 0.5) / nx * W, py = (pr + 0.5) / ny * H;
      ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI * 2);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = "12px sans-serif"; ctx.textAlign = "left";
      ctx.fillText(`peak ${mxv.toFixed(3)}`, px + 11, py + 4);
      ctx.fillStyle = "rgba(255,255,255,.5)"; ctx.font = "11px sans-serif"; ctx.textAlign = "right";
      ctx.fillText("opponent goal →", W - 8, 16);
    }
    paintBase();
    const base = ctx.getImageData(0, 0, W, H);   // snapshot so hover redraws are cheap
    const cellAt = (clientX, clientY) => {
      const r = cv.getBoundingClientRect();
      const px = (clientX - r.left) / r.width * W, py = (clientY - r.top) / r.height * H;
      return { c: clamp(Math.floor(px / W * nx), 0, nx - 1), r: clamp(Math.floor(py / H * ny), 0, ny - 1) };
    };
    const showCell = (c, r) => {
      const xt = S[r][c] * mxv;
      ctx.putImageData(base, 0, 0);
      const x0 = c / nx * W, y0 = r / ny * H, cw = W / nx, ch = H / ny;
      ctx.fillStyle = "rgba(255,255,255,0.16)"; ctx.fillRect(x0, y0, cw, ch);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.strokeRect(x0, y0, cw, ch);
      readEl.innerHTML = `<b>xT = ${xt.toFixed(3)}</b>: with the ball in this zone, the team scores within the next ~5 actions about <b>${(xt * 100).toFixed(1)}%</b> of the time.`;
    };
    const clearHover = () => {
      ctx.putImageData(base, 0, 0);
      readEl.innerHTML = `<span class="hint">Hover anywhere on the pitch to read its xT (like Karun Singh's original).</span>`;
    };
    cv.addEventListener("mousemove", (e) => { const p = cellAt(e.clientX, e.clientY); showCell(p.c, p.r); });
    cv.addEventListener("mouseleave", clearHover);
    cv.addEventListener("touchmove", (e) => {
      const t = e.touches[0]; if (!t) return; e.preventDefault();
      const p = cellAt(t.clientX, t.clientY); showCell(p.c, p.r);
    }, { passive: false });
  } catch (e) { el.innerHTML = `<p class="caption">xT surface unavailable: ${e.message}</p>`; }
}

// xT-created leaderboards (teams + players by threat added through open-play passing)
async function buildXTcreated() {
  const tEl = $("#xt-teams"), pEl = $("#xt-players");
  if (!tEl && !pEl) return;
  let d;
  try { d = await loadJSON("data/xt_created.json?v=2"); } catch (e) { return; }
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
      <span class="tbtrack"><span class="tbfill" style="width:${clamp(valOf(r) / mx * 100, 0, 100)}%;background:${colOf(r)}"></span></span>
      <span class="tbval">${fmt(valOf(r))}</span></div>`).join("");
  };
  if (tEl) {
    tEl.innerHTML = bars(d.teams.slice(0, 8), (r) => r.xt_per_match,
      (r) => r.team, (r) => teamColor(r.team), (v) => v.toFixed(2));
  }
  if (pEl) {
    const lab = $("#xt-pl-lab"), tg = $("#xt-pl-toggle");
    const renderPlayers = (mode) => {
      const permatch = mode === "permatch";
      const rows = [...d.players].sort((a, b) =>
        (permatch ? b.xt_per_match - a.xt_per_match : b.xt_total - a.xt_total)).slice(0, 10);
      pEl.innerHTML = bars(rows, (r) => permatch ? r.xt_per_match : r.xt_total,
        (r) => `${shortName(r.name)} <span class="lteam">${r.team}</span>${permatch ? ` <span class="lpos">${r.matches}m</span>` : ""}`,
        (r) => teamColor(r.team), (v) => permatch ? v.toFixed(2) : v.toFixed(1));
      if (lab) lab.innerHTML = permatch
        ? "Players · xT added <b>per match</b> (WC2022 · games played shown)"
        : "Players · <b>total</b> xT added (WC2022)";
    };
    renderPlayers("total");
    if (tg) $$(".htog", tg).forEach((b) => b.addEventListener("click", () => {
      $$(".htog", tg).forEach((x) => x.classList.toggle("on", x === b));
      renderPlayers(b.dataset.m);
    }));
  }
}

/* "where the xT comes from" — per-player bucket breakdown (tiny/small/moderate/big) */
async function buildXtBreakdown() {
  const el = $("#xt-breakdown"); if (!el) return;
  let d; try { d = await loadJSON("data/xt_breakdown.json?v=1"); } catch (e) { return; }
  const RANGE = { tiny: "0–0.01", small: "0.01–0.03", moderate: "0.03–0.07", big: ">0.07 (box entries)" };
  const gmx = Math.max(1e-9, ...(d.players || []).flatMap((p) => p.buckets.map((b) => b.sum)));
  el.innerHTML = (d.players || []).map((p) => {
    const rows = p.buckets.map((b) => `<div class="tbrow"><span class="tbname">${b.label} <span class="lteam">${RANGE[b.label] || ""}</span> <span class="lteam">${b.count}×</span></span>
      <span class="tbtrack"><span class="tbfill" style="width:${clamp(b.sum / gmx * 100, 0, 100)}%;background:${teamColor(p.team)}"></span></span>
      <span class="tbval">${b.sum.toFixed(2)}</span></div>`).join("");
    return `<div><div class="boardlab">${p.name} <span class="lteam">${p.team}</span> · <b style="color:var(--ink)">${p.total} total</b> · ${p.per_match}/match</div>
      ${rows}
      <p class="caption faintnote">${p.actions} passes+carries · ${p.backward_pct}% backward/sideways (count as 0) · biggest single +${p.biggest}</p></div>`;
  }).join("");
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
      const pctW = clamp(v / mx * 100, 0, 100);
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
  if (!$("#chase-canvas")) return;   // gravity act stashed (no-gravity restructure)
  const surf = await loadJSON("data/surfaces/chase.json");
  const data = await loadJSON("data/space_chase.json?v=64");
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
  // floor cameo players (gravity-frames in only ONE match spike the top) on the 64 sample
  const top = data.players.filter((r) => r.n_matches >= 2).slice(0, 12);
  const lb = leaderboard(top, {
    name: (r) => r.name, team: (r) => r.team, pos: (r) => r.position, val: (r) => r.gravity,
    fmt: (v) => v.toFixed(2),
    tier: (r) => r.rank, barColor: "#9b8cff", scrubberEl: scEl,
    note: (r) => `<span class="comp">drawn ${r.drawn_markers.toFixed(2)} · pull ${r.chase_pull_ms.toFixed(2)} m/s</span>`,
    tierLabel: (g, m, gi) => gi === 0
      ? `most gravity — the strikers who bend the block`
      : (m.length > 1 ? `the chasing group` : `tier ${gi + 1}`),
  });
  $("#chase-board").appendChild(lb);
  // team gravity board + its xG-receipt scatter removed in the sweep: team-aggregate
  // gravity collapses on all 64 (ρ +0.38 -> +0.03). Gravity stays a player + clip story.
}

async function buildPOBSO() {
  const surf = await loadJSON("data/surfaces/pobso.json?v=19");
  const data = await loadJSON("data/space_pobso.json?v=7");
  const scEl = $("#pobso-canvas");
  const h = surf.hero || {};
  const got = h.outcome === "goal" ? "and <b>scores</b>" : (h.outcome ? `and ${h.outcome}` : "and receives");
  const from = h.assist ? ` from <b>${h.assist}</b>` : "";
  buildScrubber(scEl, surf, {
    id: "pobso", ramp: rampHot, gamma: 0.55, threshold: 0.02, speed: 1.0,
    labelName: h.name, defaultMode: "surface",
    ballXt: true, receivers: surf.receivers || [], passes: surf.passes || null,
    toggles: [
      { key: "reveal", label: "reveal danger (× xT)" },
    ],
    readout: (fr, st) => st.mode === "reveal"
      ? `Only the cells the attacker controls <b>and</b> that carry threat stay lit. That is the dangerous space forming before the ball arrives.`
      : `<b>${h.name}</b> drifts off the ball into the space he both <b>owns</b> and can finish from, then receives${from} ${got}. `
        + `Each pass is tagged with the <b>xT it adds</b>; every receiver is ringed — `
        + `<span style="color:#5fd38a">green when his team owns the grass he is in</span>, `
        + `<span style="color:#ff6b6b">red when it does not</span> — and the tag on the ball is its live xT.`,
  });
  renderTeamLegend("pobso-teamleg", surf.teams);
  const im = surf.impact;
  if (im) {
    const goal = h.outcome === "goal";
    renderImpact(scEl, `<b>What it created.</b> Over ${im.window_s}s the ball`
      + ` climbed from ${im.xt_start.toFixed(2)} to <b>${im.xt_peak.toFixed(2)} xT</b>,`
      + ` a <span class="big">+${im.xt_added.toFixed(2)} xT</span> rise in threat`
      + `${goal ? ", and it ended in a <b>goal</b>" : (h.outcome ? `, and ended in a <b>${h.outcome}</b>` : "")}.`
      + ` That is dangerous space turned into the highest-value spot on the pitch.`);
  }
  // name the auto-picked runner in the card title
  const pbTitle = $("#pobso-hero-title");
  if (pbTitle && h.name) pbTitle.textContent = `${h.name}'s run and finish`;
  // PLAYER board. DEFAULT = PER MOMENT (the intensity board): mean control×xT m² a player owns
  // at any instant off the ball (≥90 min so cameo subs don't spike it). PER MATCH = danger-
  // weighted m²·min/game with a group/knockout/all stage split (so it is not just deep-run teams).
  // Opponent-weighted/raw applies to both. Same stages schema as the other boards.
  const boardEl = $("#pobso-board"), vtg = $("#pobso-view"), btg = $("#pobso-toggle"), bwt = $("#pobso-weight");
  const blab = $("#pobso-lab"), btop = $("#pobso-top"), SCALE = 0.5 / 60;
  const players = (data.players || []).filter((r) => r.stages && r.position);
  const bst = { view: "moment", stage: "ko", weighted: false };
  const row = (r, val, badge, fmt) => `<div class="tbrow"><span class="tbname">${r.name} <span class="lteam">${r.team || ""}</span>${r.position ? ` <span class="lpos">${r.position}</span>` : ""} <span class="lpos">${badge}</span></span>
      <span class="tbtrack"><span class="tbfill" style="width:${clamp(val, 0, 100)}%;background:#ff8a5c"></span></span>
      <span class="tbval">${fmt}</span></div>`;
  const renderBoard = () => {
    const stage = bst.stage, w = bst.weighted, okM = (s) => s && s.matches >= (STAGE_MIN[stage] || 2);
    let sv, fmt, lab;
    if (bst.view === "moment") {
      // intensity: mean control×xT m² owned per frame present IN this stage (≥6000 frames ≈ real
      // minutes, so cameo subs don't spike the mean). Stage-aware now.
      sv = (r) => { const s = r.stages[stage]; return (okM(s) && (s.frames || 0) >= 10800) ? (w ? s.per_moment : s.per_moment_raw) : null; };  // ≥~90 min in this stage (no cameo-sub spikes)
      fmt = (v) => v.toFixed(1);
      lab = `Players · dangerous space owned <b>at any instant</b> off the ball (control × xT m²)${w ? ", opponent-weighted" : " <span class='lpos'>(raw)</span>"} · <b>${STAGE_LABEL[stage]}</b>`;
    } else if (bst.view === "total") {
      sv = (r) => { const s = r.stages[stage]; return okM(s) ? (w ? s.total : s.total_raw) * SCALE : null; };
      fmt = (v) => Math.round(v).toLocaleString();
      lab = `Players · <b>total</b> dangerous space owned off the ball (m²·min)${w ? ", opponent-weighted" : " <span class='lpos'>(raw)</span>"} · <b>${STAGE_LABEL[stage]}</b>`;
    } else {
      sv = (r) => { const s = r.stages[stage]; return okM(s) ? (w ? s.per_match : s.per_match_raw) * SCALE : null; };
      fmt = (v) => Math.round(v).toLocaleString();
      lab = `Players · dangerous space owned off the ball, <b>m²·min per match</b>${w ? ", opponent-weighted" : " <span class='lpos'>(raw)</span>"} · <b>${STAGE_LABEL[stage]}</b>`;
    }
    const rows = players.filter((r) => sv(r) != null).sort((a, b) => sv(b) - sv(a)).slice(0, 12);
    const mx = Math.max(1e-9, ...rows.map(sv));
    boardEl.innerHTML = rows.map((r) => row(r, sv(r) / mx * 100, `${r.stages[stage].matches}m`, fmt(sv(r)))).join("");
    if (blab) blab.innerHTML = lab;
    if (btop) btop.textContent = rows.slice(0, 3).map((r) => r.name).join(", ");
  };
  const syncStageBtns = () => { if (btg) $$(".htog", btg).forEach((x) => x.classList.toggle("on", x.dataset.m === bst.stage)); };
  syncStageBtns(); renderBoard();
  if (vtg) $$(".htog", vtg).forEach((b) => b.addEventListener("click", () => {
    bst.view = b.dataset.v; $$(".htog", vtg).forEach((x) => x.classList.toggle("on", x === b));
    bst.stage = bst.view === "match" ? "group" : "ko";   // moment/total default to knockout, per-match to the level field
    syncStageBtns(); renderBoard();
  }));
  if (btg) $$(".htog", btg).forEach((b) => b.addEventListener("click", () => {
    bst.stage = b.dataset.m; $$(".htog", btg).forEach((x) => x.classList.toggle("on", x === b)); renderBoard();
  }));
  if (bwt) $$(".htog", bwt).forEach((b) => b.addEventListener("click", () => {
    bst.weighted = b.dataset.w === "weighted"; $$(".htog", bwt).forEach((x) => x.classList.toggle("on", x === b)); renderBoard();
  }));
  // NOTE: the team danger-RATE board + its xG-receipt were removed in the consolidation
  // sweep — that metric tracked xG only on the 10 knockout contenders and INVERTS across
  // all 64 (counter teams get acres of unconverted transition space). See the "measuring
  // space wrong" beat. Act 2 now keeps the dangerous-space clip + the player board only.
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
// (team pitch-control scatter removed in the Pass 1 restructure)

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
          <span class="ctrack"><span class="cfill" style="width:${clamp(v / mx * 100, 0, 100)}%;background:${col}"></span></span>
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
          ${cmp("Dangerous space · danger-moments / min", danger.Argentina, danger.France, num)}
          <div class="lcallout">France's danger was concentrated: <b>Mbappé</b>'s hat-trick, and France's late surges into dangerous space (the kind you scrubbed in <b>Act 2</b>). The team rate favours Argentina; France's biggest moments were a handful of individual runs.</div>
          <div class="lcallout">Both lenses agree on the shape of the game: <b>Argentina created more, more often</b>, off two completely independent measurement systems.</div>
        </div>
      </div>`;
      // the outcome — real StatsBomb xG (the page's "so what", at match level)
      if (xg.Argentina && xg.France) {
        const a = xg.Argentina, b = xg.France, mx = Math.max(a.xg, b.xg, 1);
        const xbar = (name, v, np, col) => `<div class="cmprow"><span class="ck">${name}</span>
          <span class="ctrack"><span class="cfill" style="width:${clamp(v / mx * 100, 0, 100)}%;background:${col}"></span></span>
          <span class="cval">${v.toFixed(2)}</span></div>
          <div class="cmprow"><span class="ck"></span><span class="cmpsub">open-play (non-penalty) xG: <b>${np.toFixed(2)}</b></span></div>`;
        lensEl.innerHTML += `<div class="card lxg">
          <div class="clab"><b>The outcome: real expected goals</b> <span class="lteam">StatsBomb 2022, penalty shootout excluded</span></div>
          ${xbar("ARG", a.xg, a.npxg, ARG)}${xbar("FRA", b.xg, b.npxg, FRA)}
          <p class="caption">The space dominance showed up on the scoreboard of chances: Argentina out-created France on xG (2.76 vs 2.27), and in <b>open play it isn't close</b> (1.97 vs 0.71). France's xG was penalty-driven; their open-play danger really did run through Mbappé. Three independent measurements (FIFA's counts, our tracking, StatsBomb's xG) all point the same way.</p>
        </div>`;
      }
    } catch (e) {
      lensEl.innerHTML = `<p class="caption">2022-final EFI comparison unavailable (${e.message}).</p>`;
    }
  }

  /* ---- 2026 live: threat (value) paired with receptions in behind (access) ---- */
  if (liveEl) {
    try {
      const dThreat = await loadJSON("data/efi_2026.json?v=3");
      const dAccess = await loadJSON("data/intro_efi.json?v=2");
      const tRows = (dThreat.team_threat_leaders || []).slice(0, 6);
      const aRows = ((dAccess.efi_2026 || {}).receptions_in_behind || []).slice(0, 6);
      const board = (rows, valKey, fmt) => {
        const mx = Math.max(1, ...rows.map((r) => r[valKey]));
        return `<div class="tbars">` + rows.map((r) => {
          const nm = codeName(r.team);
          return `<div class="tbrow"><span class="tbname">${nm} <span class="lteam">${r.team}</span></span>
            <span class="tbtrack"><span class="tbfill" style="width:${clamp(r[valKey] / mx * 100, 0, 100)}%;background:${teamColor(nm)}"></span></span>
            <span class="tbval">${fmt(r[valKey])}</span></div>`;
        }).join("") + `</div>`;
      };
      const n = dThreat.n_matches || (dAccess.efi_2026 || {}).n_matches_played || "—";
      liveEl.innerHTML = `
        <div class="liveupd">Updated ${fmtDate(dThreat.fetched)} · ${n} WC2026 matches · FIFA EFI</div>
        <div class="liveboards">
          <div><h4>Threat created · per match <span class="unit">FIFA's xT-cousin (value)</span></h4>${board(tRows, "threat", (v) => v.toFixed(1))}</div>
          <div><h4>Receptions in behind · per match <span class="unit">space access</span></h4>${board(aRows, "per_match", (v) => v.toFixed(0))}</div>
        </div>`;
    } catch (e) {
      liveEl.innerHTML = `<p class="caption">Live WC2026 EFI feed unavailable right now (${e.message}). The 2022 lens above stands on its own.</p>`;
    }
  }

}

/* ---- 2026 threat created (team + player) — FIFA's live xT-cousin.
   Lives in the xT act (Act 1) as "the same idea, measured live in 2026". ---- */
async function buildThreat() {
  const ttEl = $("#xt-threat-teams"), tpEl = $("#xt-threat-players");
  if (!ttEl && !tpEl) return;
  try {
    const d = await loadJSON("data/efi_2026.json?v=3");
    const up = $("#xt-threat-updated");
    if (up && d.fetched) up.textContent =
      `FIFA EFI · live · updated ${fmtDate(d.fetched)} · ${d.n_matches || "—"} matches, ${d.n_teams || "—"} teams`;
    if (ttEl) {
      const rows = (d.team_threat_leaders || []).slice(0, 8);
      const mx = Math.max(1, ...rows.map((r) => r.threat));
      ttEl.innerHTML = rows.map((r) => {
        const nm = codeName(r.team);
        return `<div class="tbrow"><span class="tbname">${nm} <span class="lteam">${r.team}</span></span>
          <span class="tbtrack"><span class="tbfill" style="width:${clamp(r.threat / mx * 100, 0, 100)}%;background:${teamColor(nm)}"></span></span>
          <span class="tbval">${r.threat.toFixed(1)}</span></div>`;
      }).join("");
    }
    if (tpEl) {
      const rows = (d.player_threat_leaders || []).slice(0, 8);
      const mx = Math.max(1, ...rows.map((r) => r.threat));
      tpEl.innerHTML = rows.map((r) => {
        const team = codeName(r.team);
        return `<div class="tbrow"><span class="tbname">${r.player} <span class="lteam">${team}</span></span>
          <span class="tbtrack"><span class="tbfill" style="width:${clamp(r.threat / mx * 100, 0, 100)}%;background:${teamColor(team)}"></span></span>
          <span class="tbval">${r.threat.toFixed(1)}</span></div>`;
      }).join("");
    }
  } catch (e) {
    if (ttEl) ttEl.innerHTML = `<p class="caption">threat feed unavailable (${e.message})</p>`;
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
    <svg class="xpl-svg" viewBox="0 0 240 110" preserveAspectRatio="xMidYMid meet" overflow="hidden" role="img" aria-label="ball moving into higher-value zone">
      <rect x="4" y="4" width="232" height="102" fill="#0b160f"/>
      <line x1="120" y1="4" x2="120" y2="106" stroke="#bcd2e6" stroke-opacity=".18"/>
      <rect x="200" y="28" width="36" height="54" fill="none" stroke="#bcd2e6" stroke-opacity=".22"/>
      <path d="M80,60 Q150,16 224,50" fill="none" stroke="#9aa6b6" stroke-opacity=".35" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="150" y="20" text-anchor="middle" font-size="8" fill="#9aa6b6">+0.24 threat added</text>
      ${stops.map(s => `<circle cx="${s.x}" cy="${s.y}" r="2.4" fill="#9aa6b6" fill-opacity=".5"/>`).join("")}
      <circle id="xtBall" cx="${stops[0].x}" cy="${stops[0].y}" r="4.5" fill="#fff" stroke="#000" stroke-width="1"/>
      <text x="226" y="16" text-anchor="end" font-size="8" fill="#9aa6b6">goal →</text>
    </svg>
    <div class="xpl-num">threat <span id="xtVal">0.02</span></div>
    <p class="xpl-cap">The ball climbs from midfield, to the edge of the box, to <b>right in front of goal</b>. Same move, far more <b>threat</b>, because the zone is worth more. xT peaks at the goal.</p>`;
  const valEl = $("#xtVal", host), ball = $("#xtBall", host);
  const lerp = (a, b, t) => a + (b - a) * t;
  const T = 4600, hold = 1100, travel = T - hold;   // travel the 2 legs, then hold at goal, loop
  let raf, t0 = null;
  const tick = (now) => {
    if (t0 === null) t0 = now;
    const p = (now - t0) % T;
    const prog = p < travel ? (p / travel) * 2 : 2;  // 0..2 across the two legs, then hold at 2
    const i = Math.min(1, Math.floor(prog)), f = clamp(prog - i, 0, 1);
    const a = stops[i], b = stops[i + 1];
    const x = lerp(a.x, b.x, f), y = lerp(a.y, b.y, f), v = lerp(a.v, b.v, f);
    ball.setAttribute("cx", x.toFixed(1));
    ball.setAttribute("cy", y.toFixed(1));
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
function buildDangerExplainer(sel = "#pobso-explainer", capHtml) {
  const host = $(sel); if (!host) return;
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
          <stop offset="0%" stop-color="#1a2440"/><stop offset="40%" stop-color="#3cb878"/>
          <stop offset="75%" stop-color="#ffc43c"/><stop offset="100%" stop-color="#ff6b6b"/>
        </linearGradient>
        <radialGradient id="dangerPocket" cx="62%" cy="44%" r="42%">
          <stop offset="0%" stop-color="#ff6b6b" stop-opacity="1"/>
          <stop offset="55%" stop-color="#ff9a3a" stop-opacity=".55"/>
          <stop offset="100%" stop-color="#ff9a3a" stop-opacity="0"/>
        </radialGradient>
      </defs>
      <g><rect x="6" y="14" width="72" height="58" fill="#0e1014"/>
         <ellipse cx="42" cy="43" rx="26" ry="20" fill="url(#ctrlBlob)"/>
         <text x="42" y="86" text-anchor="middle" font-size="9" fill="#9aa6b6">control</text></g>
      <text x="100" y="48" text-anchor="middle" font-size="20" fill="#e8edf4">×</text>
      <g><rect x="120" y="14" width="72" height="58" fill="#0e1014"/>
         <rect x="122" y="16" width="68" height="54" fill="url(#xtGrad)"/>
         <text x="156" y="86" text-anchor="middle" font-size="9" fill="#9aa6b6">value (xT)</text></g>
      <text x="214" y="48" text-anchor="middle" font-size="18" fill="#e8edf4">=</text>
      <g><rect x="234" y="14" width="60" height="58" fill="#0e1014"/>
         <circle cx="264" cy="40" r="20" fill="url(#dangerPocket)"/>
         <text x="264" y="86" text-anchor="middle" font-size="9" fill="#ff6b6b">danger pocket</text></g>
    </svg>
    <p class="xpl-cap">${capHtml || "<b>pitch control × xT = dangerous space.</b> Control over low-value grass scores near zero. Only the grass a player both owns and that sits near goal lights up."}</p>`;
}

/* small DOM legend naming both playing teams with their dot colors (att=blue/def=red). */
function renderTeamLegend(elId, teams, attColor = "#7ec8ff", defColor = "#ff9a9a") {
  const el = document.getElementById(elId); if (!el || !teams) return;
  el.innerHTML =
    `<span><span class="tswatch" style="background:${attColor}"></span><b>${teams.attack}</b> attacking</span>` +
    `<span><span class="tswatch" style="background:${defColor}"></span><b>${teams.defend}</b> defending</span>` +
    `<span><span class="tswatch gk" style="background:#6dd58c"></span>goalkeepers (team-ringed)</span>`;
}

/* per-clip "what it created" receipt — appended to the clip card, after the caption. */
function renderImpact(canvasEl, html) {
  if (!canvasEl || !canvasEl.parentElement) return;
  let box = canvasEl.parentElement.querySelector(".impact");
  if (!box) { box = document.createElement("div"); box.className = "impact"; canvasEl.parentElement.appendChild(box); }
  box.innerHTML = html;
}

/* 4) PITCH CONTROL — fully INTERACTIVE. Drag the attacker, defender and ball; each
   player's velocity is taken from how fast you drag (a quick flick = a sprint), and
   the control surface recomputes live. Faithful port of pitch_control.py's
   Fernández–Bornn influence (bivariate normal, velocity-shifted centre, speed-
   elongated covariance, distance-to-ball radius scaling). */
function buildPitchControlExplainer() {
  const host = $("#pc-explainer"); if (!host) return;
  const W = 520, H = 322, REG_W = 64, REG_H = REG_W * H / W;   // ~64 m × 40 m of pitch
  const SC = W / REG_W;                                        // px per metre
  const GW = 64, GH = Math.round(GW * H / W);                  // control-grid resolution
  host.innerHTML = `
    <div class="xpl-head">how it's built · <b>pitch control</b> (Fernández &amp; Bornn). <span style="color:var(--accent)">drag the dots</span></div>
    <div class="pcx-stage"><canvas id="pcx-cv" width="${W}" height="${H}"></canvas></div>
    <div class="pcx-read" id="pcx-read"></div>
    <p class="xpl-cap"><b>Drag the attacker, defender or ball.</b> Each player's influence is a bivariate-normal blob; a spot's <b>control = σ(attacker − defender influence)</b> (blue = attacker owns, red = defender owns). Drag a player <b>faster</b> and its influence <b>stretches forward</b>, because a sprint reaches more grass ahead, and the field tilts. Move it onto the ball and its blob tightens; far from the ball it spreads.</p>`;
  const cv = $("#pcx-cv", host), ctx = cv.getContext("2d"), readEl = $("#pcx-read", host);
  const m2p = (x, y) => [x * SC, y * SC];
  // state (metres). attacker attacks +x (right).
  const att = { x: 22, y: REG_H / 2, vx: 0, vy: 0, kind: "att" };
  const def = { x: 34, y: REG_H / 2 - 2, vx: 0, vy: 0, kind: "def" };
  const ball = { x: 16, y: REG_H / 2, kind: "ball" };
  const players = [att, def];

  function influence(pl, gx, gy) {        // Fernández–Bornn influence of pl at (gx,gy) metres
    const speed = Math.hypot(pl.vx, pl.vy);
    const distBall = Math.hypot(pl.x - ball.x, pl.y - ball.y);
    const frac = Math.min(distBall / 18, 1);
    const radius = 4 + 4 * frac * frac;          // gentler far-from-ball growth (teaching view)
    const sr = Math.min(speed / 13, 1);
    const sAlong = radius * (1 + 0.6 * sr);       // softer forward stretch so fast drags don't warp
    const sPerp = Math.max(radius * (1 - 0.35 * sr), radius * 0.55);
    const mux = pl.x + 0.5 * pl.vx * 0.5, muy = pl.y + 0.5 * pl.vy * 0.5;
    let cos = 1, sin = 0;
    if (speed > 1e-3) { cos = pl.vx / speed; sin = pl.vy / speed; }
    const dx = gx - mux, dy = gy - muy;
    const u = cos * dx + sin * dy, w = -sin * dx + cos * dy;
    return Math.exp(-0.5 * ((u / sAlong) ** 2 + (w / sPerp) ** 2));
  }
  const off = document.createElement("canvas"); off.width = GW; off.height = GH;
  const octx = off.getContext("2d");
  function draw() {
    // control grid → diverging blue/red field (alpha by decisiveness)
    const img = octx.createImageData(GW, GH);
    for (let r = 0; r < GH; r++) for (let c = 0; c < GW; c++) {
      const gx = (c + 0.5) / GW * REG_W, gy = (r + 0.5) / GH * REG_H;
      const a = influence(att, gx, gy), d = influence(def, gx, gy);
      const ctrl = 1 / (1 + Math.exp(-2.4 * (a - d)));
      const k = (ctrl - 0.5) * 2;                  // -1 (def) .. +1 (att)
      const i = (r * GW + c) * 4;
      if (k >= 0) { img.data[i] = 108; img.data[i + 1] = 180; img.data[i + 2] = 238; }
      else { img.data[i] = 238; img.data[i + 1] = 120; img.data[i + 2] = 120; }
      img.data[i + 3] = Math.round(200 * Math.min(Math.abs(k) * 1.2, 1));
    }
    octx.putImageData(img, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#0c1116"; ctx.fillRect(0, 0, W, H);
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
    ctx.drawImage(off, 0, 0, GW, GH, 0, 0, W, H);
    // players + velocity arrows
    for (const pl of players) {
      const [px, py] = m2p(pl.x, pl.y);
      const sp = Math.hypot(pl.vx, pl.vy);
      if (sp > 0.3) {                              // velocity arrow (1 m/s ≈ 3 px)
        const ax2 = px + pl.vx * SC * 0.45, ay2 = py + pl.vy * SC * 0.45;
        ctx.strokeStyle = "rgba(255,255,255,0.8)"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(ax2, ay2); ctx.stroke();
        const ang = Math.atan2(ay2 - py, ax2 - px);
        ctx.beginPath(); ctx.moveTo(ax2, ay2);
        ctx.lineTo(ax2 - 6 * Math.cos(ang - 0.4), ay2 - 6 * Math.sin(ang - 0.4));
        ctx.lineTo(ax2 - 6 * Math.cos(ang + 0.4), ay2 - 6 * Math.sin(ang + 0.4));
        ctx.closePath(); ctx.fillStyle = "rgba(255,255,255,0.8)"; ctx.fill();
      }
      ctx.beginPath(); ctx.arc(px, py, 9, 0, Math.PI * 2);
      ctx.fillStyle = pl.kind === "att" ? "#7ec8ff" : "#ff9a9a";
      ctx.strokeStyle = "#0a0c10"; ctx.lineWidth = 2; ctx.fill(); ctx.stroke();
    }
    const [bx, by] = m2p(ball.x, ball.y);
    // LIVE control metric at the ball's spot — σ(attacker − defender influence) there
    const cb = 1 / (1 + Math.exp(-2.4 * (influence(att, ball.x, ball.y) - influence(def, ball.x, ball.y))));
    const cCol = cb > 0.5 ? "#7ec8ff" : "#ff9a9a";
    // value chip above the ball
    ctx.save();
    ctx.font = "700 13px Inter, system-ui, sans-serif"; ctx.textAlign = "center";
    const txt = cb.toFixed(2), cw = ctx.measureText(txt).width + 12;
    const chipY = by - 26;
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(bx - cw / 2, chipY - 9, cw, 18, 5)
      : ctx.rect(bx - cw / 2, chipY - 9, cw, 18);
    ctx.fillStyle = "rgba(10,12,16,0.9)"; ctx.fill();
    ctx.strokeStyle = cCol; ctx.lineWidth = 1.2; ctx.stroke();
    ctx.fillStyle = cCol; ctx.textBaseline = "middle"; ctx.fillText(txt, bx, chipY + 0.5);
    ctx.restore();
    ctx.beginPath(); ctx.arc(bx, by, 5, 0, Math.PI * 2);
    ctx.fillStyle = "#fff"; ctx.strokeStyle = "#000"; ctx.lineWidth = 1.4; ctx.fill(); ctx.stroke();
    const owner = cb > 0.55 ? "attacker owns it" : cb < 0.45 ? "defender owns it" : "contested";
    readEl.innerHTML = `<b>control at the ball</b> <b style="color:${cCol}">${cb.toFixed(2)}</b> (${owner})`
      + ` · attacker <b style="color:#7ec8ff">${Math.hypot(att.vx, att.vy).toFixed(1)} m/s</b>`
      + ` · defender <b style="color:#ff9a9a">${Math.hypot(def.vx, def.vy).toFixed(1)} m/s</b>`
      + ` <span class="hint">drag a dot; flick to add speed</span>`;
  }

  // pointer drag with drag-derived velocity (EMA) + decay on release
  let dragging = null, lastT = 0, lastX = 0, lastY = 0;
  const pick = (mx, my) => {
    let best = null, bd = 22;
    for (const o of [...players, ball]) {
      const [px, py] = m2p(o.x, o.y), d = Math.hypot(mx - px, my - py);
      if (d < bd) { bd = d; best = o; }
    }
    return best;
  };
  const evtXY = (e) => {
    const rect = cv.getBoundingClientRect();
    const t = e.touches ? e.touches[0] : e;
    return [(t.clientX - rect.left) * (W / rect.width), (t.clientY - rect.top) * (H / rect.height)];
  };
  const onDown = (e) => {
    const [mx, my] = evtXY(e); const o = pick(mx, my);
    if (o) {
      dragging = o; lastT = performance.now(); lastX = mx; lastY = my;
      if (o.kind !== "ball") { o.vx = 0; o.vy = 0; }   // start fresh — no stale flick velocity
      e.preventDefault();
    }
  };
  const onMove = (e) => {
    if (!dragging) return;
    const [mx, my] = evtXY(e); const now = performance.now();
    const dt = Math.max(0.016, (now - lastT) / 1000);
    dragging.x = clamp(mx / SC, 0, REG_W); dragging.y = clamp(my / SC, 0, REG_H);
    if (dragging.kind !== "ball") {            // velocity from drag speed (m/s), clamped + EMA
      const vx = clamp((mx - lastX) / SC / dt, -9, 9), vy = clamp((my - lastY) / SC / dt, -9, 9);
      dragging.vx = 0.6 * dragging.vx + 0.4 * vx; dragging.vy = 0.6 * dragging.vy + 0.4 * vy;
    }
    lastT = now; lastX = mx; lastY = my; e.preventDefault();
  };
  const onUp = () => { dragging = null; };
  cv.addEventListener("mousedown", onDown); window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
  cv.addEventListener("touchstart", onDown, { passive: false });
  cv.addEventListener("touchmove", onMove, { passive: false });
  window.addEventListener("touchend", onUp);

  let raf;
  const loop = () => {
    for (const pl of players) if (pl !== dragging) { pl.vx *= 0.9; pl.vy *= 0.9; }  // velocity relaxes
    draw();
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
  host._stop = () => cancelAnimationFrame(raf);
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
/* ---------------- player-skill boards (pitch control turned on individuals, 64 games) */
// Stage filter (group / knockout / all), always PER MATCH and opponent-strength weighted —
// the fair way to compare players from teams that played different numbers of (different-
// strength) games. Group stage is the level field; knockout = vs elite defences.
const STAGE_LABEL = { group: "group stage", ko: "knockout", all: "all 64 games" };
const STAGE_MIN = { group: 2, ko: 1, all: 2 };
async function buildPassSelection() {
  const el = $("#ps-board"); if (!el) return;
  let d; try { d = await loadJSON("data/pass_selection.json?v=5"); } catch (e) { return; }
  const players = (d.players || []).filter((r) => !String(r.name).startsWith("#") && r.stages);
  if (!players.length) return;
  const lab = $("#ps-lab"), tg = $("#ps-toggle"), wtg = $("#ps-weight"), top = $("#ps-top");
  const st = { stage: "group", weighted: false };
  const render = () => {
    const stage = st.stage, key = st.weighted ? "per_match" : "per_match_raw";
    const min = STAGE_MIN[stage] || 2;
    const sv = (r) => (r.stages[stage] && r.stages[stage].matches >= min) ? r.stages[stage][key] : null;
    const rows = players.filter((r) => sv(r) != null).sort((a, b) => sv(b) - sv(a)).slice(0, 12);
    const mx = Math.max(1e-9, ...rows.map(sv));
    const PS_SCALE = 100;   // triple product (control × xT_dest × xT_added) is small; ×100 for a readable index
    el.innerHTML = rows.map((r) => { const s = r.stages[stage]; return `<div class="tbrow"><span class="tbname">${r.name} <span class="lteam">${r.team || ""}</span>${r.pos ? ` <span class="lpos">${r.pos}</span>` : ""} <span class="lpos">${s.matches}m</span></span>
      <span class="tbtrack"><span class="tbfill" style="width:${clamp(sv(r) / mx * 100, 0, 100)}%;background:#6cb4ee"></span></span>
      <span class="tbval">${(sv(r) * PS_SCALE).toFixed(2)}</span></div>`; }).join("");
    if (lab) lab.innerHTML = `Players · control × xT-added into dangerous space (threading index), <b>per match</b>${st.weighted ? ", opponent-strength weighted" : " <span class='lpos'>(raw)</span>"} · <b>${STAGE_LABEL[stage]}</b>`;
    if (top) top.textContent = rows.slice(0, 3).map((r) => r.name).join(", ");
  };
  render();
  if (tg) $$(".htog", tg).forEach((b) => b.addEventListener("click", () => {
    st.stage = b.dataset.m; $$(".htog", tg).forEach((x) => x.classList.toggle("on", x === b)); render();
  }));
  if (wtg) $$(".htog", wtg).forEach((b) => b.addEventListener("click", () => {
    st.weighted = b.dataset.w === "weighted"; $$(".htog", wtg).forEach((x) => x.classList.toggle("on", x === b)); render();
  }));
}

/* Act 2 — Space Occupation board: pitch control turned into a per-player number,
   split active (running) vs passive (walking). The Fernández & Bornn 2018 result;
   the passive split is the "Messi walks" finding. Reads the OBSO per-player data. */
async function buildSOG() {
  const el = $("#pc-sog"); if (!el) return;
  let d; try { d = await loadJSON("data/space_pobso.json?v=7"); } catch (e) { return; }
  const players = (d.players || []).filter((r) => r.walk_stages && r.stages);
  if (!players.length) return;
  const modeTg = $("#sog-mode"), stTg = $("#sog-stage"), lab = $("#sog-lab");
  const st = { mode: "passive", stage: "all" };
  const nameCell = (r) => `<span class="sogname"><span class="fl" style="background:${teamColor(r.team)}"></span>${r.name} <span class="lteam">${r.team}</span>${r.position ? ` <span class="lpos">${r.position}</span>` : ""}</span>`;
  const seg = (c, w) => `<span style="width:${Math.max(0, w).toFixed(1)}%;background:${c}"></span>`;
  const render = () => {
    const stage = st.stage, min = STAGE_MIN[stage] || 2;
    const walkOf = (r) => (r.walk_stages[stage] != null && r.stages[stage] && r.stages[stage].matches >= min) ? r.walk_stages[stage] : null;
    const valOf = (r) => { const w = walkOf(r); return w == null ? null : (st.mode === "active" ? 100 - w : w); };
    const col = st.mode === "active" ? "#f0b429" : "#6cb4ee";
    const word = st.mode === "active" ? "running" : "walking";
    const rows = players.filter((r) => valOf(r) != null).sort((a, b) => valOf(b) - valOf(a)).slice(0, 12);
    el.innerHTML = rows.map((r) => `<div class="sogrow">${nameCell(r)}<span class="sogbar">${seg(col, valOf(r))}</span><span class="sogval">${valOf(r)}% ${word}</span></div>`).join("");
    if (lab) lab.innerHTML = `Share of each player's dangerous space won <b>${word}</b> (${st.mode === "active" ? "2 m/s and up" : "under 2 m/s"}) · <b>${STAGE_LABEL[stage]}</b>`;
  };
  render();
  if (modeTg) $$(".htog", modeTg).forEach((b) => b.addEventListener("click", () => {
    st.mode = b.dataset.m; $$(".htog", modeTg).forEach((x) => x.classList.toggle("on", x === b)); render();
  }));
  if (stTg) $$(".htog", stTg).forEach((b) => b.addEventListener("click", () => {
    st.stage = b.dataset.s; $$(".htog", stTg).forEach((x) => x.classList.toggle("on", x === b)); render();
  }));
  const m = (d.players || []).find((r) => /Messi/.test(r.name) && r.minutes_sampled >= 90);
  // HEADLINE: overall share of his time on the pitch spent walking (distinct from the
  // danger-space share below — this is total time, the "Messi walks" number).
  const ws = $("#sog-walkstat");
  if (m && ws && m.time_walk_pct != null) {
    const field = (d.players || []).filter((r) => r.time_walk_pct != null && r.minutes_sampled >= 90);
    const sorted = field.slice().sort((a, b) => b.time_walk_pct - a.time_walk_pct);
    const rank = sorted.findIndex((r) => /Messi/.test(r.name)) + 1;
    const DEF = /\b(CB|RB|LB|RWB|LWB|WB|DM|GK)\b/i;   // defenders/holders walk most; Messi is a forward
    const above = sorted.slice(0, Math.max(0, rank - 1));
    const defAbove = above.filter((r) => DEF.test(r.position || "")).length;
    const tail = (rank > 3 && above.length && defAbove >= Math.ceil(above.length * 0.6))
      ? ` Almost everyone who walks more is a <b>defender</b> — he is a forward who owns the most dangerous space on the pitch.`
      : ` He owns the most dangerous space on the pitch while doing it.`;
    ws.innerHTML = `<span class="wnum">${m.time_walk_pct}%</span>`
      + `<span class="wlab">of his time on the pitch, <b>Messi is walking</b> (under 2 m/s)`
      + `${rank ? ` — the <b>#${rank}</b> highest share of the ${field.length} outfielders with real minutes` : ""}.`
      + `${tail}</span>`;
  }
  const mEl = $("#sog-messi");
  if (m && mEl) mEl.innerHTML = `<b>And it shows up in where it matters.</b> Of the dangerous space Messi wins, <b>${m.passive_pct}%</b> he wins while <b>walking</b> — the highest share of any forward — moving just <b>${m.control_speed} m/s</b> when he owns it. Fernández &amp; Bornn measured the same thing in 2017 and got 66%. He walks into the right grass while everyone else runs.`;
}

/* TEAM BOARD (Act 2): pitch control aggregated per team — territorial control %
   and dangerous space (OBSO), per match / total × group / knockout / all. The
   "France controlled 55% of the pitch?" board. Reads team_control.json. */
async function buildTeamBoard() {
  const el = $("#team-board"); if (!el) return;
  let d; try { d = await loadJSON("data/team_control.json?v=1"); } catch (e) { return; }
  const teams = d.teams || []; if (!teams.length) return;
  const mTg = $("#team-metric"), vTg = $("#team-view"), sTg = $("#team-stage"), lab = $("#team-lab"), top = $("#team-top");
  const st = { metric: "control", view: "per_match", stage: "group" };
  const valOf = (t) => {
    if ((t.n_matches[st.stage] || 0) < 1) return null;
    const blk = t[st.metric] && t[st.metric][st.view];
    return blk && blk[st.stage] != null ? blk[st.stage] : null;
  };
  const render = () => {
    const isC = st.metric === "control";
    const rows = teams.filter((t) => valOf(t) != null).sort((a, b) => valOf(b) - valOf(a)).slice(0, 14);
    const mx = Math.max(1e-9, ...rows.map(valOf));
    const fmt = isC ? (v) => v.toFixed(1) + "%" : (v) => Math.round(v).toLocaleString();
    const col = isC ? "#6cb4ee" : "#ff8a5c";
    el.innerHTML = rows.map((t) => `<div class="tbrow"><span class="tbname">${t.team} <span class="lpos">${t.n_matches[st.stage]}m</span></span>`
      + `<span class="tbtrack"><span class="tbfill" style="width:${clamp(valOf(t) / mx * 100, 0, 100)}%;background:${col}"></span></span>`
      + `<span class="tbval">${fmt(valOf(t))}</span></div>`).join("");
    if (lab) lab.innerHTML = `Teams · ${isC ? "<b>territorial control</b> (share of the pitch owned)" : "<b>dangerous space</b> (OBSO, xT-weighted m²·min)"}, ${st.view === "total" ? "<b>tournament total</b>" : "<b>per match</b>"} · <b>${STAGE_LABEL[st.stage]}</b>`;
    if (top) top.innerHTML = "Leaders: <b>" + rows.slice(0, 3).map((t) => t.team).join(", ") + "</b>";
  };
  render();
  const wire = (tg, key, get) => { if (tg) $$(".htog", tg).forEach((b) => b.addEventListener("click", () => { st[key] = get(b); $$(".htog", tg).forEach((x) => x.classList.toggle("on", x === b)); render(); })); };
  wire(mTg, "metric", (b) => b.dataset.k);
  wire(vTg, "view", (b) => b.dataset.v);
  wire(sTg, "stage", (b) => b.dataset.s);
}

/* SGG (Act 3, Application 2): Space Generation Gain — space a player frees for
   teammates by dragging a marker (F&B drag detection). Reads space_sgg.json. */
async function buildSGG() {
  const el = $("#sgg-board"); if (!el) return;
  let d; try { d = await loadJSON("data/space_sgg.json?v=1"); } catch (e) { return; }
  const players = (d.players || []).filter((r) => r.stages);
  if (!players.length) return;
  const vTg = $("#sgg-view"), sTg = $("#sgg-stage"), wTg = $("#sgg-weight"), lab = $("#sgg-lab"), top = $("#sgg-top");
  const st = { view: "per_match", stage: "group", weighted: false };
  const SCALE = 0.5 / 60;   // xT-wtd m²·frame → m²·min (same as the SOG board)
  const valOf = (r) => {
    const s = r.stages[st.stage];
    if (!s || s.matches < (STAGE_MIN[st.stage] || 2)) return null;
    const k = st.view === "total" ? (st.weighted ? "total" : "total_raw") : (st.weighted ? "per_match" : "per_match_raw");
    return s[k] != null ? s[k] * SCALE : null;
  };
  const render = () => {
    const rows = players.filter((r) => valOf(r) != null).sort((a, b) => valOf(b) - valOf(a)).slice(0, 12);
    const mx = Math.max(1e-9, ...rows.map(valOf));
    const fmt = (v) => st.view === "total" ? Math.round(v).toLocaleString() : v.toFixed(1);
    el.innerHTML = rows.map((r) => `<div class="tbrow"><span class="tbname">${r.name} <span class="lteam">${r.team || ""}</span>${r.position ? ` <span class="lpos">${r.position}</span>` : ""} <span class="lpos">${r.stages[st.stage].matches}m</span></span>`
      + `<span class="tbtrack"><span class="tbfill" style="width:${clamp(valOf(r) / mx * 100, 0, 100)}%;background:#9b8cff"></span></span>`
      + `<span class="tbval">${fmt(valOf(r))}</span></div>`).join("");
    if (lab) lab.innerHTML = `Players · space generated for teammates (control × xT m²·min)${st.view === "total" ? ", <b>tournament total</b>" : ", <b>per match</b>"}${st.weighted ? ", opponent-weighted" : " <span class='lpos'>(raw)</span>"} · <b>${STAGE_LABEL[st.stage]}</b>`;
    if (top) top.textContent = rows.slice(0, 3).map((r) => r.name).join(", ");
  };
  render();
  const wire = (tg, key, get) => { if (tg) $$(".htog", tg).forEach((b) => b.addEventListener("click", () => { st[key] = get(b); $$(".htog", tg).forEach((x) => x.classList.toggle("on", x === b)); render(); })); };
  wire(vTg, "view", (b) => b.dataset.v);
  wire(sTg, "stage", (b) => b.dataset.m);
  wire(wTg, "weighted", (b) => b.dataset.w === "weighted");
}

async function buildBWAE() {
  const el = $("#bwae-xt"); if (!el) return;
  let d; try { d = await loadJSON("data/balls_won_above_expected.json?v=4"); } catch (e) { return; }
  const players = (d.players || []).filter((r) => !String(r.name).startsWith("#") && r.stages);
  if (!players.length) return;
  const lab = $("#bwae-lab"), tg = $("#bwae-toggle"), wtg = $("#bwae-weight"), top = $("#bwae-top");
  const st = { stage: "all", weighted: false };
  const render = () => {
    const stage = st.stage, key = st.weighted ? "per_match" : "per_match_raw";
    const min = STAGE_MIN[stage] || 2;
    const sv = (r) => (r.stages[stage] && r.stages[stage].matches >= min) ? r.stages[stage][key] : null;
    const rows = players.filter((r) => sv(r) != null).sort((a, b) => sv(b) - sv(a)).slice(0, 12);
    const mx = Math.max(1e-9, ...rows.map(sv));
    el.innerHTML = rows.map((r) => { const s = r.stages[stage]; return `<div class="tbrow"><span class="tbname">${r.name} <span class="lteam">${r.team || ""}</span>${r.pos ? ` <span class="lpos">${r.pos}</span>` : ""} <span class="lpos">${s.matches}m</span></span>
      <span class="tbtrack"><span class="tbfill" style="width:${clamp(sv(r) / mx * 100, 0, 100)}%;background:#9b8cff"></span></span>
      <span class="tbval">${sv(r) >= 0 ? "+" : ""}${sv(r).toFixed(2)}</span></div>`; }).join("");
    if (lab) lab.innerHTML = `Players · xT-weighted balls won above expected, <b>per match</b>${st.weighted ? ", opponent-strength weighted" : " <span class='lpos'>(raw)</span>"} · <b>${STAGE_LABEL[stage]}</b>`;
    if (top) top.textContent = rows.slice(0, 3).map((r) => r.name).join(", ");
  };
  render();
  if (tg) $$(".htog", tg).forEach((b) => b.addEventListener("click", () => {
    st.stage = b.dataset.m; $$(".htog", tg).forEach((x) => x.classList.toggle("on", x === b)); render();
  }));
  if (wtg) $$(".htog", wtg).forEach((b) => b.addEventListener("click", () => {
    st.weighted = b.dataset.w === "weighted"; $$(".htog", wtg).forEach((x) => x.classList.toggle("on", x === b)); render();
  }));
}

/* Way 1 clip — a top creator's pass into controllable dangerous final-third space. */
async function buildPassingClip() {
  const el = $("#passing-canvas"); if (!el) return;
  let surf; try { surf = await loadJSON("data/surfaces/passing.json?v=8"); } catch (e) { return; }
  const h = surf.hero || {};
  const shot = h.shot_outcome
    ? ` The move ended in <b>${h.shot_outcome}</b>${h.shot_shooter ? ` (${h.shot_shooter})` : ""}.`
    : "";
  buildScrubber(el, surf, {
    id: "passing", ramp: rampHot, gamma: 0.55, threshold: 0.02,
    labelName: h.name, defaultMode: "surface",
    readout: () => `<b>${h.name}</b> threads it to <b>${h.receiver}</b> into controllable, dangerous space: `
      + `control ${Math.round((h.control || 0) * 100)}% × xT ${Number(h.xt || 0).toFixed(2)} at the target. `
      + `The bright pocket forms <b>before</b> the ball arrives.${shot}`,
  });
  renderTeamLegend("passing-teamleg", surf.teams);
  const im = surf.impact;
  if (im) renderImpact(el, `<b>What it created.</b> Over ${im.window_s}s the ball`
    + ` gained <span class="big">+${im.xt_added.toFixed(2)} xT</span> of threat (into the final third)`
    + `${h.shot_outcome ? `, and the move ended in <b>${h.shot_outcome}</b>${h.shot_shooter ? ` by ${h.shot_shooter}` : ""}` : ""}.`);
  const t1 = $("#passing-hero-title"), t2 = $("#passing-hero-title2");
  if (t1) t1.textContent = `${h.name}'s pass to ${h.receiver} (${surf.match})`;
  if (t2) t2.textContent = `${h.name} → ${h.receiver}`;
}

/* Way 2 clip — a ground duel won against the pitch-control expectation (a BWAE upset). */
async function buildDuelClip() {
  const el = $("#duel-canvas"); if (!el) return;
  let surf; try { surf = await loadJSON("data/surfaces/duel.json?v=8"); } catch (e) { return; }
  const h = surf.hero || {};
  buildScrubber(el, surf, {
    id: "duel", ramp: rampHot, gamma: 0.95, threshold: 0.05, surfaceAlpha: 0.6,
    labelName: h.name, defaultMode: "surface",
    duo: { winner: h.name, loser: h.loser }, focusBall: true, emphasizeBall: true,
    readout: () => `<b>${h.name}</b> (gold) and <b>${h.loser}</b> (red) arrive together. From where each player is and how `
      + `they are moving, pitch control gives <b>${h.name}</b> a <b>baseline ${h.expected_pct}%</b> chance of winning it. `
      + `He won it: <b>+${(1 - (h.expected_win ?? 0)).toFixed(2)}</b> above baseline. Beating the baseline like this, in `
      + `valuable areas, again and again, is the skill the board measures.`,
  });
  renderTeamLegend("duel-teamleg", surf.teams);
  // a duel's value is the possession won, not xT — show the BWAE swing vs the 50-50 odds
  const swing = (1 - (h.expected_win ?? 0)).toFixed(2);
  renderImpact(el, `<b>What it created.</b> Pitch control's <b>baseline</b> gave him a <b>${h.expected_pct}%</b> `
    + `chance from his position and momentum. He won it: <span class="big">+${swing}</span> above baseline. `
    + `Winning the ball back is the value; beating the baseline, in valuable areas, is the skill.`);
  const t1 = $("#duel-hero-title"), t2 = $("#duel-hero-title2");
  if (t1) t1.textContent = `${h.name} vs ${h.loser} (${surf.match})`;
  if (t2) t2.textContent = `${h.name} vs ${h.loser}`;
}

if (!window.__spaceWIPPage) {
  (async function () {
    initReveal();
    await buildIntro();
    // Act 1 — xT: value surface + leaderboard + live 2026 threat (the xT-cousin)
    await buildXT();
    buildXtExplainer();
    buildXTcreated();
    buildXtBreakdown();
    buildThreat();
    // Act 2 — Pitch control (Fernández & Bornn): interactive explainer + space-occupation board
    buildPitchControlExplainer();
    buildTeamBoard();
    // Act 3 — applications: off-ball SOG, SGG (teammates), passing, duels
    buildPassSelection();
    buildBWAE();
    buildSOG();
    buildSGG();
    await Promise.allSettled([buildPassingClip(), buildDuelClip(), buildPOBSO()]);
    buildDangerExplainer("#pobso-explainer");
    buildDangerExplainer("#ps-explainer", "<b>pitch control × xT = dangerous space.</b> Control over low-value grass scores near zero. The board below sums this product over each player's final-third passes, so a big number means repeated balls into controlled, high-value space.");
    // Closing — live 2026 (2022-final two-lens validation + live EFI)
    await buildLive();
  })();
}
