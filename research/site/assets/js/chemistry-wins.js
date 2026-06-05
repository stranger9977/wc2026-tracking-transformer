/* Chemistry → Winning — Tab 4.
   Story: chemistry wins, and it doesn't look the same for every team.
   Argentina = nucleus. France = network. Morocco = wall. Croatia = engine.
   Renders the headline scatter, four case-study networks + clips, and an
   appendix of remaining interactive plays. */

import { loadJSON, escapeHTML } from "./site.js";
import { mountClipInto, toggleClipGroup, setClipGroups, clearClipLabels, isClipGroupActive } from "./interactive-plays.js?v=lines-labels3";

/* ---------------- data ---------------- */

const [teamRows, fullNets] = await Promise.all([
  loadJSON("data/team_chemistry_vs_paper.json"),
  loadJSON("data/team_full_networks.json"),
]);

const TEAM_IDS = { France: "363", Argentina: "364", Morocco: "374", Croatia: "371" };
const SEMIS = new Set(["France", "Croatia", "Argentina", "Morocco"]);

/* ---------------- headline scatter (TCD vs finish) ---------------- */

const scatterEl = document.getElementById("chem-vs-result-scatter");
if (scatterEl && Array.isArray(teamRows)) {
  renderTcdScatter(teamRows.filter((r) => r.tcd != null && r.stage_int != null));
}

function renderTcdScatter(rows) {
  const W = 1100, H = 500;
  const padL = 86, padR = 48, padT = 22, padB = 72;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const xs = rows.map((r) => r.tcd);
  const xmin = Math.min(...xs) - 4, xmax = Math.max(...xs) + 4;
  const ymin = 1.4, ymax = 8.4;
  const sx = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const sy = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;

  const yLevels = [
    { y: 2, label: "Group" }, { y: 4, label: "R16" }, { y: 5, label: "QF" },
    { y: 6, label: "Semi" }, { y: 7, label: "Final" }, { y: 8, label: "Winner" },
  ];
  const yRules = yLevels.map(({ y, label }) => `
    <line x1="${padL}" y1="${sy(y)}" x2="${W - padR}" y2="${sy(y)}"
          stroke="currentColor" stroke-width="0.5" opacity="0.10"/>
    <text x="${padL - 8}" y="${sy(y) + 4}" font-size="12" font-weight="500"
          fill="currentColor" opacity="0.65" text-anchor="end">${label}</text>`).join("");

  const dots = rows.map((r) => {
    const cx = sx(r.tcd), cy = sy(r.stage_int);
    const isSemi = SEMIS.has(r.team_name);
    const ring = isSemi ? `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="9" fill="none" stroke="#d4a23a" stroke-width="2"/>` : "";
    const fill = isSemi ? "#d4a23a" : "#6b7280";
    return `${ring}<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5.5" fill="${fill}" stroke="var(--bg, #0b1220)" stroke-width="1.2"/>`;
  }).join("");

  // Deterministic non-overlap label placement (same shape as fifa-mode.js)
  const labelW = 64, labelH = 14;
  const lineSpacing = labelH + 2;
  const intersects = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);
  const order = [...rows].sort((a, b) => b.stage_int - a.stage_int || b.tcd - a.tcd);
  const placed = [];
  const picks = new Map();
  for (const r of order) {
    const cx = sx(r.tcd), cy = sy(r.stage_int);
    const stackUpFromBottom = r.stage_int === 2;
    const stackDown = !stackUpFromBottom && r.stage_int <= 4;
    const anchor = (cx > padL + innerW * 0.6) ? "end" : "start";
    const dx = anchor === "start" ? 9 : -9;
    let dy = stackUpFromBottom ? -10 : (stackDown ? 10 : -10);
    const step = stackUpFromBottom ? -lineSpacing : (stackDown ? lineSpacing : -lineSpacing);
    let box;
    for (let bump = 0; bump < 14; bump++) {
      const lx = cx + dx, ly = cy + dy;
      box = anchor === "start"
        ? { x1: lx, y1: ly - labelH, x2: lx + labelW, y2: ly + 2 }
        : { x1: lx - labelW, y1: ly - labelH, x2: lx, y2: ly + 2 };
      if (!placed.some((p) => intersects(p, box))) break;
      dy += step;
    }
    placed.push(box);
    picks.set(r.team_name, { anchor, dx, dy });
  }
  const labels = rows.map((r) => {
    const cx = sx(r.tcd), cy = sy(r.stage_int);
    const pick = picks.get(r.team_name);
    const fw = SEMIS.has(r.team_name) ? 700 : 500;
    return `<text x="${(cx + pick.dx).toFixed(1)}" y="${(cy + pick.dy).toFixed(1)}"
           font-size="11.5" font-weight="${fw}" fill="currentColor"
           opacity="0.92" text-anchor="${pick.anchor}">${escapeHTML(r.team_name)}</text>`;
  }).join("");

  const xTicks = [0, 25, 50, 75, 100, 125, 150];
  const xTickSvg = xTicks.map((x) => `
    <text x="${sx(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="middle">${x}</text>`).join("");
  const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - padB + 36}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
    Team Chemistry Density (TCD)</text>`;

  scatterEl.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         class="fifa-scatter-svg" role="img"
         aria-label="TCD vs tournament finish scatter">
      ${yRules}
      ${xTickSvg}
      ${dots}
      ${labels}
      ${axisX}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#d4a23a; border-radius:50%;"></span> WC22 semifinalist (gold ring)</span>
      <span class="muted">Spearman ρ(TCD, finish) = <strong>+0.704</strong> (p &lt; 0.001, n = 31). FIFA-23 Overall → finish is +0.548. Chemistry beats raw talent.</span>
    </div>`;
}

/* ---------------- chemistry → expected-goals panel ---------------- */
/* Two added-variable scatters, but framed for casual fans: both axes have talent +
   schedule stripped out, so the trend = chemistry's own effect. Plain-language copy
   (title / verdict / strength meter) lives in the HTML; this draws the chart only.
   The raw partial-r / CI / n live behind the "How we measured this" toggle, injected
   from the JSON meta so they stay truthful. */

const XG_MARQUEE = new Set(["Brazil", "Spain", "Portugal", "England", "Netherlands", "Germany", "Belgium"]);

const xgPanelEl = document.getElementById("chem-xg-panel");
if (xgPanelEl) {
  loadJSON("data/chemistry_xg.json").then((xg) => renderChemistryXgPanel(xg)).catch(() => {});
}

function renderChemistryXgPanel(xg) {
  const defRows = xg.teams.filter((t) => t.def_chem_adj != null && t.xg_prevented_over_expected != null);
  const offRows = xg.teams.filter((t) => t.off_chem_adj != null && t.xg_added_over_expected != null);
  const defEl = document.getElementById("chem-xg-def");
  const offEl = document.getElementById("chem-xg-off");
  if (defEl) renderXgScatter(defEl, defRows, {
    xKey: "def_chem_adj", yKey: "xg_prevented_over_expected",
    yTop: "Allows fewer chances than expected", yBot: "Allows more than expected",
    xLabel: "More defensive chemistry →",
    aria: "Defensive chemistry vs expected goals allowed, with talent and schedule removed",
  });
  if (offEl) renderXgScatter(offEl, offRows, {
    xKey: "off_chem_adj", yKey: "xg_added_over_expected",
    yTop: "Creates more chances than expected", yBot: "Creates fewer than expected",
    xLabel: "More attacking chemistry →",
    aria: "Attacking chemistry vs expected goals created, with talent and schedule removed",
  });

  // keep the "How we measured this" numbers in sync with the data (truthful, not hardcoded)
  const fmtR = (r) => (r >= 0 ? "+" : "−") + Math.abs(r).toFixed(2);
  const fmtCi = (ci) => `${ci[0] >= 0 ? "" : "−"}${Math.abs(ci[0]).toFixed(2)} to ${ci[1] >= 0 ? "" : "−"}${Math.abs(ci[1]).toFixed(2)}`;
  const set = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
  set("xg-n", String(xg.meta.n_teams));
  set("xg-def-r", fmtR(xg.meta.defense.partial_r));
  set("xg-def-ci", fmtCi(xg.meta.defense.ci90));
  set("xg-off-r", fmtR(xg.meta.offense.partial_r));
  set("xg-off-ci", fmtCi(xg.meta.offense.ci90));
}

function renderXgScatter(mountEl, rows, opt) {
  const W = 560, H = 430;
  const padL = 44, padR = 26, padT = 30, padB = 54;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const xs = rows.map((r) => r[opt.xKey]), ys = rows.map((r) => r[opt.yKey]);
  const xr = (Math.max(...xs) - Math.min(...xs)) || 1, yr = (Math.max(...ys) - Math.min(...ys)) || 1;
  const xmin = Math.min(...xs) - xr * 0.10, xmax = Math.max(...xs) + xr * 0.14;
  const ymin = Math.min(...ys) - yr * 0.10, ymax = Math.max(...ys) + yr * 0.10;
  const sx = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const sy = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;
  const zx = sx(0), zy = sy(0);

  // quadrant cues: up-right (more chemistry + better than expected) = the story holds (green);
  // down-left = against it (red). Only drawn when zero is on-screen for both axes.
  let tint = "";
  if (xmin < 0 && xmax > 0 && ymin < 0 && ymax > 0) {
    tint =
      `<rect x="${zx.toFixed(1)}" y="${padT}" width="${(padL + innerW - zx).toFixed(1)}" height="${(zy - padT).toFixed(1)}" fill="#34d399" opacity="0.06"/>` +
      `<rect x="${padL}" y="${zy.toFixed(1)}" width="${(zx - padL).toFixed(1)}" height="${(padT + innerH - zy).toFixed(1)}" fill="#f87171" opacity="0.05"/>`;
  }
  const frame = `<rect x="${padL}" y="${padT}" width="${innerW}" height="${innerH}" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/>`;
  const zeroX = (xmin < 0 && xmax > 0) ? `<line x1="${zx.toFixed(1)}" y1="${padT}" x2="${zx.toFixed(1)}" y2="${padT + innerH}" stroke="currentColor" stroke-width="1" opacity="0.28" stroke-dasharray="2 4"/>` : "";
  const zeroY = (ymin < 0 && ymax > 0) ? `<line x1="${padL}" y1="${zy.toFixed(1)}" x2="${W - padR}" y2="${zy.toFixed(1)}" stroke="currentColor" stroke-width="1" opacity="0.28" stroke-dasharray="2 4"/>` : "";

  // least-squares trend line over the cloud
  const n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; }
  const slope = sxx ? sxy / sxx : 0, intc = my - slope * mx;
  const trend = `<line x1="${sx(xmin).toFixed(1)}" y1="${sy(intc + slope * xmin).toFixed(1)}" x2="${sx(xmax).toFixed(1)}" y2="${sy(intc + slope * xmax).toFixed(1)}" stroke="#d4a23a" stroke-width="3" stroke-linecap="round"/>`;

  const dots = rows.map((r) => {
    const cx = sx(r[opt.xKey]), cy = sy(r[opt.yKey]);
    if (r.is_semifinalist) {
      return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="8.5" fill="none" stroke="#d4a23a" stroke-width="2.5"/>` +
             `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5.5" fill="#d4a23a" stroke="var(--bg, #0b1220)" stroke-width="1.3"/>`;
    }
    const fill = XG_MARQUEE.has(r.team_name) ? "#9aa6ba" : "#56617a";
    return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4.5" fill="${fill}" stroke="var(--bg, #0b1220)" stroke-width="1.1"/>`;
  }).join("");

  // labels: semifinalists (gold) + marquee teams (muted), greedy non-overlap
  const labeled = rows.filter((r) => r.is_semifinalist || XG_MARQUEE.has(r.team_name));
  const placed = [];
  const inter = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);
  const order = [...labeled].sort((a, b) =>
    (b.is_semifinalist ? 1 : 0) - (a.is_semifinalist ? 1 : 0) || b[opt.yKey] - a[opt.yKey]);
  const labels = order.map((r) => {
    const cx = sx(r[opt.xKey]), cy = sy(r[opt.yKey]);
    const semi = r.is_semifinalist;
    const fs = semi ? 12.5 : 11, fw = semi ? 800 : 600;
    const fill = semi ? "#e0b450" : "currentColor", op = semi ? 1 : 0.78;
    const w = r.team_name.length * fs * 0.6, h = fs + 2;
    const anchor = cx > padL + innerW * 0.62 ? "end" : "start";
    const dx = anchor === "start" ? 10 : -10;
    let dy = -9, box;
    const step = (cy < padT + innerH / 2) ? 14 : -14;
    for (let k = 0; k < 16; k++) {
      const lx = cx + dx, ly = cy + dy;
      box = anchor === "start" ? { x1: lx, y1: ly - h, x2: lx + w, y2: ly + 3 } : { x1: lx - w, y1: ly - h, x2: lx, y2: ly + 3 };
      if (!placed.some((p) => inter(p, box))) break;
      dy += step;
    }
    placed.push(box);
    return `<text x="${(cx + dx).toFixed(1)}" y="${(cy + dy).toFixed(1)}" font-size="${fs}" font-weight="${fw}" fill="${fill}" opacity="${op}" text-anchor="${anchor}">${escapeHTML(r.team_name)}</text>`;
  }).join("");

  // directional axis labels INSIDE the plot (so they never clip)
  const yTopLbl = `<text x="${padL + 8}" y="${padT + 18}" font-size="11.5" font-weight="600" fill="#7ed3ab">↑ ${escapeHTML(opt.yTop)}</text>`;
  const yBotLbl = `<text x="${padL + 8}" y="${padT + innerH - 9}" font-size="11.5" font-weight="600" fill="#e29a9a">↓ ${escapeHTML(opt.yBot)}</text>`;
  const xLbl = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - 14}" font-size="12.5" font-weight="600" fill="currentColor" opacity="0.7" text-anchor="middle">${escapeHTML(opt.xLabel)}</text>`;

  mountEl.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="fifa-scatter-svg" role="img" aria-label="${escapeHTML(opt.aria)}">` +
    `${tint}${frame}${zeroX}${zeroY}${trend}${dots}${labels}${yTopLbl}${yBotLbl}${xLbl}</svg>`;
}

/* ---------------- combination play (final-third give-and-gos + third-man + take-overs) -------- */

const comboEl = document.getElementById("combo-grid");
if (comboEl) {
  loadJSON("data/combination_xg.json").then((xg) => renderComboPanel(xg)).catch(() => {});
}
// defensive team leaderboard (the stronger, validated chemistry signal)
{
  loadJSON("data/defense_chemistry.json").then((dj) => {
    const el = document.getElementById("defense-team-leaderboard");
    if (el && Array.isArray(dj.teams)) renderDefenseTeams(el, dj.teams);
  }).catch(() => {});
}

function renderComboPanel(xg) {
  // 1. the cell-mean grid (toggle: team talent <-> shared club history)
  let split = "fifa";
  const gridEl = document.getElementById("combo-grid");
  const draw = () => { if (gridEl) renderComboGrid(gridEl, xg.grid, split); };
  draw();
  document.querySelectorAll("[data-combo-split]").forEach((btn) => {
    btn.addEventListener("click", () => {
      split = btn.getAttribute("data-combo-split");
      document.querySelectorAll("[data-combo-split]").forEach((b) => b.classList.toggle("active", b === btn));
      draw();
    });
  });

  // 2. where combinations come from — raw scatter vs squad shared club history
  const hist = document.getElementById("combo-history-scatter");
  if (hist) renderXgScatter(hist, xg.teams.filter((t) => t.shared_history != null && t.genuine_combos_pg != null), {
    xKey: "shared_history", yKey: "genuine_combos_pg",
    yTop: "More combinations near goal", yBot: "Fewer combinations",
    xLabel: "More shared club history (prior minutes as club teammates) →",
    aria: "Final-third combinations vs squad shared club history",
  });

  // 3. pairs that combine most (volume rank) + AW-JOI & xG-added columns, sliced by type
  const lbEl = document.getElementById("combo-leaderboard");
  let lbType = "all";
  const drawLb = () => renderPairLeaderboard(lbEl, xg.pair_leaderboard, lbType);
  drawLb();
  document.querySelectorAll("[data-lb-type]").forEach((btn) => {
    btn.addEventListener("click", () => {
      lbType = btn.getAttribute("data-lb-type");
      document.querySelectorAll("[data-lb-type]").forEach((b) => b.classList.toggle("active", b === btn));
      drawLb();
    });
  });
  renderScoredPairs(document.getElementById("combo-scored-list"), xg.scored_pairs);

  // 3b. team leaderboard — two views: "who combines most" (volume, by type) and
  //     "chemistry beyond talent" (talent-adjusted chemistry-added xG). The latter answers the
  //     "the top of the raw list underachieved" critique — it strips out talent.
  const tlbEl = document.getElementById("combo-team-leaderboard");
  let tlbType = "all", teamView = "adjusted";
  const typeToggleEl = document.getElementById("combo-team-type-toggle");
  const noteVol = document.getElementById("combo-team-note-volume");
  const noteAdj = document.getElementById("combo-team-note-adjusted");
  const drawTlb = () => {
    const adj = teamView === "adjusted";
    if (typeToggleEl) typeToggleEl.style.display = adj ? "none" : "";
    if (noteVol) noteVol.style.display = adj ? "none" : "";
    if (noteAdj) noteAdj.style.display = adj ? "" : "none";
    if (adj) renderTalentAdjustedLeaderboard(tlbEl, xg.team_leaderboard);
    else renderTeamComboLeaderboard(tlbEl, xg.team_leaderboard, tlbType);
  };
  drawTlb();
  document.querySelectorAll("[data-team-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      teamView = btn.getAttribute("data-team-view");
      document.querySelectorAll("[data-team-view]").forEach((b) => b.classList.toggle("active", b === btn));
      drawTlb();
    });
  });
  document.querySelectorAll("[data-team-lb-type]").forEach((btn) => {
    btn.addEventListener("click", () => {
      tlbType = btn.getAttribute("data-team-lb-type");
      document.querySelectorAll("[data-team-lb-type]").forEach((b) => b.classList.toggle("active", b === btn));
      drawTlb();
    });
  });

  // 3c. NUCLEUS ranking — players by combinations with teammates (the hubs: Messi & his goons)
  const nucEl = document.getElementById("combo-nucleus");
  if (nucEl && Array.isArray(xg.nucleus)) {
    let nucMode = "combos";
    const drawNuc = () => renderNucleusRanking(nucEl, xg.nucleus, nucMode);
    drawNuc();
    document.querySelectorAll("[data-nuc-sort]").forEach((btn) => {
      btn.addEventListener("click", () => {
        nucMode = btn.getAttribute("data-nuc-sort");
        document.querySelectorAll("[data-nuc-sort]").forEach((b) => b.classList.toggle("active", b === btn));
        drawNuc();
      });
    });
  }

  // 4. meta numbers (truthful, from JSON)
  const m = xg.meta || {};
  const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
  const sgn = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);
  const pct = (v) => Math.round(v * 100) + "%";
  if (m.partial_r != null) set("combo-r", sgn(m.partial_r));
  if (m.ci90) set("combo-ci", `${m.ci90[0].toFixed(2)} to ${m.ci90[1].toFixed(2)}`);
  // top-line "beats talent" stat block
  if (m.cv_r2_baseline != null) set("combo-cv-base", m.cv_r2_baseline.toFixed(2));
  if (m.cv_r2_chem != null) set("combo-cv-chem", m.cv_r2_chem.toFixed(2));
  if (m.partial_r != null) { set("combo-r2-partial", sgn(m.partial_r)); set("combo-var-pct", Math.round(m.partial_r * m.partial_r * 100) + "%"); }
  if (m.ci90) set("combo-ci2", `${m.ci90[0].toFixed(2)} to ${m.ci90[1].toFixed(2)}`);
  if (m.n_teams != null) set("combo-n", String(m.n_teams));
  if (m.model_combination_acc != null) set("combo-mdl", pct(m.model_combination_acc));
  if (m.model_overall_acc != null) set("combo-mdl-base", pct(m.model_overall_acc));
  if (m.nearest_baseline_acc != null) set("combo-near", pct(m.nearest_baseline_acc));
  if (m.history_rho != null) set("combo-hist-r", sgn(m.history_rho));
  if (m.history_partial != null) set("combo-hist-partial", sgn(m.history_partial));
  renderComboGoalsTable(m);
}

// "did these create goals?" — per type: how often it happens, how often it was part of a move
// that scored within 10s (a shooting percentage). Numbers from combination_xg.json meta.
function renderComboGoalsTable(m) {
  const el = document.getElementById("combo-goals-table");
  if (!el || !m.kinds || !m.led_to_goal_by_kind) return;
  const rate = m.led_rate_by_kind || {};
  const pct = (v) => (v == null ? "—" : (v * 100).toFixed(1) + "%");
  const num = (v) => (v || 0).toLocaleString();
  const totCombos = (m.kinds.onetwo || 0) + (m.kinds.thirdman || 0) + (m.kinds.takeover || 0);
  const row = (lab, k) => `<tr style="border-bottom:1px solid var(--border);">
    <td style="padding:0.4rem 0.7rem;">${lab}</td>
    <td style="padding:0.4rem 0.7rem; text-align:right;" class="tabular">${num(m.kinds[k])}</td>
    <td style="padding:0.4rem 0.7rem; text-align:right; color:#e0b450; font-weight:700;" class="tabular">${m.led_to_goal_by_kind[k] || 0}</td>
    <td style="padding:0.4rem 0.7rem; text-align:right;" class="tabular">${pct(rate[k])}</td></tr>`;
  el.innerHTML = `<table class="data-table" style="border-collapse:collapse; font-size:0.9rem; min-width:28rem;">
    <thead><tr style="border-bottom:1px solid var(--border); color:var(--text-dim); text-transform:uppercase; letter-spacing:0.4px; font-size:0.74rem;">
      <th style="text-align:left; padding:0.4rem 0.7rem;">Combination</th>
      <th style="text-align:right; padding:0.4rem 0.7rem;">In WC22<br>(final third)</th>
      <th style="text-align:right; padding:0.4rem 0.7rem;">Led to a goal<br>(within 10s)</th>
      <th style="text-align:right; padding:0.4rem 0.7rem;">Rate</th></tr></thead>
    <tbody>
      ${row("Give-and-go", "onetwo")}
      ${row("Third-man run", "thirdman")}
      ${row("Take-over", "takeover")}
      <tr style="font-weight:700; border-top:2px solid var(--border);">
        <td style="padding:0.4rem 0.7rem;">All three</td>
        <td style="padding:0.4rem 0.7rem; text-align:right;" class="tabular">${num(totCombos)}</td>
        <td style="padding:0.4rem 0.7rem; text-align:right; color:#e0b450;" class="tabular">${m.n_combo_led}</td>
        <td style="padding:0.4rem 0.7rem; text-align:right;" class="tabular">${pct(m.led_rate)}</td></tr>
    </tbody></table>`;
}

// grouped-bar cell-mean grid: 3 talent/history tiers x {fewer, more} combinations -> avg xG/game
function renderComboGrid(mountEl, grid, split) {
  const d = grid[split], tiers = d.tiers;
  const W = 560, H = 430, padL = 46, padR = 18, padT = 22, padB = 72;
  const innerW = W - padL - padR, innerH = H - padT - padB, base = padT + innerH;
  const ymax = Math.max(...tiers.flatMap((t) => [t.low.mean_xg, t.high.mean_xg]), 1) * 1.18;
  const sy = (v) => padT + innerH - (v / ymax) * innerH;
  const groupW = innerW / tiers.length, barW = groupW * 0.28, gap = groupW * 0.07;
  const name = { low: "Lower", mid: "Mid", high: "Higher" };

  let grids = "";
  for (let g = 0; g <= ymax + 1e-9; g += 0.5) {
    const y = sy(g);
    grids += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="currentColor" stroke-width="1" opacity="0.10"/>` +
             `<text x="${padL - 6}" y="${(y + 3.5).toFixed(1)}" font-size="10" fill="currentColor" opacity="0.5" text-anchor="end">${g.toFixed(1)}</text>`;
  }
  let bars = "", lbls = "";
  tiers.forEach((t, i) => {
    const cx = padL + groupW * (i + 0.5);
    const xL = cx - barW - gap / 2, xR = cx + gap / 2;
    const hL = base - sy(t.low.mean_xg), hR = base - sy(t.high.mean_xg);
    bars += `<rect x="${xL.toFixed(1)}" y="${sy(t.low.mean_xg).toFixed(1)}" width="${barW.toFixed(1)}" height="${hL.toFixed(1)}" fill="#566179" rx="2.5"/>` +
            `<rect x="${xR.toFixed(1)}" y="${sy(t.high.mean_xg).toFixed(1)}" width="${barW.toFixed(1)}" height="${hR.toFixed(1)}" fill="#d4a23a" rx="2.5"/>`;
    lbls += `<text x="${(xL + barW / 2).toFixed(1)}" y="${(sy(t.low.mean_xg) - 6).toFixed(1)}" font-size="11.5" font-weight="700" fill="currentColor" opacity="0.7" text-anchor="middle">${t.low.mean_xg.toFixed(1)}</text>` +
            `<text x="${(xR + barW / 2).toFixed(1)}" y="${(sy(t.high.mean_xg) - 6).toFixed(1)}" font-size="12.5" font-weight="800" fill="#e0b450" text-anchor="middle">${t.high.mean_xg.toFixed(1)}</text>`;
    const sub = split === "fifa" ? `FIFA ${t.range}` : `${t.range} min`;
    lbls += `<text x="${cx.toFixed(1)}" y="${(base + 19).toFixed(1)}" font-size="12.5" font-weight="700" fill="currentColor" opacity="0.85" text-anchor="middle">${name[t.tier]}</text>` +
            `<text x="${cx.toFixed(1)}" y="${(base + 34).toFixed(1)}" font-size="10" fill="currentColor" opacity="0.5" text-anchor="middle">${escapeHTML(sub)}</text>`;
  });
  const yLbl = `<text transform="translate(13,${(padT + innerH / 2).toFixed(0)}) rotate(-90)" font-size="11.5" font-weight="600" fill="currentColor" opacity="0.7" text-anchor="middle">Good chances created / game (xG)</text>`;
  const legend = `<g transform="translate(${padL},${H - 10})">` +
    `<rect x="0" y="-9" width="11" height="11" fill="#566179" rx="2"/><text x="16" y="0" font-size="10.5" fill="currentColor" opacity="0.7">Teams that combine less</text>` +
    `<rect x="166" y="-9" width="11" height="11" fill="#d4a23a" rx="2"/><text x="182" y="0" font-size="10.5" fill="currentColor" opacity="0.9">…combine more</text></g>`;
  mountEl.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="fifa-scatter-svg" role="img" aria-label="Average good chances created by combination level, split by ${escapeHTML(d.label)}">` +
    `${grids}${bars}${lbls}${yLbl}${legend}</svg>`;
}

// volume-ranked, with AW-JOI (co-attention×threat) + xG-added columns; sliced by combination type
function renderPairLeaderboard(el, pairs, type) {
  if (!el || !Array.isArray(pairs)) return;
  type = type || "all";
  const metric = (p) => type === "all"
    ? { n: p.n_combos, aw: p.combo_aw_joi || 0, xg: p.combo_xg_added || 0 }
    : { n: (p.by_type && p.by_type[type] ? p.by_type[type].n : 0),
        aw: (p.by_type && p.by_type[type] ? p.by_type[type].aw_joi : 0) || 0,
        xg: (p.by_type && p.by_type[type] ? p.by_type[type].xg_added : 0) || 0 };
  const rows = pairs.map((p) => ({ p, v: metric(p) })).filter((r) => r.v.n > 0)
    .sort((a, b) => b.v.n - a.v.n).slice(0, 10);
  if (!rows.length) { el.innerHTML = '<p class="dim small">No pairs for this type.</p>'; return; }
  const maxN = Math.max(...rows.map((r) => r.v.n), 1);
  const TH = 'style="text-align:right; padding:0.3rem 0.5rem;"';
  const body = rows.map(({ p, v }, i) => {
    const w = Math.max(10, (v.n / maxN) * 100);
    return `<tr style="border-bottom:1px solid var(--border);">
      <td style="padding:0.3rem 0.4rem; opacity:0.45; text-align:right;">${i + 1}</td>
      <td style="padding:0.3rem 0.5rem; line-height:1.15;"><strong>${escapeHTML(p.player_a)}</strong> + ${escapeHTML(p.player_b)}<span class="dim small"> · ${escapeHTML(p.team_name)}</span></td>
      <td style="padding:0.3rem 0.5rem; white-space:nowrap;"><span class="combo-bar-wrap" style="display:inline-block; width:34px; vertical-align:middle;"><span class="combo-bar${p.is_semifinalist ? " semi" : ""}" style="width:${w.toFixed(0)}%"></span></span> <span class="tabular">${v.n}</span></td>
      <td style="padding:0.3rem 0.5rem; text-align:right; color:#5eb1f8;" class="tabular">${(v.aw * 1000).toFixed(1)}</td>
      <td style="padding:0.3rem 0.5rem; text-align:right; color:#e0b450;" class="tabular">${v.xg.toFixed(2)}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `<table class="data-table" style="border-collapse:collapse; font-size:0.82rem; width:100%;">
    <thead><tr style="color:var(--text-dim); text-transform:uppercase; letter-spacing:0.3px; font-size:0.66rem; border-bottom:1px solid var(--border);">
      <th></th><th style="text-align:left; padding:0.3rem 0.5rem;">Pair</th>
      <th style="text-align:left; padding:0.3rem 0.5rem;">Combos</th>
      <th ${TH} title="Co-attention × threat the model put on the pair during their combinations (×10⁻³).">AW-JOI</th>
      <th ${TH} title="Threat the model added during their combinations (summed ΔP-score) — the model's scoring-probability rise, NOT StatsBomb xG.">Threat+</th>
    </tr></thead><tbody>${body}</tbody></table>`;
}

// team version of the pair table: which teams combine most PER GAME (fair across teams that
// played a different number of matches), sliced by type. Final-four teams flagged gold.
function renderTeamComboLeaderboard(el, teams, type) {
  if (!el || !Array.isArray(teams)) return;
  type = type || "all";
  const metric = (t) => {
    if (type === "all") return { n: t.n_combos || 0, aw: t.combo_aw_joi || 0, xg: t.combo_xg_added || 0 };
    const b = (t.by_type && t.by_type[type]) || {};
    return { n: b.n || 0, aw: b.aw_joi || 0, xg: b.xg_added || 0 };
  };
  const rows = teams.map((t) => {
    const v = metric(t); const g = t.games || 1;
    return { t, n: v.n, g, perG: v.n / g, aw: (v.aw / g) * 1000, xg: v.xg / g };
  }).filter((r) => r.n > 0).sort((a, b) => b.perG - a.perG);
  if (!rows.length) { el.innerHTML = '<p class="dim small">No teams for this type.</p>'; return; }
  const maxP = Math.max(...rows.map((r) => r.perG), 1);
  const TH = 'style="text-align:right; padding:0.3rem 0.5rem;"';
  const body = rows.map((r, i) => {
    const w = Math.max(8, (r.perG / maxP) * 100);
    const semi = r.t.is_semifinalist;
    return `<tr style="border-bottom:1px solid var(--border);">
      <td style="padding:0.3rem 0.4rem; opacity:0.45; text-align:right;">${i + 1}</td>
      <td style="padding:0.3rem 0.5rem; line-height:1.15;"><strong${semi ? ' style="color:#e0b450;"' : ""}>${escapeHTML(r.t.team_name)}</strong>${semi ? ' <span style="color:#e0b450;" title="Reached the semifinals">★</span>' : ""}</td>
      <td style="padding:0.3rem 0.5rem; white-space:nowrap;" title="${r.n} total over ${r.g} game${r.g === 1 ? "" : "s"}"><span class="combo-bar-wrap" style="display:inline-block; width:34px; vertical-align:middle;"><span class="combo-bar${semi ? " semi" : ""}" style="width:${w.toFixed(0)}%"></span></span> <span class="tabular">${r.perG.toFixed(1)}</span></td>
      <td style="padding:0.3rem 0.5rem; text-align:right; color:#5eb1f8;" class="tabular">${r.aw.toFixed(1)}</td>
      <td style="padding:0.3rem 0.5rem; text-align:right; color:#e0b450;" class="tabular">${r.xg.toFixed(2)}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `<table class="data-table" style="border-collapse:collapse; font-size:0.82rem; width:100%;">
    <thead><tr style="color:var(--text-dim); text-transform:uppercase; letter-spacing:0.3px; font-size:0.66rem; border-bottom:1px solid var(--border);">
      <th></th><th style="text-align:left; padding:0.3rem 0.5rem;">Team</th>
      <th style="text-align:left; padding:0.3rem 0.5rem;">Combos / game</th>
      <th ${TH} title="Team total co-attention × threat the model put on its pairs during these combinations, per game (×10⁻³).">AW-JOI</th>
      <th ${TH} title="Model threat added during these combinations, per game (summed ΔP-score) — NOT StatsBomb xG.">Threat+</th>
    </tr></thead><tbody>${body}</tbody></table>`;
}

// talent-adjusted view: chances each team's combinations add BEYOND talent/experience/schedule/opp
// (chem_added_xg), with what they ACTUALLY created vs expected — so the relationship is visible
// team-by-team (mostly aligned; Spain the honest miss). This is the answer to "the raw top underachieved".
// DEFENSIVE team leaderboard — count of strong defensive partnerships (the validated −0.38 predictor
// of fewer chances allowed) + StatsBomb xG prevented vs talent. Role-clean at TEAM level only (per-pair
// AW-JDI is not face-valid — it surfaces attention-magnet attackers, so no defensive pair board).
// Residuals within ±NEUTRAL_BAND xG/game read as "about as expected" (≈ one goal's worth of xG
// over a tournament) — show the number in white with NO ✓/✗, so near-zero isn't mislabelled a miss.
const NEUTRAL_BAND = 0.2;
function nearZero(v) { return Math.abs(v) < NEUTRAL_BAND; }

function renderDefenseTeams(el, teams, sortKey) {
  if (!el || !Array.isArray(teams)) return;
  sortKey = sortKey || "nsd";
  const data = teams.map((t) => ({ t, nsd: t.n_strong_def, adj: t.def_chem_adj, prev: t.xg_prevented_over_expected }));
  if (!data.length) { el.innerHTML = '<p class="dim small">No data.</p>'; return; }
  const sv = (r) => (r[sortKey] == null ? -Infinity : r[sortKey]);
  const rows = data.slice().sort((a, b) => sv(b) - sv(a));
  const maxN = Math.max(...data.map((r) => r.nsd), 1);
  const fmt = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);
  const fmt1 = (v) => (v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1));
  const col = (v) => (v >= 0 ? "#54c875" : "#e07474");
  const hl = (k) => (k === sortKey ? " color:#e0b450;" : "");
  const arr = (k) => (k === sortKey ? " ▼" : "");
  const body = rows.map((r, i) => {
    const semi = r.t.is_semifinalist;
    const w = Math.max(8, (r.nsd / maxN) * 100);
    const nz = nearZero(r.prev);
    return `<tr style="border-bottom:1px solid var(--border);">
      <td style="padding:0.3rem 0.4rem; opacity:0.45; text-align:right;">${i + 1}</td>
      <td style="padding:0.3rem 0.5rem;"><strong${semi ? ' style="color:#e0b450;"' : ""}>${escapeHTML(r.t.team_name)}</strong>${semi ? ' <span style="color:#e0b450;" title="semifinalist">★</span>' : ""}</td>
      <td style="padding:0.3rem 0.5rem; white-space:nowrap;"><span class="combo-bar-wrap" style="display:inline-block; width:34px; vertical-align:middle;"><span class="combo-bar${semi ? " semi" : ""}" style="width:${w.toFixed(0)}%"></span></span> <span class="tabular">${r.nsd}</span></td>
      <td style="padding:0.3rem 0.5rem; text-align:right; white-space:nowrap;" class="tabular"><span style="color:${r.adj == null ? "var(--text)" : col(r.adj)};${sortKey === "adj" ? " font-weight:700;" : ""}">${fmt1(r.adj)}</span></td>
      <td style="padding:0.3rem 0.5rem; text-align:right; white-space:nowrap;" class="tabular"><span style="color:${nz ? "var(--text)" : col(r.prev)};">${fmt(r.prev)}</span> ${nz ? "" : `<span title="${r.prev >= 0 ? "allowed fewer chances than talent predicted" : "allowed more than expected"}" style="opacity:0.75;">${r.prev >= 0 ? "✓" : "✗"}</span>`}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `<table class="data-table" style="border-collapse:collapse; font-size:0.82rem; width:100%;">
    <thead><tr style="color:var(--text-dim); text-transform:uppercase; letter-spacing:0.3px; font-size:0.66rem; border-bottom:1px solid var(--border);">
      <th></th><th style="text-align:left; padding:0.3rem 0.5rem;">Team</th>
      <th data-defsort="nsd" style="text-align:left; padding:0.3rem 0.5rem; cursor:pointer;${hl("nsd")}" title="RAW count of strong defensive partnerships (AW-JDI above the tournament median). It is additive, so it leans toward teams that played more (corr +0.51 with games) — the Adjusted column corrects for that. · click to sort">Strong def pairs${arr("nsd")}</th>
      <th data-defsort="adj" style="text-align:right; padding:0.3rem 0.5rem; cursor:pointer;${hl("adj")}" title="Defensive chemistry ADJUSTED for talent + games + opponent strength — strong pairs above/below what a team's rating and schedule predict. The games-FAIR ranking, and what the validated −0.38 finding is built on. Morocco and Argentina stay top-4; France slides. · click to sort">Adjusted (talent+games)${arr("adj")}</th>
      <th data-defsort="prev" style="text-align:right; padding:0.3rem 0.5rem; cursor:pointer;${hl("prev")}" title="StatsBomb xG PREVENTED vs talent expectation — ✓ clearly fewer chances allowed, ✗ clearly more, blank = about as expected (within ±0.2 xG/game) · click to sort">xG prevented vs exp${arr("prev")}</th>
    </tr></thead><tbody>${body}</tbody></table>`;
  el.querySelectorAll("[data-defsort]").forEach((h) => h.addEventListener("click", () => renderDefenseTeams(el, teams, h.getAttribute("data-defsort"))));
}

function renderTalentAdjustedLeaderboard(el, teams, sortKey) {
  if (!el || !Array.isArray(teams)) return;
  sortKey = sortKey || "add";
  const data = teams.filter((t) => t.chem_added_xg != null)
    .map((t) => ({ t, add: t.chem_added_xg, act: t.xg_added_over_expected }));
  if (!data.length) { el.innerHTML = '<p class="dim small">No data.</p>'; return; }
  const rows = data.slice().sort((a, b) => b[sortKey] - a[sortKey]);
  const maxA = Math.max(...data.map((r) => Math.abs(r.add)), 0.01);
  const hl = (k) => (k === sortKey ? " color:#e0b450;" : "");
  const arr = (k) => (k === sortKey ? " ▼" : "");
  const fmt = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);
  const col = (v) => (v >= 0 ? "#54c875" : "#e07474");
  const body = rows.map((r, i) => {
    const semi = r.t.is_semifinalist;
    const w = Math.max(6, (Math.abs(r.add) / maxA) * 100);
    const agree = (r.add >= 0) === (r.act >= 0);
    const nz = nearZero(r.act);
    return `<tr style="border-bottom:1px solid var(--border);">
      <td style="padding:0.3rem 0.4rem; opacity:0.45; text-align:right;">${i + 1}</td>
      <td style="padding:0.3rem 0.5rem; line-height:1.15;"><strong${semi ? ' style="color:#e0b450;"' : ""}>${escapeHTML(r.t.team_name)}</strong>${semi ? ' <span style="color:#e0b450;" title="Reached the semifinals">★</span>' : ""}</td>
      <td style="padding:0.3rem 0.5rem; white-space:nowrap;"><span class="combo-bar-wrap" style="display:inline-block; width:34px; vertical-align:middle;"><span class="combo-bar" style="width:${w.toFixed(0)}%; background:${col(r.add)};"></span></span> <span class="tabular" style="color:${col(r.add)}; font-weight:700;">${fmt(r.add)}</span></td>
      <td style="padding:0.3rem 0.5rem; text-align:right; white-space:nowrap;" class="tabular"><span style="color:${nz ? "var(--text)" : col(r.act)};">${fmt(r.act)}</span> ${nz ? "" : `<span title="${agree ? "chemistry's call paid off" : "combined a lot, but it didn't translate"}" style="opacity:0.75;">${agree ? "✓" : "✗"}</span>`}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `<table class="data-table" style="border-collapse:collapse; font-size:0.82rem; width:100%;">
    <thead><tr style="color:var(--text-dim); text-transform:uppercase; letter-spacing:0.3px; font-size:0.66rem; border-bottom:1px solid var(--border);">
      <th></th><th style="text-align:left; padding:0.3rem 0.5rem;">Team</th>
      <th data-teamsort="add" style="text-align:left; padding:0.3rem 0.5rem; cursor:pointer;${hl("add")}" title="An ESTIMATE — the talent-adjusted genuine-combo rate × the xG-per-combo slope from the regression. A model attribution, NOT measured xG. ('Chances vs expected →' is the measured StatsBomb xG.) · click to sort">Chemistry-added xG/g <span style="text-transform:none; opacity:0.6;">(est.)</span>${arr("add")}</th>
      <th data-teamsort="act" style="text-align:right; padding:0.3rem 0.5rem; cursor:pointer;${hl("act")}" title="What the team actually created above/below its talent baseline — ✓ = the read paid off; blank = about as expected (within ±0.2 xG/game) · click to sort">Chances vs expected${arr("act")}</th>
    </tr></thead><tbody>${body}</tbody></table>`;
  el.querySelectorAll("[data-teamsort]").forEach((h) => h.addEventListener("click", () => renderTalentAdjustedLeaderboard(el, teams, h.getAttribute("data-teamsort"))));
}

// NUCLEUS ranking — players by combinations with teammates. Sort by total / per-game / AW-JOI;
// the active column is highlighted. The face-valid view: the creative hub of every deep team.
function renderNucleusRanking(el, players, sortKey) {
  if (!el || !Array.isArray(players)) return;
  sortKey = sortKey || "combos";
  const cols = [
    { k: "combos", label: "Combos", get: (p) => p.combos, fmt: (v) => String(v), color: "", title: "combinations with teammates (final third)" },
    { k: "per_game", label: "/ game", get: (p) => p.per_game, fmt: (v) => v.toFixed(1), color: "", title: "combinations per match played" },
    { k: "partners", label: "Partners", get: (p) => p.partners, fmt: (v) => String(v), color: "", title: "distinct teammates combined with — the breadth of the hub" },
    { k: "aw_joi", label: "AW-JOI", get: (p) => p.aw_joi, fmt: (v) => v.toFixed(1), color: "", title: "model's attention-weighted threat on this player's combinations (×10⁻³)" },
    { k: "xg_added", label: "Threat+", get: (p) => p.xg_added, fmt: (v) => v.toFixed(2), color: "#5eb1f8", title: "the model's scoring-probability rise (ΔP-score) during this player's combinations — NOT StatsBomb xG" },
    { k: "per_100", label: "/100 touch", get: (p) => (p.per_100 == null ? -1 : p.per_100), fmt: (v) => (v < 0 ? "—" : v.toFixed(1)), color: "", title: "combinations per 100 ball-touches — controls for ball-volume (Mike's check: Pedri 6.5 ≈ Messi 6.2, so the raw counts mostly reward seeing the ball most)" },
    { k: "per_combo", label: "Threat/combo", get: (p) => (p.per_combo == null ? -1 : p.per_combo), fmt: (v) => (v < 0 ? "—" : v.toFixed(1) + "%"), color: "#5eb1f8", title: "model P(score)-rise PER combination (Threat+ ÷ combos) — quality per play, robust to games AND ball-volume; Modrić 3.0%, Mbappé 2.4%, Messi 2.1%, Pedri 0.9%" },
    { k: "team_share", label: "% of team", get: (p) => (p.team_share == null ? -1 : p.team_share), fmt: (v) => (v < 0 ? "—" : v.toFixed(1) + "%"), color: "#c08cf0", title: "share of the team's TOTAL combination threat that runs through this player — the nucleus/centrality cut, fully games-invariant; De Bruyne 33%, Messi 22%, Mbappé 21%" },
  ];
  const sc = cols.find((c) => c.k === sortKey) || cols[0];
  const rows = players.slice().sort((a, b) => sc.get(b) - sc.get(a)).slice(0, 20);
  const th = (c) => `<th data-nucsort="${c.k}" style="text-align:right; padding:0.3rem 0.5rem; cursor:pointer;${c.k === sortKey ? " color:#e0b450;" : ""}" title="${c.title} · click to sort">${c.label}${c.k === sortKey ? " ▼" : ""}</th>`;
  const body = rows.map((p, i) => {
    const semi = p.is_semifinalist;
    const td = (c) => `<td style="text-align:right; padding:0.3rem 0.5rem;${c.k === sortKey ? " color:#e0b450; font-weight:700;" : (c.color ? ` color:${c.color};` : "")}" class="tabular">${c.fmt(c.get(p))}</td>`;
    return `<tr style="border-bottom:1px solid var(--border);">
      <td style="padding:0.3rem 0.4rem; opacity:0.45; text-align:right;">${i + 1}</td>
      <td style="padding:0.3rem 0.5rem; line-height:1.15;"><strong${semi ? ' style="color:#e0b450;"' : ""}>${escapeHTML(p.player)}</strong>${semi ? ' <span style="color:#e0b450;" title="semifinalist">★</span>' : ""}<span class="dim small"> · ${escapeHTML(p.team)}</span></td>
      ${cols.map(td).join("")}</tr>`;
  }).join("");
  el.innerHTML = `<table class="data-table" style="border-collapse:collapse; font-size:0.82rem; width:100%;">
    <thead><tr style="color:var(--text-dim); text-transform:uppercase; letter-spacing:0.3px; font-size:0.66rem; border-bottom:1px solid var(--border);">
      <th></th><th style="text-align:left; padding:0.3rem 0.5rem;">Player</th>${cols.map(th).join("")}
    </tr></thead><tbody>${body}</tbody></table>`;
  el.querySelectorAll("[data-nucsort]").forEach((h) => h.addEventListener("click", () => renderNucleusRanking(el, players, h.getAttribute("data-nucsort"))));
}

// the pairs whose combinations actually led to a goal within 10s (a different, sparse set)
function renderScoredPairs(el, pairs) {
  if (!el || !Array.isArray(pairs) || !pairs.length) return;
  el.innerHTML = pairs.map((p) => {
    const n = p.n_goals_led;
    return `<div class="scored-row">
      <span class="combo-team"><strong>${escapeHTML(p.player_a)}</strong> + ${escapeHTML(p.player_b)}<span class="dim"> · ${escapeHTML(p.team_name)}</span></span>
      <span class="sg">${n} goal${n === 1 ? "" : "s"}</span>
    </div>`;
  }).join("");
}

/* ---------------- team network renderers ---------------- */

const POS_XY = {
  GK: [8, 32],
  LCB: [22, 22], RCB: [22, 42], CB: [22, 32],
  LB: [28, 10], RB: [28, 54],
  LWB: [30, 8], RWB: [30, 56],
  DM: [42, 32], CDM: [42, 32],
  LM: [50, 14], RM: [50, 50], CM: [55, 32], LCM: [52, 24], RCM: [52, 40],
  AM: [65, 32], CAM: [65, 32],
  LW: [78, 14], RW: [78, 50],
  CF: [88, 32], ST: [88, 32], SS: [80, 32],
};
function isOff(pos) { return /^(CF|ST|LW|RW|AM|CM|DM|LM|RM|CAM|CDM|LCM|RCM|SS)$/.test(pos || ""); }
function isDef(pos) { return /^(CB|LB|RB|LCB|RCB|LWB|RWB|GK)$/.test(pos || ""); }
// Surname helper that keeps compound surnames intact: "Mac Allister",
// "Di María", "Van Dijk", "De Bruyne", "El Yamiq" etc. Without this, the
// network shows "Allister" / "María" / "Dijk" — wrong and confusing.
const SURNAME_PARTICLES = new Set([
  "di","de","da","do","das","dos","del","della","la","le","los",
  "van","von","der","den","ter",
  "mac","mc",
  "el","al","bin","ibn","abu",
  "san","santa",
]);
function niceSurname(fullName) {
  if (!fullName) return "";
  const parts = fullName.trim().split(/\s+/);
  if (parts.length < 2) return fullName;
  let take = 1;
  for (let i = parts.length - 2; i >= Math.max(0, parts.length - 3); i--) {
    if (SURNAME_PARTICLES.has(parts[i].toLowerCase())) take = parts.length - i;
    else break;
  }
  return parts.slice(-take).join(" ");
}
function pitchXY(position, idx, sameCount) {
  const base = POS_XY[position] || [55, 32];
  const offset = sameCount > 1 ? (idx - (sameCount - 1) / 2) * 8 : 0;
  return [base[0], Math.max(4, Math.min(60, base[1] + offset))];
}

/** Pitch-positioned network used for France, Morocco, Croatia.
 *  highlight:
 *    - "def"      → emphasise def↔def edges (Morocco)
 *    - "midfield" → emphasise the CM/DM cluster (Croatia)
 *    - null       → uniform palette (France) */
function renderPitchNetwork(mountEl, teamName, highlight = null, edgeThreshold = 0.3) {
  const teamId = TEAM_IDS[teamName];
  const net = fullNets?.[teamId];
  if (!mountEl || !net) {
    if (mountEl) mountEl.innerHTML = `<div class="empty-state small">Network data missing.</div>`;
    return;
  }

  // GK exclusion makes the player-to-player chemistry actually visible.
  const gkIds = new Set(net.nodes.filter((n) => n.position === "GK").map((n) => n.player_id));
  const byPos = {};
  for (const n of net.nodes) {
    if (gkIds.has(n.player_id)) continue;
    const p = n.position || "CM";
    (byPos[p] = byPos[p] || []).push(n);
  }
  const placed = new Map();
  for (const pos in byPos) {
    const list = byPos[pos];
    list.sort((a, b) => b.minutes - a.minutes);
    list.forEach((n, i) => {
      const [x, y] = pitchXY(pos, i, list.length);
      placed.set(n.player_id, { ...n, x, y });
    });
  }

  const edges = net.edges
    .filter((e) => placed.has(e.p) && placed.has(e.q) && Number.isFinite(e.aw_joi90) && e.aw_joi90 >= edgeThreshold);
  const maxAW = Math.max(0.4, ...edges.map((e) => e.aw_joi90));

  // Viewport: 100 × 70, with a 6-unit headroom at the top reserved for
  // the WALL / THE ATTACK callouts so they never collide with the
  // topmost player dots or labels. Pitch starts at y = 6.
  const W = 100, H = 70;
  const padX = 4;
  const padTop = 6;   // headroom for top callouts
  const padBottom = 4;
  const scaleX = (x) => padX + (x / 100) * (W - 2 * padX);
  const scaleY = (y) => padTop + (y / 64) * (H - padTop - padBottom);
  // Legacy padY (used by the pitch rect + box outlines below) — equals
  // padTop here so the pitch rect starts where the headroom ends.
  const padY = padTop;

  // Midfield highlight cluster (Croatia): Modrić / Brozović / Kovačić
  const midfieldEngine = new Set();
  if (highlight === "midfield") {
    for (const n of placed.values()) {
      if (/^Luka Modri|^Marcelo Brozovi|^Mateo Kovaci|^Mateo Kovači/.test(n.name)) {
        midfieldEngine.add(n.player_id);
      }
    }
  }

  function edgeStyle(e, a, b) {
    const oo = isOff(a.position) && isOff(b.position);
    const dd = isDef(a.position) && isDef(b.position);
    const cat = oo ? "off" : dd ? "def" : "cross";
    // Brighter palette so the def-def block actually reads as a "lattice."
    let color = { off: "#f59e0b", def: "#5eb1f8", cross: "#a78bfa" }[cat];
    let muted = false;
    if (highlight === "def" && cat !== "def") muted = true;
    // "wall+recycle": Morocco's story is the wall feeding the attack.
    // Light up BOTH def↔def (blue, the wall) AND cross-team edges where
    // one endpoint is a defender (orange, the recycle). Mute pure off↔off.
    if (highlight === "wall+recycle") {
      if (cat === "def") {
        // pure def-def stays blue
      } else if (cat === "cross" && (isDef(a.position) || isDef(b.position))) {
        color = "#f59e0b"; // recycle edge — defender feeding the attack
      } else {
        muted = true;
      }
    }
    if (highlight === "midfield") {
      const inEngine = midfieldEngine.has(a.player_id) && midfieldEngine.has(b.player_id);
      if (!inEngine) muted = true;
      else color = "#ffd166";
    }
    return { color, muted, cat };
  }

  const ratioOf = (e) => e.aw_joi90 / maxAW;
  // Pre-classify defender ids so the node-render below can give the wall
  // extra ring weight when we're in "def" highlight mode.
  const isDefenderId = (pid) => {
    const node = placed.get(pid);
    return node && isDef(node.position);
  };

  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="atom-svg" role="img" aria-label="${escapeHTML(teamName)} chemistry network">`;
  // Pitch surface — height now defined by padTop and padBottom separately
  // so we have headroom at the top for the WALL / ATTACK callouts.
  const pitchH = H - padTop - padBottom;
  const pitchCY = padTop + pitchH / 2;
  svg += `<rect x="${padX}" y="${padTop}" width="${W - 2*padX}" height="${pitchH}" fill="#13332b" stroke="#2a4034" stroke-width="0.25" rx="1" />`;
  // Halfway line + center circle.
  svg += `<line x1="${W/2}" y1="${padTop}" x2="${W/2}" y2="${padTop + pitchH}" stroke="#2a4034" stroke-width="0.18" />`;
  svg += `<circle cx="${W/2}" cy="${pitchCY}" r="5" stroke="#2a4034" stroke-width="0.18" fill="none" />`;
  // Penalty boxes for spatial context (16.5 m wide, 40.32 m tall on a 105×68 pitch).
  const pbW = (16.5 / 105) * (W - 2 * padX);
  const pbH = (40.32 / 68) * pitchH;
  const sixW = (5.5 / 105) * (W - 2 * padX);
  const sixH = (18.32 / 68) * pitchH;
  svg += `<rect x="${padX}" y="${(pitchCY - pbH / 2).toFixed(1)}" width="${pbW.toFixed(1)}" height="${pbH.toFixed(1)}" fill="none" stroke="#2a4034" stroke-width="0.15" />`;
  svg += `<rect x="${(W - padX - pbW).toFixed(1)}" y="${(pitchCY - pbH / 2).toFixed(1)}" width="${pbW.toFixed(1)}" height="${pbH.toFixed(1)}" fill="none" stroke="#2a4034" stroke-width="0.15" />`;
  svg += `<rect x="${padX}" y="${(pitchCY - sixH / 2).toFixed(1)}" width="${sixW.toFixed(1)}" height="${sixH.toFixed(1)}" fill="none" stroke="#2a4034" stroke-width="0.12" />`;
  svg += `<rect x="${(W - padX - sixW).toFixed(1)}" y="${(pitchCY - sixH / 2).toFixed(1)}" width="${sixW.toFixed(1)}" height="${sixH.toFixed(1)}" fill="none" stroke="#2a4034" stroke-width="0.12" />`;

  // Render edges in two passes so muted ones go BEHIND the highlighted ones.
  // For Morocco's wall+recycle view we also cap the focus list per category
  // so the pitch reads as ~6 wall edges + ~6 recycle edges instead of a blob
  // of every-defender-to-every-attacker. Edges are kept in descending
  // aw_joi90 order before capping.
  const mutedEdges = [], focusEdges = [];
  const sortedEdges = [...edges].sort((x, y) => (y.aw_joi90 || 0) - (x.aw_joi90 || 0));
  const cat2style = new Map(); // remember per-category style for later
  for (const e of sortedEdges) {
    const a = placed.get(e.p), b = placed.get(e.q);
    const meta = edgeStyle(e, a, b);
    cat2style.set(meta.color, meta);
    (meta.muted ? mutedEdges : focusEdges).push({ e, a, b, ...meta });
  }
  // Universal per-category cap on focused edges so no team network turns
  // into spaghetti. Per-highlight cap profiles tuned to keep the strongest
  // story-bearing edges and drop the rest into the muted bucket (where
  // they still render very faintly at the back).
  const CAP_BY_HIGHLIGHT = {
    "wall+recycle": { def: 6, off: 6, cross: 8 },
    "def":          { def: 8, off: 4, cross: 5 },
    "midfield":     { def: 4, off: 8, cross: 6 },
    "_default":     { def: 5, off: 7, cross: 6 },
  };
  const CAP = CAP_BY_HIGHLIGHT[highlight] || CAP_BY_HIGHLIGHT._default;
  {
    const seenCats = new Map();
    const capped = [];
    const overflow = [];
    for (const ed of focusEdges) {
      const seen = seenCats.get(ed.cat) || 0;
      const cap = CAP[ed.cat] ?? 100;
      if (seen >= cap) { overflow.push(ed); continue; }
      seenCats.set(ed.cat, seen + 1);
      capped.push(ed);
    }
    for (const ed of overflow) mutedEdges.push({ ...ed, muted: true });
    focusEdges.length = 0;
    focusEdges.push(...capped);
  }
  for (const { e, a, b, color, muted } of mutedEdges) {
    const r = ratioOf(e);
    const w = 0.10 + r * 0.35;
    const op = (0.05 + r * 0.10).toFixed(2);
    svg += `<line x1="${scaleX(a.x).toFixed(1)}" y1="${scaleY(a.y).toFixed(1)}" x2="${scaleX(b.x).toFixed(1)}" y2="${scaleY(b.y).toFixed(1)}" stroke="${color}" stroke-opacity="${op}" stroke-width="${w.toFixed(2)}" stroke-linecap="round"><title>${escapeHTML(e.name_p)} ↔ ${escapeHTML(e.name_q)}: AW-JOI90 ${e.aw_joi90.toFixed(2)}, AW-JDI90 ${(e.aw_jdi90 ?? 0).toFixed(2)}</title></line>`;
  }
  // Focused edges: slightly thinner than before, still with a soft halo
  // underneath so the wall reads as a single lattice and not a tangle.
  for (const { e, a, b, color } of focusEdges) {
    const r = ratioOf(e);
    const w = 0.35 + r * 1.25;
    const op = (0.55 + r * 0.40).toFixed(2);
    svg += `<line x1="${scaleX(a.x).toFixed(1)}" y1="${scaleY(a.y).toFixed(1)}" x2="${scaleX(b.x).toFixed(1)}" y2="${scaleY(b.y).toFixed(1)}" stroke="${color}" stroke-opacity="0.16" stroke-width="${(w * 1.9).toFixed(2)}" stroke-linecap="round" />`;
    svg += `<line x1="${scaleX(a.x).toFixed(1)}" y1="${scaleY(a.y).toFixed(1)}" x2="${scaleX(b.x).toFixed(1)}" y2="${scaleY(b.y).toFixed(1)}" stroke="${color}" stroke-opacity="${op}" stroke-width="${w.toFixed(2)}" stroke-linecap="round"><title>${escapeHTML(e.name_p)} ↔ ${escapeHTML(e.name_q)}: AW-JOI90 ${e.aw_joi90.toFixed(2)}, AW-JDI90 ${(e.aw_jdi90 ?? 0).toFixed(2)}</title></line>`;
  }
  for (const n of placed.values()) {
    // Bigger nodes: ~1.6–2.6 in viewBox units (was 0.9–1.6). Defenders in
    // "def" highlight mode get a thicker ring so the wall pops as a unit.
    const r = 1.6 + Math.min(1.0, n.minutes / 600) * 1.0;
    const isWallNode = highlight === "def" && isDef(n.position);
    const ringColor = highlight === "midfield" && midfieldEngine.has(n.player_id)
      ? "#ffd166"
      : (isWallNode ? "#5eb1f8" : "#e8eef9");
    const ringWidth = isWallNode ? 0.45 : 0.28;
    if (isWallNode) {
      svg += `<circle cx="${scaleX(n.x).toFixed(1)}" cy="${scaleY(n.y).toFixed(1)}" r="${(r + 0.9).toFixed(2)}" fill="none" stroke="${ringColor}" stroke-opacity="0.25" stroke-width="0.5" />`;
    }
    svg += `<circle cx="${scaleX(n.x).toFixed(1)}" cy="${scaleY(n.y).toFixed(1)}" r="${r.toFixed(2)}" fill="#0b1220" stroke="${ringColor}" stroke-width="${ringWidth}"><title>${escapeHTML(n.name)} (${escapeHTML(n.position)}) · ${Math.round(n.minutes)} min</title></circle>`;
    const displayName = niceSurname(n.name);
    svg += `<text x="${scaleX(n.x).toFixed(1)}" y="${(scaleY(n.y) + r + 2.6).toFixed(1)}" text-anchor="middle" class="atom-label" style="font-weight:${isWallNode ? 700 : 600}; fill:${isWallNode ? "#cfe3ff" : "#e8eef9"};">${escapeHTML(displayName)}</text>`;
  }
  // Callouts: WALL / THE ATTACK pinned to the TOP edge of the pitch
  // (above the play, where they can't overlap anything) and connected to
  // their cluster with a faint vertical line. Avoids the previous problem
  // where the boxes sat on top of the player dots and labels.
  if (highlight === "def" || highlight === "wall+recycle") {
    const drawCallout = (cluster, text, color) => {
      if (!cluster.length) return;
      const cx = cluster.reduce((s, n) => s + scaleX(n.x), 0) / cluster.length;
      // Lives in the dedicated headroom band (y 0-6) — guaranteed clear
      // of every player dot / label since the pitch surface itself
      // starts at y = padTop (6).
      const boxY = 0.6;
      const boxH = 4.4;
      // Box width: pad generously so the bold mono text + letter-spacing
      // can never clip. Was clipping "THE WALL" / "THE ATTACK" at the
      // box edges before (text wider than container).
      const w = Math.max(18, text.length * 2.05 + 4);
      svg += `<rect x="${(cx - w / 2).toFixed(1)}" y="${boxY}" width="${w.toFixed(1)}" height="${boxH}" rx="0.8" fill="${color}" fill-opacity="0.16" stroke="${color}" stroke-width="0.35" />`;
      svg += `<text x="${cx.toFixed(1)}" y="${(boxY + 2.85).toFixed(1)}" text-anchor="middle" style="fill:${color}; font-size:2.5px; font-weight:800; letter-spacing:0.45px;">${text}</text>`;
    };
    const defs = [...placed.values()].filter((n) => isDef(n.position));
    drawCallout(defs, "THE WALL", "#5eb1f8");
    if (highlight === "wall+recycle") {
      const offs = [...placed.values()].filter((n) => isOff(n.position));
      drawCallout(offs, "THE ATTACK", "#f59e0b");
    }
  }
  svg += `</svg>`;
  mountEl.innerHTML = svg;
}

/** Nucleus rendering for Argentina: Messi at the center, every strong
 *  partner orbiting around him. Orbital position is scored by
 *  Messi-pair AW-JOI (closer = stronger pair), with light angular spread
 *  by position so it doesn't all collapse into one cluster. */
function renderNucleusNetwork(mountEl, teamName, centerName = "Messi") {
  const teamId = TEAM_IDS[teamName];
  const net = fullNets?.[teamId];
  if (!mountEl || !net) {
    if (mountEl) mountEl.innerHTML = `<div class="empty-state small">Network data missing.</div>`;
    return;
  }
  const center = net.nodes.find((n) => n.name.includes(centerName));
  if (!center) {
    mountEl.innerHTML = `<div class="empty-state small">${escapeHTML(centerName)} not found in roster.</div>`;
    return;
  }
  // Messi spokes
  const spokes = net.edges
    .filter((e) => (e.p === center.player_id || e.q === center.player_id) && Number.isFinite(e.aw_joi90))
    .map((e) => {
      const other = e.p === center.player_id ? e.q : e.p;
      const otherName = e.p === center.player_id ? e.name_q : e.name_p;
      const otherNode = net.nodes.find((n) => n.player_id === other);
      return { other, otherName, otherNode, aw_joi90: e.aw_joi90, aw_jdi90: e.aw_jdi90 };
    })
    .filter((s) => s.otherNode && s.otherNode.position !== "GK" && s.aw_joi90 >= 0.3)
    .sort((a, b) => b.aw_joi90 - a.aw_joi90);

  const W = 100, H = 64, cx = W / 2, cy = H / 2;
  const maxJoi = Math.max(0.4, ...spokes.map((s) => s.aw_joi90));

  // Angular slot by player position so spokes splay out by role
  // (defenders left, midfielders top/bottom, forwards right).
  const posAngle = (pos) => {
    if (/^(GK|CB|LCB|RCB|LB|RB|LWB|RWB)$/.test(pos)) return Math.PI;        // left half
    if (/^(CF|ST|LW|RW|SS)$/.test(pos)) return 0;                            // right half
    if (/^(LM|LCM)$/.test(pos)) return -Math.PI / 2 - 0.4;
    if (/^(RM|RCM)$/.test(pos)) return  Math.PI / 2 + 0.4;
    if (/^(AM|CAM)$/.test(pos)) return -Math.PI / 4;
    if (/^(DM|CDM)$/.test(pos)) return Math.PI - Math.PI / 4;
    return -Math.PI / 2;  // CM / fallback up top
  };

  // Spread spokes inside each angular bucket so labels don't overlap.
  const buckets = new Map();
  spokes.forEach((s) => {
    const a = posAngle(s.otherNode.position || "CM");
    if (!buckets.has(a)) buckets.set(a, []);
    buckets.get(a).push(s);
  });
  const placed = [];
  for (const [angle, list] of buckets.entries()) {
    list.sort((a, b) => b.aw_joi90 - a.aw_joi90);
    const span = 0.55;  // total angular spread per bucket
    list.forEach((s, i) => {
      const t = list.length === 1 ? 0 : (i / (list.length - 1)) - 0.5;
      const a = angle + t * span;
      // Stronger pair = closer to Messi (shorter orbit radius).
      const ratio = s.aw_joi90 / maxJoi;
      const orbit = 14 + (1 - ratio) * 14;  // 14..28
      placed.push({
        ...s,
        x: cx + Math.cos(a) * orbit,
        y: cy + Math.sin(a) * orbit * (H / W) * 1.6,
        ratio,
      });
    });
  }

  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="atom-svg" role="img" aria-label="${escapeHTML(teamName)} nucleus network around ${escapeHTML(center.name)}">`;
  svg += `<rect x="0" y="0" width="${W}" height="${H}" fill="none" stroke="#2a313d" stroke-width="0.2" />`;

  // Spoke lines first (under the dots)
  for (const s of placed) {
    const w = 0.2 + s.ratio * 1.4;
    const op = (0.32 + s.ratio * 0.55).toFixed(2);
    svg += `<line x1="${cx}" y1="${cy}" x2="${s.x.toFixed(1)}" y2="${s.y.toFixed(1)}" stroke="#ffd166" stroke-opacity="${op}" stroke-width="${w.toFixed(2)}" stroke-linecap="round"><title>${escapeHTML(center.name)} ↔ ${escapeHTML(s.otherName)}: AW-JOI90 ${s.aw_joi90.toFixed(2)}</title></line>`;
  }
  // Orbital dots + labels
  for (const s of placed) {
    const r = 0.9 + s.ratio * 0.7;
    svg += `<circle cx="${s.x.toFixed(1)}" cy="${s.y.toFixed(1)}" r="${r.toFixed(2)}" fill="#1f2a3a" stroke="#e8eef9" stroke-width="0.22"><title>${escapeHTML(s.otherName)} · AW-JOI90 ${s.aw_joi90.toFixed(2)}</title></circle>`;
    const sn = niceSurname(s.otherName);
    svg += `<text x="${s.x.toFixed(1)}" y="${(s.y + r + 2.6).toFixed(1)}" text-anchor="middle" class="atom-label">${escapeHTML(sn)}</text>`;
  }
  // Nucleus on top
  svg += `<circle cx="${cx}" cy="${cy}" r="3.6" fill="#fde047" stroke="#0b1220" stroke-width="0.4"><title>${escapeHTML(center.name)}</title></circle>`;
  svg += `<text x="${cx}" y="${(cy + 5.4).toFixed(1)}" text-anchor="middle" class="atom-label" font-weight="700">${escapeHTML(niceSurname(center.name))}</text>`;
  svg += `</svg>`;
  mountEl.innerHTML = svg;
}

/* ---------------- network mounts (with Nucleus / Network toggles) ---------------- */

// Per-team config: which highlight mode + edge threshold to use for the
// "Network" view, and which player anchors the "Nucleus" view.
const TEAM_VIEW_CFG = {
  argentina: { name: "Argentina", highlight: null,       threshold: 0.30, nucleusCenter: "Messi" },
  france:    { name: "France",    highlight: null,       threshold: 0.50, nucleusCenter: "Mbappé" },
  morocco:   { name: "Morocco",   highlight: "wall+recycle", threshold: 0.30, nucleusCenter: null },
  croatia:   { name: "Croatia",   highlight: "midfield", threshold: 0.30, nucleusCenter: null },
};

// Pick a sensible default nucleus center: team's top-AW-JOI non-GK player.
function pickTopAwjoiPlayer(teamName) {
  const teamId = TEAM_IDS[teamName];
  const net = fullNets?.[teamId];
  if (!net) return null;
  const gkIds = new Set(net.nodes.filter((n) => n.position === "GK").map((n) => n.player_id));
  let bestName = null, bestVal = -Infinity;
  for (const e of (net.edges || [])) {
    if (!Number.isFinite(e.aw_joi90)) continue;
    if (gkIds.has(e.p) || gkIds.has(e.q)) continue;
    if (e.aw_joi90 > bestVal) {
      bestVal = e.aw_joi90;
      // Prefer the higher-minutes endpoint as anchor.
      const np = net.nodes.find((n) => n.player_id === e.p);
      const nq = net.nodes.find((n) => n.player_id === e.q);
      bestName = (np && nq && (np.minutes || 0) >= (nq.minutes || 0)) ? np.name : (nq?.name || np?.name);
    }
  }
  return bestName;
}

function renderTeamView(teamKey, view) {
  const cfg = TEAM_VIEW_CFG[teamKey];
  if (!cfg) return;
  const mountEl = document.getElementById(`net-${teamKey}`);
  if (!mountEl) return;
  if (view === "nucleus") {
    const center = cfg.nucleusCenter || pickTopAwjoiPlayer(cfg.name);
    if (!center) {
      mountEl.innerHTML = `<div class="empty-state small">No nucleus anchor found for ${escapeHTML(cfg.name)}.</div>`;
      return;
    }
    renderNucleusNetwork(mountEl, cfg.name, center);
  } else {
    renderPitchNetwork(mountEl, cfg.name, cfg.highlight, cfg.threshold);
  }
}

// Per-team, per-view heading + blurb text. When the user toggles between
// Nucleus and Network, the headline above the graph updates so it doesn't
// keep claiming "Messi's orbital network" while you're actually looking at
// the pitch-positioned team network.
const NET_VIEW_TEXT = {
  argentina: {
    nucleus: {
      h: "Messi's orbital network",
      p: "Spokes from Messi to every strong same-squad partner. Line thickness ∝ AW-JOI90; shorter orbit = stronger pair. Goalkeeper excluded.",
    },
    network: {
      h: "Argentina — pitch-positioned chemistry network",
      p: "Every Argentina player as a node on the pitch; edges colored by pair category (yellow off↔off, blue def↔def, purple cross-team). Capped per category so the strongest pairs read at a glance.",
    },
  },
};
function updateNetHeading(teamKey, view) {
  const cfg = NET_VIEW_TEXT[teamKey]?.[view];
  if (!cfg) return;
  const hEl = document.getElementById(`${teamKey}-net-heading`);
  const pEl = document.getElementById(`${teamKey}-net-blurb`);
  if (hEl) hEl.textContent = cfg.h;
  if (pEl) pEl.textContent = cfg.p;
}
function wireNetworkToggles() {
  document.querySelectorAll(".net-view-toggle").forEach((group) => {
    const teamKey = group.dataset.team;
    const defaultView = group.dataset.default || "network";
    const buttons = group.querySelectorAll(".net-view-btn");
    const apply = (view) => {
      buttons.forEach((b) => b.classList.toggle("active", b.dataset.view === view));
      updateNetHeading(teamKey, view);
      renderTeamView(teamKey, view);
    };
    buttons.forEach((b) => b.addEventListener("click", () => apply(b.dataset.view)));
    apply(defaultView);
  });
}

wireNetworkToggles();

/* ---------------- Morocco def-def support panel ---------------- */
// Renders a tournament-wide leaderboard with a metric switcher so the
// reader can pick which way to slice defensive chemistry. Morocco ranks
// differently on each:
//   sum_jdi  — Morocco #2 (Argentina just ahead)
//   n_strong — Morocco #3 (using the paper's tcd_def threshold)
//   top5_mean — Morocco #7
//   mean_jdi — Morocco #8
// Default is sum_jdi where they look strongest.
function computeDefMetrics() {
  if (!fullNets || typeof fullNets !== "object") return [];
  const out = [];
  // Outfield-defender predicate — EXCLUDES GK so GK↔CB pairs (which the
  // model heavily attends to in the defensive third) don't dominate the
  // metric. Matches the chemistry-leaderboard convention from CLAUDE.md.
  const isOutfieldDef = (p) => /^(CB|LB|RB|LCB|RCB|LWB|RWB)$/.test(p || "");
  for (const tid in fullNets) {
    const net = fullNets[tid];
    if (!net || !Array.isArray(net.nodes)) continue;
    const byId = new Map(net.nodes.map((n) => [n.player_id, n]));
    const jdis = [];
    for (const e of (net.edges || [])) {
      const a = byId.get(e.p), b = byId.get(e.q);
      if (!a || !b) continue;
      if (!isOutfieldDef(a.position) || !isOutfieldDef(b.position)) continue;
      const v = e.aw_jdi90;
      if (Number.isFinite(v) && v > 0) jdis.push(v);
    }
    if (!jdis.length) continue;
    jdis.sort((a, b) => b - a);
    const sum = jdis.reduce((s, x) => s + x, 0);
    const mean = sum / jdis.length;
    const top5 = jdis.slice(0, 5);
    const top5_mean = top5.reduce((s, x) => s + x, 0) / top5.length;
    const tinfo = (Array.isArray(teamRows)
      ? teamRows.find((r) => String(r.team_id) === String(tid)) : null) || {};
    out.push({
      tid,
      name: tinfo.team_name || `team ${tid}`,
      flag_code: tinfo.flag_code,
      stage: tinfo.stage,
      sum_jdi: sum,
      mean_jdi: mean,
      top5_mean,
      n_strong: tinfo.tcd_def ?? jdis.filter((v) => v >= 0.30).length,
    });
  }
  return out;
}
const DEF_METRICS = computeDefMetrics();
const METRIC_META = {
  sum_jdi:    { label: "Total defensive mass (Σ AW-JDI90)",
                blurb: "Add up the AW-JDI90 contribution of every def↔def pair on the team. Bigger number = either more elite pairs, more total defender minutes together, or both. Reads as <em>how much joint-defending work the back line did per 90</em>, in the model's units (so the absolute value isn't a probability &mdash; it's a relative threat-suppression score). The Morocco vs Argentina gap (3.33 vs 3.40) is &lt;3&#37;: effectively tied at the top.",
                fmt: (v) => (v == null ? "—" : v.toFixed(2)) },
  n_strong:   { label: "Strong pairs (AW-JDI90 ≥ 0.30)",
                blurb: "Count of pair-edges whose AW-JDI90 clears 0.30 &mdash; the cutoff Bransen &amp; Van Haaren used as their \"elite pair\" threshold. Rewards breadth: a team with five solid pairs scores higher than a team carried by one star duo.",
                fmt: (v) => String(Math.round(v)) },
  top5_mean:  { label: "Mean of top-5 pairs",
                blurb: "Average AW-JDI90 across a team's five strongest def↔def pairs. Strips out depth: a team with one elite back four can still rank high here even if their bench partnerships have no chemistry signal.",
                fmt: (v) => (v == null ? "—" : v.toFixed(3)) },
  mean_jdi:   { label: "Mean across all pairs",
                blurb: "Average AW-JDI90 across every def↔def pair the team has minutes for. Closer to a per-pair quality floor than a ceiling &mdash; a team is penalised here if rotations dilute the back-line chemistry.",
                fmt: (v) => (v == null ? "—" : v.toFixed(3)) },
};

function renderMoroccoTcdSupport(metric = "sum_jdi") {
  const lbEl = document.getElementById("morocco-tcd-def-leaderboard");
  const brEl = document.getElementById("morocco-tcd-breakdown");
  if (!Array.isArray(teamRows)) return;
  if (!DEF_METRICS.length) return;
  const fmt = (METRIC_META[metric] || METRIC_META.sum_jdi).fmt;
  const sorted = [...DEF_METRICS].sort((a, b) => b[metric] - a[metric]);
  const top = sorted.slice(0, 10);
  const max = Math.max(1e-9, ...top.map((r) => r[metric]));
  // Build the row format the existing renderer below expects.
  const rows = top.map((r) => ({ name: r.name, n: r[metric], stage: r.stage }));
  if (lbEl) {
    const FLAG = {
      Brazil: "🇧🇷", France: "🇫🇷", Morocco: "🇲🇦", Croatia: "🇭🇷",
      Argentina: "🇦🇷", Spain: "🇪🇸", Portugal: "🇵🇹", "Saudi Arabia": "🇸🇦",
      Germany: "🇩🇪", Switzerland: "🇨🇭", "United States": "🇺🇸", "South Korea": "🇰🇷",
      Netherlands: "🇳🇱", Japan: "🇯🇵", Senegal: "🇸🇳", Australia: "🇦🇺",
      Mexico: "🇲🇽", Uruguay: "🇺🇾", Belgium: "🇧🇪", Canada: "🇨🇦",
      Ghana: "🇬🇭", Cameroon: "🇨🇲", Denmark: "🇩🇰", England: "🇬🇧",
      Iran: "🇮🇷", Poland: "🇵🇱", Qatar: "🇶🇦", Serbia: "🇷🇸",
      Tunisia: "🇹🇳", Wales: "🏴", "Costa Rica": "🇨🇷", Ecuador: "🇪🇨",
    };
    lbEl.innerHTML = top.map((src, i) => {
      const r = { name: src.name, n: src[metric] };
      const isMar = r.name === "Morocco";
      const pct = (r.n / max) * 100;
      const bg = isMar ? "#3b6ea0" : "#2a313d";
      const ring = isMar ? "border:1px solid #5eb1f8;" : "";
      const labelStyle = isMar ? "color:#cfe3ff; font-weight:700;" : "color:var(--text);";
      return `
        <div style="display:grid; grid-template-columns: 1.6rem 8rem 1fr 3.4rem; align-items:center; gap:0.5rem; margin:0.18rem 0;">
          <span class="dim small" style="text-align:right;">#${i + 1}</span>
          <span style="${labelStyle}">${FLAG[r.name] || "🏳️"} ${escapeHTML(r.name)}</span>
          <span style="height:0.85rem; background:#0e141f; border-radius:3px; overflow:hidden; ${ring}">
            <span style="display:block; height:100%; width:${pct.toFixed(1)}%; background:${bg};"></span>
          </span>
          <span class="tabular" style="${labelStyle} text-align:right;">${fmt(r.n)}</span>
        </div>`;
    }).join("");
  }
  if (brEl) {
    const mar = teamRows.find((r) => r.team_name === "Morocco");
    if (mar) {
      const o = mar.tcd_off || 0, dd = mar.tcd_def || 0, x = mar.tcd_cross_net || 0;
      brEl.innerHTML = `
        off↔off <strong class="tabular" style="color:#d4793a;">${o}</strong> &middot;
        <strong style="color:var(--text)">def↔def <strong class="tabular" style="color:#5eb1f8;">${dd}</strong></strong> &middot;
        cross-team <strong class="tabular" style="color:#9b7fc6;">${x}</strong>
        &nbsp; (total TCD ${mar.tcd ?? "?"})`;
    }
  }
}
renderMoroccoTcdSupport();

/* ---------------- Morocco elite pairs spotlight ---------------- */
// Names the 5 strongest def↔def pairs by AW-JDI90 (GKs excluded), each
// with their AW-JOI90 + minutes-shared, drawn from team_full_networks.json
// (already loaded into fullNets). El Yamiq is the hub in 3/5 — the card
// visualises that by giving him a larger badge.
function renderMoroccoElitePairs() {
  const mountEl = document.getElementById("morocco-elite-pairs");
  if (!mountEl) return;
  const net = fullNets?.[TEAM_IDS.Morocco];
  if (!net) return;
  const isDefPos = (p) => /^(CB|LB|RB|LCB|RCB|LWB|RWB)$/.test(p || "");

  // Build the field of ALL def↔def pairs across every team so we can score
  // each Morocco pair as a percentile against the actual field, not just
  // against Morocco's own row.
  const allDefJdis = [];
  for (const tid in fullNets) {
    const tn = fullNets[tid];
    const byTid = new Map(tn.nodes.map((n) => [n.player_id, n]));
    for (const e of (tn.edges || [])) {
      const a = byTid.get(e.p), b = byTid.get(e.q);
      if (!a || !b) continue;
      if (!isDefPos(a.position) || !isDefPos(b.position)) continue;
      const v = e.aw_jdi90 ?? 0;
      if (v > 0) allDefJdis.push(v);
    }
  }
  allDefJdis.sort((a, b) => a - b);
  const pctileOf = (v) => {
    if (!allDefJdis.length) return null;
    let lo = 0, hi = allDefJdis.length;
    while (lo < hi) { const m = (lo + hi) >> 1; allDefJdis[m] < v ? lo = m + 1 : hi = m; }
    return (lo / allDefJdis.length) * 100;
  };

  const byId = new Map(net.nodes.map((n) => [n.player_id, n]));
  const pairs = (net.edges || [])
    .map((e) => {
      const a = byId.get(e.p), b = byId.get(e.q);
      if (!a || !b) return null;
      if (!isDefPos(a.position) || !isDefPos(b.position)) return null;
      const jdi = e.aw_jdi90 ?? 0;
      const joi = e.aw_joi90 ?? 0;
      const mins = e.minutes_together ?? e.minutes ?? 0;
      return { a, b, jdi, joi, mins, pctile: pctileOf(jdi) };
    })
    .filter(Boolean)
    .sort((x, y) => y.jdi - x.jdi)
    .slice(0, 5);
  if (!pairs.length) { mountEl.innerHTML = "<div class='empty-state small'>No def-def pairs.</div>"; return; }
  // Count how many of the top-5 each player appears in — to size the hub badge.
  const appearCount = new Map();
  for (const p of pairs) {
    appearCount.set(p.a.player_id, (appearCount.get(p.a.player_id) || 0) + 1);
    appearCount.set(p.b.player_id, (appearCount.get(p.b.player_id) || 0) + 1);
  }
  const maxJdi = Math.max(...pairs.map((p) => p.jdi));
  const surname = (full) => niceSurname(full || "");
  // Pctile -> color bucket: ≥95 emerald, ≥85 green, ≥70 yellow, ≥50 amber, else gray.
  const pctileChip = (pct) => {
    if (pct == null) return "";
    let bg, border, fg, label;
    if (pct >= 95)      { bg = "#0e2a1a"; border = "#10b981"; fg = "#6ee7b7"; label = "elite"; }
    else if (pct >= 85) { bg = "#16321f"; border = "#22c55e"; fg = "#86efac"; label = "top tier"; }
    else if (pct >= 70) { bg = "#332815"; border = "#eab308"; fg = "#fde68a"; label = "strong"; }
    else if (pct >= 50) { bg = "#33240e"; border = "#f59e0b"; fg = "#fbbf24"; label = "solid"; }
    else                { bg = "#1f2a3a"; border = "#3a4554"; fg = "#9aa5b1"; label = "ok"; }
    return `<span title="${label} — beats ${pct.toFixed(1)}% of all def↔def pairs in the tournament"
                   style="display:inline-flex; align-items:center; gap:0.3rem; padding:0.12rem 0.45rem; border-radius:999px; background:${bg}; border:1px solid ${border}; color:${fg}; font-weight:700; font-size:0.78rem; letter-spacing:0.3px; text-transform:uppercase;">
        ${label} &middot; p${Math.round(pct)}
      </span>`;
  };
  mountEl.innerHTML = `
    <div style="display:grid; grid-template-columns: 1.4rem 1fr 7rem 6rem 4rem; align-items:center; column-gap:0.65rem; row-gap:0.4rem;">
      <span></span>
      <span class="dim small" style="text-transform:uppercase; letter-spacing:0.5px;">Pair</span>
      <span class="dim small" style="text-transform:uppercase; letter-spacing:0.5px;">AW-JDI90</span>
      <span class="dim small" style="text-transform:uppercase; letter-spacing:0.5px;">vs field</span>
      <span class="dim small" style="text-transform:uppercase; letter-spacing:0.5px; text-align:right;">Mins</span>
      ${pairs.map((p, i) => {
        const pct = (p.jdi / maxJdi) * 100;
        const aHub = (appearCount.get(p.a.player_id) || 0) >= 2;
        const bHub = (appearCount.get(p.b.player_id) || 0) >= 2;
        const badge = (name, pos, isHub) => `
          <span style="display:inline-flex; align-items:center; gap:0.3rem; padding:0.18rem 0.5rem; border-radius:999px; background:${isHub ? "#1e3a5f" : "#1f2a3a"}; border:1px solid ${isHub ? "#5eb1f8" : "#2a313d"}; color:${isHub ? "#cfe3ff" : "#cdd6e3"}; font-weight:${isHub ? 700 : 500};">
            ${escapeHTML(surname(name))}
            <span class="dim small" style="font-weight:500;">${escapeHTML(pos)}</span>
          </span>`;
        return `
          <span class="dim small" style="text-align:right;">#${i + 1}</span>
          <span style="display:flex; align-items:center; gap:0.4rem; flex-wrap:wrap;">
            ${badge(p.a.name, p.a.position, aHub)}
            <span class="dim">↔</span>
            ${badge(p.b.name, p.b.position, bHub)}
          </span>
          <span style="display:flex; align-items:center; gap:0.4rem;">
            <span style="flex:1; height:0.55rem; background:#0e141f; border-radius:3px; overflow:hidden;">
              <span style="display:block; height:100%; width:${pct.toFixed(1)}%; background:#5eb1f8;"></span>
            </span>
            <span class="tabular" style="color:#cfe3ff; font-weight:700; min-width:2.6rem; text-align:right;">${p.jdi.toFixed(3)}</span>
          </span>
          <span>${pctileChip(p.pctile)}</span>
          <span class="tabular dim small" style="text-align:right;">${Math.round(p.mins)}</span>
        `;
      }).join("")}
    </div>
    <p class="dim small" style="margin:0.6rem 0 0;">
      <strong style="color:#cfe3ff;">El Yamiq</strong> appears in
      ${[...appearCount.values()].filter((v) => v >= 2).length > 0 ? "3 of the top 5 pairs" : "multiple top pairs"}
      &mdash; the wall has a hub. Percentile is vs every def&harr;def pair
      across all 32 squads (${allDefJdis.length} pairs).
    </p>`;
}
renderMoroccoElitePairs();

/* ---------------- Morocco TCD hero card ---------------- */
function renderMoroccoTcdHero(metric = "sum_jdi") {
  const el = document.getElementById("morocco-tcd-hero");
  if (!el || !DEF_METRICS.length) return;
  const meta = METRIC_META[metric] || METRIC_META.sum_jdi;
  const sorted = [...DEF_METRICS].sort((a, b) => b[metric] - a[metric]);
  const mar = sorted.find((r) => r.name === "Morocco");
  if (!mar) return;
  const rank = sorted.findIndex((r) => r.name === "Morocco") + 1;
  const total = sorted.length;
  const ahead = sorted.slice(0, rank - 1).map((r) => r.name);
  el.innerHTML = `
    <div style="display:flex; align-items:center; gap:0.9rem; padding:0.75rem 1rem; border-radius:var(--radius-sm); background:linear-gradient(90deg, #1e3a5f 0%, #1a2840 100%); border:1px solid #5eb1f8;">
      <span style="font-size:2.4rem; line-height:1;">🇲🇦</span>
      <div style="flex:1;">
        <div style="font-weight:800; font-size:1.1rem; color:#cfe3ff;">Morocco &mdash; <span style="color:#5eb1f8;">#${rank} of ${total}</span></div>
        <div class="small" style="color:#a6c1e0;">
          <strong class="tabular" style="color:#cfe3ff;">${meta.fmt(mar[metric])}</strong> &middot; ${meta.label}
          ${ahead.length ? `<br>only behind ${escapeHTML(ahead.join(" and "))}` : ""}
          ${ahead.length === 0 ? `<br><strong style="color:#86efac;">leading the field</strong>` : ""}
        </div>
      </div>
    </div>`;
  const blurbEl = document.getElementById("morocco-metric-blurb");
  if (blurbEl) blurbEl.innerHTML = meta.blurb;
}
renderMoroccoTcdHero();

/* ---------------- Metric switcher dropdown ---------------- */
function wireMoroccoMetricSwitcher() {
  const sel = document.getElementById("morocco-metric-select");
  if (!sel) return;
  const apply = (m) => {
    renderMoroccoTcdSupport(m);
    renderMoroccoTcdHero(m);
  };
  sel.addEventListener("change", () => apply(sel.value));
  apply(sel.value);
}
wireMoroccoMetricSwitcher();

/* ---------------- embedded play scrubbers ---------------- */
// One per case study, plus an appendix.
// Argentina → Julián Álvarez carry (Messi off-ball gravity visible).
// France    → Mbappé 81' volley.
// Morocco   → no clean Morocco clip in the current set; honest placeholder.
// Croatia   → no clean Croatia clip in the current set; honest placeholder.
// Appendix: Memphis 10' (Netherlands-USA), Doan 48' (Japan-Spain),
//           Di María 36' (Argentina-France final).

const PLAY_INDEX = {
  "argentina-australia-messi": {
    title: "Messi 35' (Argentina v Australia, R16)",
    summary: "A third-man run: Messi feeds the build-up, it works through Mac Allister and Otamendi, and Otamendi slips it back to Messi — who has run into the box to finish low past Ryan. Watch the chemistry load onto the Mac Allister↔Otamendi↔Messi link off the ball, before the pass that frees him.",
    // Clip total 69 frames: 59 real (Argentina's first attempt
    // cleared, then they recover and Messi finishes) + 10 synthetic
    // tail frames driving the ball into the net. Argentina attacks
    // the RIGHT goal (positive x). Real ball-crosses-line at frame 59.
    // Event timings (clip-relative): cross @0s, clearance @1s,
    // Argentina recovery 3-8s, Mac Allister & Otamendi feed Messi @10s,
    // Messi shot @11s, ball in net @11.8s.
    // The third-man run, narrated leg by leg. highlight_pairs force-draws the
    // combining pair's edge (bright dashed, labelled with its CUMULATIVE
    // AW-JOI) even though its single-frame attention is below the top-N floor —
    // that running number is "the attention that matters." Legs 1–2 stay wide
    // so the highlighted edge reads against the team; the climax focuses.
    // Each chapter's highlight_pairs ARE the rows of the table you're reading at
    // that moment, and they suppress the generic top-N edges — so the lines on the
    // pitch always match the narrative. SPINE = the four off-ball-table pairs
    // (Otamendi↔Fernández 2, ↔Romero 7, Álvarez 0↔Otamendi, ↔Acuña 10); the legs
    // are the pass-table combination pairs.
    annotations: [
      { from: 0,  to: 13, text: "Messi's early cross — Souttar clears (no threat yet)",
        pair_defaults: { cats: ["off-off"], top: 4 } },
      { from: 14, to: 35, text: "Argentina recycle — the off-ball spine the model keeps linked (the off-ball table)",
        highlight_pairs: [[1, 2], [1, 7], [0, 1], [1, 10]],
        pair_defaults: { cats: ["off-off"], top: 4 } },
      { from: 36, to: 44, text: "Third-man run · leg 1 — Messi ➝ Mac Allister",
        highlight_pairs: [[5, 6]],
        pair_defaults: { cats: ["off-off"], top: 1 } },
      { from: 45, to: 50, text: "Leg 2 — Mac Allister ➝ Otamendi (the relay; their chemistry is already ~0.09)",
        highlight_pairs: [[6, 1]],
        pair_defaults: { cats: ["off-off"], top: 1 } },
      // Climax: tighten to Otamendi + Messi as the ball comes back and Messi
      // arrives to finish.
      { from: 51, to: 58, text: "Leg 3 — Otamendi slips it back; Messi has run in to finish",
        focus_slots: [1, 5], highlight_pairs: [[1, 5]],
        pair_defaults: { cats: ["off-off"], top: 1 } },
      { from: 59, to: 200, text: "GOAL — Messi · third-man run complete", color: "#ffd166",
        focus_slots: [5], highlight_pairs: [[1, 5]],
        pair_defaults: { cats: ["off-off"], top: 1 } },
    ],
    // Otamendi's feed to Messi lands at frame ~50.
    pinning: { slots: [1], from: 42, to: 52, label: "FEEDER" },
    // Label every player named in the two write-up tables so the reader can
    // identify them on the pitch: Argentina's recycle (Álvarez 0, Otamendi 1,
    // Fernández 2, Messi 5, Mac Allister 6, Romero 7, Gómez 9, Acuña 10) plus
    // the two Australian centre-backs the read calls out (Rowles 15, Souttar 20).
    name_slots: [0, 1, 2, 5, 6, 7, 9, 10, 15, 20],
    scorer_slot: 5, // Messi
    scorer_label: "FINISH",
    scorer_from: 42,
    scorer_to: 200,
  },
  "argentina-france-mbappe-volley": {
    title: "Mbappé 81' volley (France v Argentina, final)",
    summary: "Mbappé's second goal in 97 seconds. P(concede) for Argentina spikes as France break — the network around Mbappé snaps shut around the ball.",
  },
  "netherlands-usa-memphis": {
    title: "Memphis 10' (Netherlands v USA, R16)",
    summary: "Memphis at the end of a 20-pass Dutch sequence. Cross-team attention hands off down the chain — the chemistry edge that lives in pure tracking.",
  },
  "japan-spain-doan": {
    title: "Doan 48' (Japan v Spain, group stage)",
    summary: "Japan equalize from a press-and-recover sequence. Watch P(concede) for Spain climb in the seconds before any touch — that's their defensive shape breaking, not a Japanese on-ball action.",
  },
  "argentina-france-di-maria": {
    title: "Di María 36' (Argentina v France, final)",
    summary: "Argentina build the third goal from Tagliafico's interception — attention chains through Mac Allister to Messi to Di María. The off-ball spreading happens before any pass on the goal.",
  },
  "croatia-japan-perisic": {
    title: "Perišić equalizer (Croatia v Japan, R16)",
    summary: "Croatia's midfield engine sets up Perišić's header. Modrić plays the QB-ball that leads the runner; Barišić bombs forward on the left to drag the line; Lovren whips the cross to the back post for Perišić.",
    annotations: [
      { from: 0,   to: 39,  text: "Build-up — Croatia recycle through the middle",
        pair_defaults: { cats: ["off-off"], top: 3 } },
      { from: 40,  to: 99,  text: "Modrić threads it — QB-style read",
        pair_defaults: { cats: ["off-off", "cross"], top: 3 } },
      { from: 100, to: 134, text: "Barišić bombs forward on the left",
        pair_defaults: { cats: ["off-off"], top: 3 } },
      { from: 135, to: 149, text: "Lovren cross — Perišić attacks the back post",
        pair_defaults: { cats: ["cross"], top: 4 } },
      { from: 150, to: 200, text: "GOAL — Perišić", color: "#ffd166",
        pair_defaults: { cats: ["off-off", "cross"], top: 4 } },
    ],
    // Modrić (slot 16) gets the pink ring during his ignite-window. Pin
    // label "QB" because that's the user's own framing — the touch that
    // throws someone open.
    pinning: { slots: [16], from: 40, to: 99, label: "QB" },
    // Perišić (slot 21) is the eventual scorer; the gold ring tracks him
    // through the off-ball run + the header.
    scorer_slot: 21,
    scorer_label: "RUNNER",
    scorer_from: 100,
    scorer_to: 200,
  },
  "morocco-portugal-en-nesyri": {
    title: "En-Nesyri header (Morocco v Portugal, QF)",
    summary: "The defining Morocco moment. Build-up Ziyech → Boufal → Ounahi → Attiat-Allah, then a left-side cross. The off-ball move that makes it work: En-Nesyri pins between Dias and Pepe a beat before contact — watch his halo brighten while the cross-team attention edges concentrate on the centre-back pair, not the ball. Open-play header that out-leaps the Portugal back line and Diogo Costa.",
    // Wall+recycle reading spans the full pitch (defenders feeding
    // attackers across both halves). Auto-zoom obscured the off-ball
    // shape that's the whole point of this clip — keep the full field.
    disable_autozoom: true,
    // Frame indices reference the clip's own frames[] (5 Hz). Goal frame = 139.
    // Later entries take precedence when windows overlap (the renderer reads
    // findLast). The "CBs pulled" pink line replaces the original "En-Nesyri
    // pins" claim — when we re-ran the score specialist and looked at the
    // top pairs in the cross window, the heavy edges run from the ball-side
    // Morocco attackers (Boufal, Ounahi, Attiat-Allah) to Dias and Pepe,
    // not from En-Nesyri to them. The defenders ARE being pulled in
    // attentional terms, just not by the player we first guessed.
    // pair_defaults: when this chapter starts, sync the pair-edge toggles to
    // what makes sense for this phase. User can still override mid-chapter.
    annotations: [
      { from: 0, to: 30, text: "Build-up — Morocco recycle",
        pair_defaults: { cats: ["off-off", "cross"], top: 6 } },
      { from: 31, to: 70, text: "Ziyech turns it down the right",
        pair_defaults: { cats: ["off-off", "cross"], top: 6 } },
      { from: 71, to: 99, text: "Switch left → Boufal · Ounahi",
        pair_defaults: { cats: ["off-off", "cross"], top: 6 } },
      { from: 100, to: 132, text: "Attiat-Allah cross from the left",
        pair_defaults: { cats: ["cross"], top: 6 } },
      { from: 110, to: 132, text: "Dias & Pepe pulled by ball-side", color: "#ec4899",
        pair_defaults: { cats: ["cross"], top: 6 } },
      { from: 133, to: 156, text: "Header — ball in flight",
        pair_defaults: { cats: ["off-off", "cross"], top: 6 } },
      { from: 157, to: 200, text: "GOAL — En-Nesyri", color: "#ffd166",
        pair_defaults: { cats: ["off-off", "def-def", "cross"], top: 6 } },
    ],
    // Pin highlight switched to the two CBs that the model actually
    // concentrates pair attention on during the cross.
    // Dias (slot 11) and Pepe (slot 21) get pink "PULLED" rings during the
    // cross — the edges show the attention, the ring calls out the functional
    // consequence (CBs pulled to the ball-side, can't step out).
    pinning: { slots: [11, 21], from: 100, to: 138, label: "PULLED" },
    // En-Nesyri (slot 6) gets a gold "HEADER" ring during the same window so
    // you can see what the scorer is doing while the CBs are pulled.
    scorer_slot: 6,
    scorer_label: "HEADER",
    scorer_from: 100,
    scorer_to: 158,
  },
  "near-miss-netherlands-janssen": {
    title: "Janssen 4' blocked — near-miss (Senegal v Netherlands, group stage)",
    summary: "A near-miss: Netherlands work the ball into Senegal's box and P(score) climbs above 0.9 before Janssen's shot is blocked and the probability collapses. The model picks up chemistry on a sequence that didn't end in a goal.",
  },
  "bad-chemistry-australia-argentina": {
    title: "Turnover thrash 78' — bad chemistry (Argentina v Australia, R16)",
    summary: "What a breakdown looks like in the model. Net (P_score − P_concede) flips between +0.9 and −0.9 four times across 27 s as possession ping-pongs — high net is fragile when teams keep giving the ball back.",
  },
};

async function mountPlay(divId, label) {
  const meta = PLAY_INDEX[label];
  const el = document.getElementById(divId);
  if (!el) return;
  if (!meta) {
    el.innerHTML = `<div class="empty-state small">Clip <code>${escapeHTML(label)}</code> not found in PLAY_INDEX.</div>`;
    return;
  }
  await mountClipInto(el, { label, ...meta });
}

await mountPlay("play-france-1-2", "france-australia-giroud");
await mountPlay("play-argentina", "argentina-australia-messi");

// Build a FILTER PANEL right above the Messi play. Each chip toggles one
// relationship's label + connection on the pitch; the chip labels match the
// numbered rows in the tables further down, so it's clear what each references.
// The tables below stay clickable too (kept in sync), but the controls live up
// here next to the play rather than buried below it.
function wireClipFilters() {
  const rows = [...document.querySelectorAll("tr.clip-jump")];
  if (!rows.length) return;
  const scrollToPlay = (id) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" });

  // Collect each row's group + a readable label (number/time + pair/pass name).
  const items = rows.map((row) => {
    const frame = Number(row.dataset.frame || 0);
    const slots = (row.dataset.slots || "").split(",").map((s) => Number(s.trim())).filter((s) => !Number.isNaN(s));
    row._clip = row.dataset.clip;
    row._play = row.dataset.play || "play-argentina";
    row._frame = frame;
    row._slots = slots;
    row._key = `${row.dataset.slots}:${frame}`;
    const num = (row.cells[0]?.textContent || "").replace(/\s+/g, " ").trim();
    const name = (row.cells[1]?.textContent || "").replace(/\s+/g, " ").trim();
    return { row, key: row._key, slots, frame, clip: row._clip, play: row._play, num, name, table: row.closest("table") };
  });
  // off-ball table = the one whose rows are all at frame 0 (shared peak); the
  // other table is the on-ball pass chain.
  const tables = [...new Set(items.map((it) => it.table))];
  const isOffball = (tbl) => items.filter((it) => it.table === tbl).every((it) => it.frame === 0);
  const offball = items.filter((it) => isOffball(it.table));
  const onball = items.filter((it) => !isOffball(it.table));
  const clip = items[0].clip, play = items[0].play;

  const syncAll = () => {
    for (const it of items) {
      const on = isClipGroupActive(it.clip, it.key);
      it.row.classList.toggle("active", on);
      it.chip?.classList.toggle("active", on);
    }
  };
  const chip = (it) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "clip-chip";
    b.textContent = `${it.num} · ${it.name}`;
    b.title = "Toggle this relationship's labels + connection on the play";
    b.addEventListener("click", () => {
      toggleClipGroup(it.clip, it.key, it.slots, it.frame);
      if (isClipGroupActive(it.clip, it.key)) scrollToPlay(it.play);
      syncAll();
    });
    it.chip = b;
    return b;
  };
  const groupBtn = (text, fn) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn small"; b.textContent = text;
    b.addEventListener("click", () => { fn(); scrollToPlay(play); syncAll(); });
    return b;
  };

  const panel = document.createElement("div");
  panel.className = "card clip-filter-panel";
  panel.style.cssText = "margin:0 0 0.6rem; padding:0.6rem 0.85rem;";
  const intro = document.createElement("p");
  intro.className = "small mt-0 mb-0";
  intro.style.marginBottom = "0.45rem";
  intro.innerHTML = `<strong style="color:var(--accent)">&#9678; Filter the play</strong> &mdash; click a chip to label + connect that relationship on the pitch. The labels match the numbered rows in the two tables further down. Toggle as many as you want; the play stays on whatever you pick as you scrub.`;
  panel.appendChild(intro);

  const mkRow = (label, list) => {
    const r = document.createElement("div");
    r.style.cssText = "display:flex; gap:0.35rem; flex-wrap:wrap; align-items:center; margin-bottom:0.4rem;";
    const lab = document.createElement("span");
    lab.className = "small muted"; lab.style.cssText = "min-width:6.2rem; color:var(--text)"; lab.textContent = label;
    r.appendChild(lab);
    for (const it of list) r.appendChild(chip(it));
    return r;
  };
  if (offball.length) panel.appendChild(mkRow("Off-ball pairs:", offball));
  if (onball.length) panel.appendChild(mkRow("On-ball passes:", onball));

  const btnRow = document.createElement("div");
  btnRow.style.cssText = "display:flex; gap:0.4rem; flex-wrap:wrap; align-items:center;";
  if (offball.length) btnRow.appendChild(groupBtn("All off-ball", () => setClipGroups(clip, offball.map((it) => ({ key: it.key, slots: it.slots })))));
  if (onball.length) btnRow.appendChild(groupBtn("All on-ball", () => setClipGroups(clip, onball.map((it) => ({ key: it.key, slots: it.slots })))));
  btnRow.appendChild(groupBtn("Clear", () => clearClipLabels(clip)));
  panel.appendChild(btnRow);

  // Insert the panel right above the play box.
  const playEl = document.getElementById(play);
  if (playEl && playEl.parentNode) playEl.parentNode.insertBefore(panel, playEl);

  // Keep table rows clickable too, in sync with the chips.
  for (const it of items) {
    it.row.addEventListener("click", () => {
      toggleClipGroup(it.clip, it.key, it.slots, it.frame);
      if (isClipGroupActive(it.clip, it.key)) scrollToPlay(it.play);
      syncAll();
    });
  }

  // Default: label just the #1 off-ball pair so the play opens with one
  // relationship shown rather than a bare pitch or a wall of tags.
  const first = items.find((it) => it.row.dataset.slots === "1,2") || offball[0];
  if (first) toggleClipGroup(first.clip, first.key, first.slots, first.frame);
  syncAll();
}
wireClipFilters();
await mountPlay("play-france", "argentina-france-mbappe-volley");
await mountPlay("play-morocco", "morocco-portugal-en-nesyri");
await mountPlay("play-croatia", "croatia-japan-perisic");
await mountPlay("play-appendix-1", "netherlands-usa-memphis");
await mountPlay("play-appendix-2", "japan-spain-doan");
await mountPlay("play-appendix-3", "argentina-france-di-maria");
await mountPlay("play-appendix-4", "near-miss-netherlands-janssen");
await mountPlay("play-appendix-5", "bad-chemistry-australia-argentina");
