import { loadJSON, escapeHTML, flagHTML } from "./site.js";

// --- DOM handles ---------------------------------------------------------
const chemTable           = document.getElementById("chem-table");
const chemSortEl          = document.getElementById("chem-sort");
const chemVsResultScatter = document.getElementById("chem-vs-result-scatter");
const timeVsChemScatter   = document.getElementById("time-vs-chem-scatter");

// --- Load data -----------------------------------------------------------
const [chem, fifa] = await Promise.all([
  loadJSON("data/team_chemistry_vs_paper.json"),
  loadJSON("data/fifa_mode.json"),
]);
const fifaByTeam = new Map();
if (fifa?.wc_2022) {
  for (const r of fifa.wc_2022) fifaByTeam.set(r.team, r);
}
if (!chem) {
  chemTable.innerHTML = `<div class="empty-state"><strong>Team chemistry data missing.</strong></div>`;
} else {
  initChemistryTab(chem);
}

function initChemistryTab(rows) {
  const data = rows.filter(r => r.n_strong_total != null && r.stage_int != null);

  function applySort() {
    const v = chemSortEl.value;
    let sorted;
    const fifaOverall = (r) => fifaByTeam.get(r.team_name)?.overall ?? -1;
    if (v === "n_strong_total")          sorted = [...data].sort((a, b) => b.n_strong_total - a.n_strong_total);
    else if (v === "mean_aw_joi90_all")  sorted = [...data].sort((a, b) => b.mean_aw_joi90_all - a.mean_aw_joi90_all);
    else if (v === "total_prior_shared") sorted = [...data].sort((a, b) => b.total_prior_shared - a.total_prior_shared);
    else if (v === "fifa_overall")       sorted = [...data].sort((a, b) => fifaOverall(b) - fifaOverall(a));
    else if (v === "result_rank")        sorted = [...data].sort((a, b) => a.result_rank - b.result_rank);
    else sorted = data;
    renderChemTable(sorted);
  }
  chemSortEl.addEventListener("change", applySort);
  applySort();

  renderChemVsResultScatter(data);
  renderTimeVsChemScatter(data);
}

function renderChemTable(rows) {
  const head = `
    <thead><tr>
      <th>Team</th>
      <th class="num" title="Pairs on the squad with AW-JOI per 90 ≥ 0.4. Frame-level chemistry density.">Strong pairs</th>
      <th class="num" title="Mean AW-JOI per 90 across all same-team pairs.">Mean AW-JOI90</th>
      <th class="num" title="Total minutes any two squad-mates were on the pitch together pre-WC22 (club + national).">Prior shared min</th>
      <th class="num" title="EA Sports' published team Overall in FIFA 23.">FIFA Overall</th>
      <th>Top players (FIFA 23)</th>
      <th>Result</th>
    </tr></thead>`;
  const body = rows.map((r) => {
    const f = fifaByTeam.get(r.team_name);
    const fifaCell = f ? `<strong class="tabular">${f.overall}</strong>
        <span class="muted small">A${f.att}/M${f.mid}/D${f.def}</span>` : `<span class="muted">—</span>`;
    const starsHTML = (f?.stars || []).slice(0, 4).map((s) => {
      if (typeof s === "string") return `<span class="chip">${escapeHTML(s)}</span>`;
      return `<span class="chip" title="${escapeHTML(s.position || "")}">${escapeHTML(s.name)} <span class="muted">${s.overall}</span></span>`;
    }).join(" ");
    return `<tr>
      <td><span class="team-cell">${flagHTML(r.flag_code)} ${escapeHTML(r.team_name)}</span></td>
      <td class="num tabular"><strong>${r.n_strong_total}</strong>
        <span class="muted small">(off ${r.n_strong_off}/def ${r.n_strong_def}/cross ${r.n_strong_cross})</span></td>
      <td class="num tabular">${r.mean_aw_joi90_all.toFixed(2)}</td>
      <td class="num tabular">${(r.total_prior_shared / 1000).toFixed(1)}k</td>
      <td class="num">${fifaCell}</td>
      <td class="small">${starsHTML || `<span class="muted">—</span>`}</td>
      <td>${escapeHTML(r.stage)} <span class="muted small">#${r.result_rank}</span></td>
    </tr>`;
  }).join("");
  chemTable.innerHTML = `<div class="table-wrap"><table class="data-table fifa-data-table">${head}<tbody>${body}</tbody></table></div>`;
}

function renderChemVsResultScatter(rows) {
  // X = n_strong_total; Y = stage_int (2..8)
  const W = 1100, H = 520;
  const padL = 86, padR = 24, padT = 22, padB = 56;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const xs = rows.map(r => r.n_strong_total);
  const xmin = Math.min(...xs) - 2, xmax = Math.max(...xs) + 2;
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
          fill="currentColor" opacity="0.65" text-anchor="end">${label}</text>
  `).join("");

  // Dot colour encodes prior shared minutes (light → deep blue).
  // Gold ring marks the four squads with the densest networks (= the 4 semifinalists).
  const semis = new Set(["France", "Croatia", "Argentina", "Morocco"]);
  const priorMax = Math.max(...rows.map(r => r.total_prior_shared));
  const priorMin = Math.min(...rows.map(r => r.total_prior_shared));
  const priorScale = (v) => {
    const t = priorMax === priorMin ? 0 : (v - priorMin) / (priorMax - priorMin);
    // Interpolate between light gray and deep teal-blue
    const lo = [180, 190, 200], hi = [30, 90, 160];
    const rr = Math.round(lo[0] + (hi[0]-lo[0]) * t);
    const gg = Math.round(lo[1] + (hi[1]-lo[1]) * t);
    const bb = Math.round(lo[2] + (hi[2]-lo[2]) * t);
    return `rgb(${rr},${gg},${bb})`;
  };

  const dotsSvg = rows.map(r => {
    const cx = sx(r.n_strong_total), cy = sy(r.stage_int);
    const ring = semis.has(r.team_name)
      ? `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="9" fill="none" stroke="#d4a23a" stroke-width="2"/>`
      : "";
    return `${ring}<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5.5"
             fill="${priorScale(r.total_prior_shared)}" stroke="var(--bg, #0b1220)" stroke-width="1.2"/>`;
  }).join("");

  // Tiny color-ramp legend in the SVG corner
  const ramp = `
    <g transform="translate(${W - padR - 220}, ${padT + 8})">
      <text x="0" y="0" font-size="10.5" fill="currentColor" opacity="0.7">Prior shared minutes</text>
      ${[0, 0.25, 0.5, 0.75, 1.0].map((t, i) => {
        const v = priorMin + t * (priorMax - priorMin);
        return `<rect x="${i*38}" y="6" width="38" height="9" fill="${priorScale(v)}"/>`;
      }).join("")}
      <text x="0" y="28" font-size="10" fill="currentColor" opacity="0.6">${Math.round(priorMin/1000)}k</text>
      <text x="190" y="28" font-size="10" fill="currentColor" opacity="0.6" text-anchor="end">${Math.round(priorMax/1000)}k</text>
    </g>`;

  // Simple non-overlap label placement
  const labelW = 64, labelH = 14;
  const lineSpacing = labelH + 2;
  const intersects = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);
  const order = [...rows].sort((a, b) => b.stage_int - a.stage_int || b.n_strong_total - a.n_strong_total);
  const placed = [];
  const picks = new Map();
  for (const r of order) {
    const cx = sx(r.n_strong_total), cy = sy(r.stage_int);
    const stackDown = r.stage_int <= 4;
    const anchor = (cx > padL + innerW * 0.6) ? "end" : "start";
    const dx = anchor === "start" ? 9 : -9;
    let dy = stackDown ? 10 : -10;
    const step = stackDown ? lineSpacing : -lineSpacing;
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

  const labelsSvg = rows.map(r => {
    const cx = sx(r.n_strong_total), cy = sy(r.stage_int);
    const pick = picks.get(r.team_name);
    const fw = semis.has(r.team_name) ? 700 : 500;
    return `<text x="${(cx + pick.dx).toFixed(1)}" y="${(cy + pick.dy).toFixed(1)}"
           font-size="11.5" font-weight="${fw}" fill="currentColor"
           opacity="0.92" text-anchor="${pick.anchor}">${escapeHTML(r.team_name)}</text>`;
  }).join("");

  const xTicks = [40, 50, 60, 70, 80, 90];
  const xTickSvg = xTicks.map(x => `
    <text x="${sx(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="middle">${x}</text>
  `).join("");
  const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - 6}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
    Strong AW-JOI pairs (AW-JOI90 ≥ 0.4)</text>`;

  chemVsResultScatter.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         class="fifa-scatter-svg" role="img"
         aria-label="Chemistry density vs tournament stage scatter">
      ${yRules}
      ${xTickSvg}
      ${dotsSvg}
      ${labelsSvg}
      ${axisX}
      ${ramp}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#d4a23a; border-radius:50%; box-shadow:inset 0 0 0 1px #d4a23a;"></span> gold ring = WC22 semifinalist</span>
      <span>dot fill = total prior shared minutes (light → deep blue)</span>
      <span class="muted">Spearman ρ = +0.76 (p &lt; 0.001, n = 31).</span>
    </div>`;
}

function renderTimeVsChemScatter(rows) {
  // X = total_prior_shared (k minutes); Y = n_strong_total
  const W = 1100, H = 480;
  const padL = 80, padR = 24, padT = 22, padB = 56;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const xs = rows.map(r => r.total_prior_shared / 1000);
  const ys = rows.map(r => r.n_strong_total);
  const xmin = 0, xmax = Math.max(...xs) * 1.05 + 5;
  const ymin = Math.min(...ys) - 4, ymax = Math.max(...ys) + 4;
  const sx = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const sy = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;

  // Linear fit for visual trend
  const n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) { num += (xs[i] - mx) * (ys[i] - my); den += (xs[i] - mx) ** 2; }
  const slope = den ? num / den : 0;
  const intercept = my - slope * mx;
  const fitLine = `<line x1="${sx(xmin)}" y1="${sy(slope*xmin+intercept)}"
    x2="${sx(xmax)}" y2="${sy(slope*xmax+intercept)}"
    stroke="currentColor" stroke-width="1.0" opacity="0.35" stroke-dasharray="4 4"/>`;

  // Highlight semifinalists in gold
  const semis = new Set(["France", "Croatia", "Argentina", "Morocco"]);
  const dotColor = (r) => semis.has(r.team_name) ? "#d4a23a" : "#6b7280";

  const dots = rows.map(r => {
    const cx = sx(r.total_prior_shared / 1000), cy = sy(r.n_strong_total);
    return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5"
       fill="${dotColor(r)}" stroke="var(--bg, #0b1220)" stroke-width="1.0"/>`;
  }).join("");

  // Label every team with deterministic non-overlap placement.
  const labelW = 64, labelH = 14;
  const lineSpacing = labelH + 2;
  const intersects = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);
  const order = [...rows].sort((a, b) => b.n_strong_total - a.n_strong_total || b.total_prior_shared - a.total_prior_shared);
  const placed = [];
  const picks = new Map();
  for (const r of order) {
    const cx = sx(r.total_prior_shared / 1000), cy = sy(r.n_strong_total);
    const stackDown = r.n_strong_total < 50;
    const anchor = (cx > padL + innerW * 0.65) ? "end" : "start";
    const dx = anchor === "start" ? 8 : -8;
    let dy = stackDown ? 10 : -8;
    const step = stackDown ? lineSpacing : -lineSpacing;
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

  const labels = rows.map(r => {
    const cx = sx(r.total_prior_shared / 1000), cy = sy(r.n_strong_total);
    const pick = picks.get(r.team_name);
    const fw = semis.has(r.team_name) ? 700 : 500;
    return `<text x="${(cx + pick.dx).toFixed(1)}" y="${(cy + pick.dy).toFixed(1)}"
           font-size="11" font-weight="${fw}" fill="currentColor"
           opacity="0.92" text-anchor="${pick.anchor}">${escapeHTML(r.team_name)}</text>`;
  }).join("");

  const xTicks = [0, 50, 100, 150, 200, 250, 300];
  const xTickSvg = xTicks.map(x => `
    <text x="${sx(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="middle">${x}k</text>
  `).join("");
  const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - 6}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
    Prior shared minutes (sum across all pairs, k = thousands)</text>`;
  const axisY = `<text x="${20}" y="${padT + innerH / 2}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle"
    transform="rotate(-90, 20, ${padT + innerH / 2})">Strong AW-JOI pairs</text>`;

  timeVsChemScatter.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         class="fifa-scatter-svg" role="img"
         aria-label="Prior shared minutes vs chemistry density scatter">
      ${fitLine}
      ${xTickSvg}
      ${dots}
      ${labels}
      ${axisX}
      ${axisY}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#d4a23a"></span> WC22 semifinalists</span>
      <span class="muted">Spearman ρ = +0.43 (p = 0.017, n = 31).</span>
    </div>`;
}

// =========================================================================
// (Old players tab removed — chemistry tab above is the new headline.)
// =========================================================================
