import { loadJSON, escapeHTML, fmtNum, fmtInt, flagHTML } from "./site.js";

const wc22View = document.getElementById("wc22-view");
const wc26View = document.getElementById("wc26-view");
const wc22Table = document.getElementById("wc22-table");
const wc26Table = document.getElementById("wc26-table");
const wc22Scatter = document.getElementById("wc22-scatter");
const wc22Stories = document.getElementById("wc22-stories");
const sortEl = document.getElementById("wc22-sort");
const tabs = document.querySelectorAll(".tab-bar button");

const data = await loadJSON("data/fifa_mode.json");
if (!data) {
  wc22Table.innerHTML = `<div class="empty-state"><strong>FIFA mode data missing.</strong><span>Expected data/fifa_mode.json.</span></div>`;
} else {
  initWc22(data.wc_2022);
  initWc26(data.wc_2026_predicted);
  tabs.forEach((b) => b.addEventListener("click", () => {
    tabs.forEach((x) => x.classList.toggle("active", x === b));
    const v = b.dataset.view;
    wc22View.classList.toggle("hidden", v !== "wc22");
    wc26View.classList.toggle("hidden", v !== "wc26");
  }));
}

function stageLabel(stage_int) {
  return ({ 8: "Winner", 7: "Final", 6: "Semi", 5: "QF", 4: "R16", 2: "Group" }[stage_int] || "—");
}

function renderTable(container, rows, options = {}) {
  const showResult = options.showResult ?? true;
  const showQual   = options.showQual   ?? false;
  const head = `
    <thead><tr>
      <th>Team</th>
      <th class="num" title="EA Sports' published team Overall">Overall</th>
      <th class="num">ATT</th>
      <th class="num">MID</th>
      <th class="num">DEF</th>
      <th class="num" title="Top-11 avg minus 12-23 avg. Higher = more top-loaded squad.">Depth gap</th>
      ${showResult ? '<th>Result</th><th class="num" title="Paper rank minus result rank. + = overperformed.">Δ rank</th>' : ''}
      ${showQual ? '<th>Qualifier</th>' : ''}
      <th>Stars</th>
    </tr></thead>`;

  // Compute paper rank
  const sortedByOverall = [...rows].sort((a, b) => b.overall - a.overall);
  const paperRank = new Map(sortedByOverall.map((r, i) => [r.team, i + 1]));

  const body = rows.map((r) => {
    const pr = paperRank.get(r.team);
    const dRank = showResult ? (pr - r.result_rank) : null;
    const dCls = dRank == null ? "" : dRank > 0 ? "chip green" : dRank < 0 ? "chip red" : "chip";
    return `<tr>
      <td><span class="team-cell">${flagHTML(r.flag)} ${escapeHTML(r.team)}</span></td>
      <td class="num"><strong class="tabular">${r.overall}</strong> <span class="muted small">(#${pr})</span></td>
      <td class="num tabular">${r.att}</td>
      <td class="num tabular">${r.mid}</td>
      <td class="num tabular">${r.def}</td>
      <td class="num tabular">${r.depth_gap.toFixed(1)}</td>
      ${showResult ? `<td>${escapeHTML(r.result)} <span class="muted small">#${r.result_rank}</span></td>
                      <td class="num"><span class="${dCls} tabular">${dRank > 0 ? "+" + dRank : dRank}</span></td>` : ''}
      ${showQual ? `<td><span class="small muted">${escapeHTML(r.qualification || "—")}</span></td>` : ''}
      <td class="small">${(r.stars || []).map(s => `<span class="chip">${escapeHTML(s)}</span>`).join(" ")}</td>
    </tr>`;
  }).join("");

  container.innerHTML = `<div class="table-wrap"><table class="data-table fifa-data-table">${head}<tbody>${body}</tbody></table></div>`;
}

function initWc22(rows) {
  function applySort() {
    const v = sortEl.value;
    const sortedByOverall = [...rows].sort((a, b) => b.overall - a.overall);
    const paperRank = new Map(sortedByOverall.map((r, i) => [r.team, i + 1]));
    let sorted;
    if (v === "overall") sorted = sortedByOverall;
    else if (v === "result_rank") sorted = [...rows].sort((a, b) => a.result_rank - b.result_rank);
    else if (v === "overperformance") sorted = [...rows].sort((a, b) =>
      (paperRank.get(b.team) - b.result_rank) - (paperRank.get(a.team) - a.result_rank));
    else if (v === "depth_gap") sorted = [...rows].sort((a, b) => b.depth_gap - a.depth_gap);
    else sorted = sortedByOverall;
    renderTable(wc22Table, sorted, { showResult: true, showQual: false });
  }
  sortEl.addEventListener("change", applySort);
  applySort();

  renderScatter(rows);
  renderStories(rows);
}

function initWc26(rows) {
  const sorted = [...rows].sort((a, b) => b.overall - a.overall);
  renderTable(wc26Table, sorted, { showResult: false, showQual: true });
}

function renderScatter(rows) {
  // Big enough that labels can breathe. Aspect ~16:9 reads natural on wide
  // monitors; on mobile the SVG shrinks proportionally via width:100%.
  const W = 1200, H = 680, padL = 78, padR = 32, padT = 28, padB = 78;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const xs = rows.map(r => r.overall);
  const xmin = Math.min(...xs) - 1, xmax = Math.max(...xs) + 1;
  const ymin = 1, ymax = 9;  // stage_int range
  const sx = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const sy = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;

  // Diagonal trend line: ranks → ranks. Map overall to expected stage based on rank ordering.
  const sortedByOverall = [...rows].sort((a, b) => b.overall - a.overall);
  const expectedStage = (rank) => rank === 1 ? 8 : rank === 2 ? 7 : rank <= 4 ? 6 : rank <= 8 ? 5 : rank <= 16 ? 4 : 2;
  const diagonalPts = sortedByOverall.map((r, i) => `${sx(r.overall)},${sy(expectedStage(i+1))}`);

  // Gridlines
  const yTicks = [2, 4, 5, 6, 7, 8];
  const yLabels = { 2: "Group", 4: "R16", 5: "QF", 6: "Semi", 7: "Final", 8: "Winner" };
  const xTicks = [70, 75, 80, 85];

  const grid = [
    ...yTicks.map(y => `<line x1="${padL}" y1="${sy(y)}" x2="${W-padR}" y2="${sy(y)}" stroke="currentColor" stroke-width="0.5" opacity="0.16"/>`),
    ...yTicks.map(y => `<text x="${padL - 10}" y="${sy(y) + 5}" font-size="15" fill="currentColor" opacity="0.85" text-anchor="end">${yLabels[y]}</text>`),
    ...xTicks.map(x => `<text x="${sx(x)}" y="${H - padB + 22}" font-size="14" fill="currentColor" opacity="0.85" text-anchor="middle">${x}</text>`),
    `<text x="${W/2}" y="${H - 14}" font-size="15" fill="currentColor" opacity="0.95" text-anchor="middle">FIFA 23 team Overall (paper talent)</text>`,
    `<text transform="translate(${padL - 52},${padT + innerH/2}) rotate(-90)" font-size="15" fill="currentColor" opacity="0.95" text-anchor="middle">Tournament stage reached</text>`,
  ].join("");

  const diag = `<polyline points="${diagonalPts.join(' ')}" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 5" opacity="0.4"/>`;

  // Position labels so they don't collide. Each team gets a candidate slot
  // (right of dot); if it overlaps an already-placed label, try left, then
  // stagger vertically. Greedy but works well for ~32 points.
  const labelW = 64;   // approx px label box width at 13px font
  const labelH = 17;
  const placed = [];  // {x1,y1,x2,y2}
  const intersects = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);

  const annotated = rows.map((r) => {
    const cx = sx(r.overall), cy = sy(r.stage_int);
    const rank = sortedByOverall.findIndex(x => x.team === r.team) + 1;
    const exp = expectedStage(rank);
    const over = r.stage_int - exp;
    const color = over >= 1 ? "#54c875" : over <= -1 ? "#e07474" : "#a0a8b3";

    // Candidate label positions: right, left, below-right, above-right, below-left, above-left
    const candidates = [
      { anchor: "start", dx:  10, dy: 4 },
      { anchor: "end",   dx: -10, dy: 4 },
      { anchor: "start", dx:  10, dy: 18 },
      { anchor: "start", dx:  10, dy: -10 },
      { anchor: "end",   dx: -10, dy: 18 },
      { anchor: "end",   dx: -10, dy: -10 },
    ];
    let pick = candidates[0];
    for (const c of candidates) {
      const lx = cx + c.dx;
      const ly = cy + c.dy;
      const box = c.anchor === "start"
        ? { x1: lx, y1: ly - labelH, x2: lx + labelW, y2: ly + 2 }
        : { x1: lx - labelW, y1: ly - labelH, x2: lx, y2: ly + 2 };
      // also keep inside chart area
      if (box.x1 < padL || box.x2 > W - padR || box.y1 < padT || box.y2 > H - padB) continue;
      if (!placed.some(p => intersects(p, box))) {
        pick = c; placed.push(box); break;
      }
    }
    return { r, cx, cy, color, pick };
  });

  // Dots first (under labels)
  const dotsSvg = annotated.map(({ r, cx, cy, color }) =>
    `<circle cx="${cx}" cy="${cy}" r="7.5" fill="${color}" fill-opacity="0.85" stroke="#0b1220" stroke-width="1.0"/>`
  ).join("");
  const labelsSvg = annotated.map(({ r, cx, cy, pick }) =>
    `<text x="${cx + pick.dx}" y="${cy + pick.dy}" font-size="13" font-weight="500" fill="currentColor" opacity="0.95" text-anchor="${pick.anchor}">${escapeHTML(r.team)}</text>`
  ).join("");

  wc22Scatter.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" class="spark-svg" role="img" aria-label="Paper rating vs tournament stage scatter">
      ${grid}
      ${diag}
      ${dotsSvg}
      ${labelsSvg}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#54c875"></span> overperformed</span>
      <span><span class="dot" style="background:#a0a8b3"></span> matched paper</span>
      <span><span class="dot" style="background:#e07474"></span> underperformed</span>
      <span class="muted">Dashed diagonal = result that matches paper rank.</span>
    </div>`;
}

function renderStories(rows) {
  const sortedByOverall = [...rows].sort((a, b) => b.overall - a.overall);
  const paperRank = new Map(sortedByOverall.map((r, i) => [r.team, i + 1]));
  const withDelta = rows.map((r) => ({ ...r, dRank: paperRank.get(r.team) - r.result_rank }));

  const overperformers = [...withDelta].sort((a, b) => b.dRank - a.dRank).slice(0, 3);
  const underperformers = [...withDelta].sort((a, b) => a.dRank - b.dRank).slice(0, 2);
  const stories = [...overperformers, ...underperformers];

  wc22Stories.innerHTML = stories.map((r) => {
    const dr = r.dRank;
    const cls = dr > 0 ? "over" : "under";
    const heading = dr > 0 ? `+${dr} ranks better than paper` : `${dr} ranks worse than paper`;
    return `<article class="story-card ${cls}">
      <header>${flagHTML(r.flag)} <strong>${escapeHTML(r.team)}</strong>
        <span class="muted small">paper #${paperRank.get(r.team)} → ${escapeHTML(r.result)} #${r.result_rank}</span></header>
      <div class="story-heading">${heading}</div>
      <p class="small">${escapeHTML(r.notes || "")}</p>
    </article>`;
  }).join("");
}
