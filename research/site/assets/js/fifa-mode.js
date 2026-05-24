import { loadJSON, escapeHTML, fmtNum, flagHTML, posChip, makeSortableTable } from "./site.js";

// --- DOM handles ---------------------------------------------------------
const sections = {
  "wc22-teams":   document.getElementById("wc22-teams-view"),
  "wc22-players": document.getElementById("wc22-players-view"),
  "wc26":         document.getElementById("wc26-view"),
};
const tabs = document.querySelectorAll(".mode-bar button");

const wc22Table   = document.getElementById("wc22-table");
const wc22Scatter = document.getElementById("wc22-scatter");
const wc22Stories = document.getElementById("wc22-stories");
const teamSortEl  = document.getElementById("wc22-sort");

const playersScatter = document.getElementById("players-scatter");
const playersStories = document.getElementById("players-stories");
const playersTable   = document.getElementById("players-table");
const playersRoleEl  = document.getElementById("players-role");
const playersMinEl   = document.getElementById("players-min");

const wc26Table = document.getElementById("wc26-table");

// --- Mode switching ------------------------------------------------------
tabs.forEach((b) => b.addEventListener("click", () => {
  tabs.forEach((x) => x.classList.toggle("active", x === b));
  const v = b.dataset.view;
  Object.entries(sections).forEach(([k, el]) => el.classList.toggle("active", k === v));
}));

// --- Load all data in parallel -------------------------------------------
const [teams, players, wc26] = await Promise.all([
  loadJSON("data/fifa_mode.json"),
  loadJSON("data/fifa_players_wc22.json"),
  loadJSON("data/wc26_rosters.json"),
]);

if (!teams) {
  wc22Table.innerHTML = `<div class="empty-state"><strong>FIFA team data missing.</strong></div>`;
} else {
  initTeamsTab(teams.wc_2022);
}
if (!players) {
  playersTable.innerHTML = `<div class="empty-state"><strong>Player FIFA 23 data missing.</strong></div>`;
} else {
  initPlayersTab(players.players);
}
if (!wc26) {
  wc26Table.innerHTML = `<div class="empty-state"><strong>WC26 roster data missing.</strong></div>`;
} else {
  initWc26Tab(wc26.teams);
}

// =========================================================================
// TEAMS TAB (WC22 paper vs result)
// =========================================================================
function stageLabel(stage_int) {
  return ({ 8: "Winner", 7: "Final", 6: "Semi", 5: "QF", 4: "R16", 2: "Group" }[stage_int] || "—");
}

function renderTeamTable(container, rows, options = {}) {
  const showResult = options.showResult ?? true;
  const showQual   = options.showQual   ?? false;
  const showLicense = options.showLicense ?? false;
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

  const sortedByOverall = [...rows].sort((a, b) => b.overall - a.overall);
  const paperRank = new Map(sortedByOverall.map((r, i) => [r.team, i + 1]));

  const body = rows.map((r) => {
    const pr = paperRank.get(r.team);
    const dRank = showResult ? (pr - r.result_rank) : null;
    const dCls = dRank == null ? "" : dRank > 0 ? "chip green" : dRank < 0 ? "chip red" : "chip";
    const licNote = showLicense && r.ea_licensed === false
      ? ` <span class="muted small" title="EA FC 26 does not license this nation; rating is aggregated from individual player Overalls.">analyst proxy</span>`
      : "";
    const starsHTML = (r.stars || []).map((s) => {
      if (typeof s === "string") return `<span class="chip">${escapeHTML(s)}</span>`;
      // wc26 format: {name, overall, position}
      return `<span class="chip" title="${escapeHTML(s.position || "")}">${escapeHTML(s.name)} <span class="muted">${s.overall}</span></span>`;
    }).join(" ");
    return `<tr>
      <td><span class="team-cell">${flagHTML(r.flag)} ${escapeHTML(r.team)}</span>${licNote}</td>
      <td class="num"><strong class="tabular">${r.overall}</strong> <span class="muted small">(#${pr})</span></td>
      <td class="num tabular">${r.att}</td>
      <td class="num tabular">${r.mid}</td>
      <td class="num tabular">${r.def}</td>
      <td class="num tabular">${r.depth_gap.toFixed(1)}</td>
      ${showResult ? `<td>${escapeHTML(r.result)} <span class="muted small">#${r.result_rank}</span></td>
                      <td class="num"><span class="${dCls} tabular">${dRank > 0 ? "+" + dRank : dRank}</span></td>` : ''}
      ${showQual ? `<td><span class="small muted">${escapeHTML(r.qualification || "—")}</span></td>` : ''}
      <td class="small">${starsHTML}</td>
    </tr>`;
  }).join("");

  container.innerHTML = `<div class="table-wrap"><table class="data-table fifa-data-table">${head}<tbody>${body}</tbody></table></div>`;
}

function initTeamsTab(rows) {
  function applySort() {
    const v = teamSortEl.value;
    const sortedByOverall = [...rows].sort((a, b) => b.overall - a.overall);
    const paperRank = new Map(sortedByOverall.map((r, i) => [r.team, i + 1]));
    let sorted;
    if (v === "overall") sorted = sortedByOverall;
    else if (v === "result_rank") sorted = [...rows].sort((a, b) => a.result_rank - b.result_rank);
    else if (v === "overperformance") sorted = [...rows].sort((a, b) =>
      (paperRank.get(b.team) - b.result_rank) - (paperRank.get(a.team) - a.result_rank));
    else if (v === "depth_gap") sorted = [...rows].sort((a, b) => b.depth_gap - a.depth_gap);
    else sorted = sortedByOverall;
    renderTeamTable(wc22Table, sorted, { showResult: true, showQual: false });
  }
  teamSortEl.addEventListener("change", applySort);
  applySort();

  renderTeamScatter(rows);
  renderTeamStories(rows);
}

function initWc26Tab(rows) {
  const sorted = [...rows].sort((a, b) => b.overall - a.overall);
  renderTeamTable(wc26Table, sorted, { showResult: false, showQual: true, showLicense: true });
}

function renderTeamScatter(rows) {
  const W = 1100, H = 520;
  const padL = 86, padR = 24, padT = 22, padB = 56;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const xs = rows.map(r => r.overall);
  const xmin = Math.min(...xs) - 1, xmax = Math.max(...xs) + 1;
  const ymin = 1.4, ymax = 8.4;
  const sx = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const sy = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;

  const sortedByOverall = [...rows].sort((a, b) => b.overall - a.overall);
  const expectedStage = (rank) => rank === 1 ? 8 : rank === 2 ? 7 : rank <= 4 ? 6 : rank <= 8 ? 5 : rank <= 16 ? 4 : 2;

  const yLevels = [
    { y: 2, label: "Group" }, { y: 4, label: "R16" }, { y: 5, label: "QF" },
    { y: 6, label: "Semi" }, { y: 7, label: "Final" }, { y: 8, label: "Winner" },
  ];
  const xTicks = [70, 75, 80, 85];

  const yRules = yLevels.map(({ y, label }) => `
    <line x1="${padL}" y1="${sy(y)}" x2="${W - padR}" y2="${sy(y)}"
          stroke="currentColor" stroke-width="0.5" opacity="0.10"/>
    <text x="${padL - 8}" y="${sy(y) + 4}" font-size="12" font-weight="500"
          fill="currentColor" opacity="0.65" text-anchor="end">${label}</text>
  `).join("");
  const xTickSvg = xTicks.map(x => `
    <text x="${sx(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="middle">${x}</text>
  `).join("");

  const diagonalPts = sortedByOverall.map((r, i) =>
    `${sx(r.overall).toFixed(1)},${sy(expectedStage(i + 1)).toFixed(1)}`);
  const diag = `<polyline points="${diagonalPts.join(' ')}" fill="none"
    stroke="currentColor" stroke-width="0.8" opacity="0.32"/>`;

  const labelW = 58, labelH = 14;
  const placed = [];
  const intersects = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);

  const annotated = rows.map((r) => {
    const cx = sx(r.overall), cy = sy(r.stage_int);
    const rank = sortedByOverall.findIndex(x => x.team === r.team) + 1;
    const exp = expectedStage(rank);
    const over = r.stage_int - exp;
    const color = over >= 1 ? "#3ea16a" : over <= -1 ? "#c25b5b" : "#6b7280";

    const slots = [
      { anchor: "start", dx:  9, dy: 4 },
      { anchor: "end",   dx: -9, dy: 4 },
      { anchor: "start", dx:  9, dy: -10 },
      { anchor: "start", dx:  9, dy: 16 },
      { anchor: "end",   dx: -9, dy: -10 },
      { anchor: "end",   dx: -9, dy: 16 },
    ];
    let pick = slots[0];
    for (const c of slots) {
      const lx = cx + c.dx, ly = cy + c.dy;
      const box = c.anchor === "start"
        ? { x1: lx, y1: ly - labelH, x2: lx + labelW, y2: ly + 2 }
        : { x1: lx - labelW, y1: ly - labelH, x2: lx, y2: ly + 2 };
      if (box.x1 < padL - 4 || box.x2 > W - padR + 4) continue;
      if (box.y1 < padT - 4 || box.y2 > H - padB + 4) continue;
      if (!placed.some(p => intersects(p, box))) { pick = c; placed.push(box); break; }
    }
    return { r, cx, cy, color, pick };
  });

  const dotsSvg = annotated.map(({ cx, cy, color }) =>
    `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5.5"
             fill="${color}" stroke="var(--bg, #0b1220)" stroke-width="1.2"/>`
  ).join("");
  const labelsSvg = annotated.map(({ r, cx, cy, pick }) =>
    `<text x="${(cx + pick.dx).toFixed(1)}" y="${(cy + pick.dy).toFixed(1)}"
           font-size="11.5" font-weight="500" fill="currentColor"
           opacity="0.92" text-anchor="${pick.anchor}">${escapeHTML(r.team)}</text>`
  ).join("");

  const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - 6}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
    FIFA 23 team Overall</text>`;

  wc22Scatter.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         class="fifa-scatter-svg" role="img"
         aria-label="Paper rating vs tournament stage scatter">
      ${yRules}
      ${xTickSvg}
      ${diag}
      ${dotsSvg}
      ${labelsSvg}
      ${axisX}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#3ea16a"></span> overperformed paper rank</span>
      <span><span class="dot" style="background:#6b7280"></span> matched</span>
      <span><span class="dot" style="background:#c25b5b"></span> underperformed</span>
      <span class="muted">Curve traces "result that matches paper rank".</span>
    </div>`;
}

function renderTeamStories(rows) {
  const sortedByOverall = [...rows].sort((a, b) => b.overall - a.overall);
  const paperRank = new Map(sortedByOverall.map((r, i) => [r.team, i + 1]));
  const withDelta = rows.map((r) => ({ ...r, dRank: paperRank.get(r.team) - r.result_rank }));

  const overperformers  = [...withDelta].sort((a, b) => b.dRank - a.dRank).slice(0, 3);
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

// =========================================================================
// PLAYERS TAB (WC22 FIFA23 vs OI/90)
// =========================================================================
let allPlayers = [];

function linfit(xs, ys) {
  const n = xs.length;
  if (n < 2) return { slope: 0, intercept: 0 };
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    num += (xs[i] - mx) * (ys[i] - my);
    den += (xs[i] - mx) ** 2;
  }
  const slope = den ? num / den : 0;
  return { slope, intercept: my - slope * mx };
}

function initPlayersTab(allRows) {
  allPlayers = allRows;
  // Compute residuals using FWD/MID 150+ min sample (the headline scatter sample)
  const fitSample = allRows.filter((r) => (r.role === "FWD" || r.role === "MID") && r.minutes >= 150);
  const { slope, intercept } = linfit(
    fitSample.map((r) => r.fifa23_overall),
    fitSample.map((r) => r.oi_per90),
  );
  allRows.forEach((r) => {
    const pred = slope * r.fifa23_overall + intercept;
    r.resid = +(r.oi_per90 - pred).toFixed(3);
  });

  renderPlayersScatter(fitSample, { slope, intercept });
  renderPlayerStories(allRows);

  let tableHandle = null;
  function refreshTable() {
    const minMin = +playersMinEl.value;
    const role = playersRoleEl.value;
    let view = allPlayers.filter((r) => r.minutes >= minMin && r.role !== "GK");
    if (role !== "all") view = view.filter((r) => r.role === role);
    if (!tableHandle) {
      tableHandle = makeSortableTable({
        data: view,
        container: playersTable,
        emptyLabel: "No players match the current filters.",
        columns: [
          { key: "name", label: "Player", render: (r) =>
              `${flagHTML(r.flag)} ${escapeHTML(r.name)}${posChip(r.position)}` },
          { key: "team", label: "Team" },
          { key: "fifa23_overall", label: "FIFA 23", num: true, digits: 0, defaultDir: "desc",
            render: (r) => `<span class="tabular">${r.fifa23_overall}</span>` },
          { key: "oi_per90", label: "OI/90", num: true, digits: 2, defaultSort: true, defaultDir: "desc",
            render: (r) => `<span class="tabular">${r.oi_per90.toFixed(2)}</span>` },
          { key: "minutes", label: "Min", num: true, digits: 0,
            render: (r) => `<span class="muted tabular">${Math.round(r.minutes)}</span>` },
          { key: "resid", label: "Δ resid", num: true, digits: 2,
            render: (r) => {
              const cls = r.resid > 0.3 ? "delta-pos" : r.resid < -0.3 ? "delta-neg" : "";
              const sign = r.resid > 0 ? "+" : "";
              return `<span class="tabular ${cls}">${sign}${r.resid.toFixed(2)}</span>`;
            } },
        ],
      });
      tableHandle.render();
    } else {
      tableHandle.setData(view);
    }
  }
  playersMinEl.addEventListener("change", refreshTable);
  playersRoleEl.addEventListener("change", refreshTable);
  refreshTable();
}

function renderPlayersScatter(rows, fit) {
  // Tufte-style: minimal chrome, named points for the storyline players, anonymous dots otherwise.
  const W = 1100, H = 540;
  const padL = 80, padR = 24, padT = 22, padB = 56;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const xs = rows.map(r => r.fifa23_overall);
  const ys = rows.map(r => r.oi_per90);
  const xmin = Math.min(...xs) - 1, xmax = Math.max(...xs) + 1;
  const ymin = Math.min(...ys, -0.4) - 0.1, ymax = Math.max(...ys) + 0.15;
  const sx = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const sy = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;

  // Reference y rules (OI/90 = 0 and the median)
  const sorted = [...ys].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const yRules = [
    { y: 0, label: "OI/90 = 0", op: 0.18 },
    { y: median, label: "median", op: 0.10 },
  ].map(({ y, label, op }) => `
    <line x1="${padL}" y1="${sy(y)}" x2="${W - padR}" y2="${sy(y)}"
          stroke="currentColor" stroke-width="0.5" opacity="${op}"/>
    <text x="${padL - 8}" y="${sy(y) + 4}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="end">${label}</text>
  `).join("");

  const xTicks = [70, 75, 80, 85, 90];
  const xTickSvg = xTicks.map(x => `
    <line x1="${sx(x)}" y1="${padT + innerH}" x2="${sx(x)}" y2="${padT + innerH + 4}"
          stroke="currentColor" stroke-width="0.6" opacity="0.4"/>
    <text x="${sx(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="middle">${x}</text>
  `).join("");

  // Fit line
  const fitX1 = xmin + 0.5, fitX2 = xmax - 0.5;
  const fitY1 = fit.slope * fitX1 + fit.intercept;
  const fitY2 = fit.slope * fitX2 + fit.intercept;
  const fitLine = `<line x1="${sx(fitX1)}" y1="${sy(fitY1)}"
    x2="${sx(fitX2)}" y2="${sy(fitY2)}"
    stroke="currentColor" stroke-width="1.0" opacity="0.4"
    stroke-dasharray="4 4"/>`;
  const slopeLabel = `<text x="${sx(fitX2) - 6}" y="${sy(fitY2) - 8}"
    font-size="10.5" fill="currentColor" opacity="0.5" text-anchor="end">
    fit slope ≈ ${fit.slope.toFixed(3)} (flat!)</text>`;

  // Players to label: top-5 over/under by residual, plus a few storyline picks
  const byResid = [...rows].sort((a, b) => b.resid - a.resid);
  const headlineNames = new Set([
    ...byResid.slice(0, 5).map(r => r.name),
    ...byResid.slice(-5).map(r => r.name),
    "Kylian Mbappé", "Lionel Messi", "Cristiano Ronaldo", "Neymar",
    "Mohammed Kudus", "Bukayo Saka", "Harry Kane",
  ]);

  // Dot color by residual sign
  const dotColor = (r) => r.resid >= 0.4 ? "#3ea16a" : r.resid <= -0.4 ? "#c25b5b" : "#6b7280";

  // Anonymous dots (small)
  const anonDots = rows.filter(r => !headlineNames.has(r.name))
    .map(r => `<circle cx="${sx(r.fifa23_overall).toFixed(1)}" cy="${sy(r.oi_per90).toFixed(1)}"
       r="3" fill="${dotColor(r)}" opacity="0.55"/>`).join("");

  // Named dots (slightly larger + label)
  const named = rows.filter(r => headlineNames.has(r.name));
  // Simple non-collision placement: alternate dx direction based on whether the point is above or below the fit line
  const placedBoxes = [];
  const labelW = 76, labelH = 13;
  const intersects = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);

  const namedSvg = named.map(r => {
    const cx = sx(r.fifa23_overall), cy = sy(r.oi_per90);
    const slots = [
      { dx:  9, dy: 4,   anchor: "start" },
      { dx: -9, dy: 4,   anchor: "end" },
      { dx:  9, dy: -10, anchor: "start" },
      { dx: -9, dy: -10, anchor: "end" },
      { dx:  9, dy: 16,  anchor: "start" },
      { dx: -9, dy: 16,  anchor: "end" },
    ];
    let pick = slots[0];
    for (const c of slots) {
      const lx = cx + c.dx, ly = cy + c.dy;
      const box = c.anchor === "start"
        ? { x1: lx, y1: ly - labelH, x2: lx + labelW, y2: ly + 2 }
        : { x1: lx - labelW, y1: ly - labelH, x2: lx, y2: ly + 2 };
      if (box.x1 < padL - 4 || box.x2 > W - padR + 4) continue;
      if (box.y1 < padT - 4 || box.y2 > H - padB + 4) continue;
      if (!placedBoxes.some(p => intersects(p, box))) { pick = c; placedBoxes.push(box); break; }
    }
    return `<g>
      <circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4.5"
              fill="${dotColor(r)}" stroke="var(--bg, #0b1220)" stroke-width="1.2"/>
      <text x="${(cx + pick.dx).toFixed(1)}" y="${(cy + pick.dy).toFixed(1)}"
            font-size="11" font-weight="500" fill="currentColor"
            opacity="0.92" text-anchor="${pick.anchor}">${escapeHTML(r.name)}</text>
    </g>`;
  }).join("");

  const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - 6}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
    FIFA 23 player Overall</text>`;
  const axisY = `<text x="${20}" y="${padT + innerH / 2}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle"
    transform="rotate(-90, 20, ${padT + innerH / 2})">WC22 OI/90</text>`;

  playersScatter.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         class="fifa-scatter-svg" role="img"
         aria-label="Player paper rating vs WC22 OI/90 scatter">
      ${yRules}
      ${xTickSvg}
      ${fitLine}
      ${slopeLabel}
      ${anonDots}
      ${namedSvg}
      ${axisX}
      ${axisY}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#3ea16a"></span> outperformed FIFA 23</span>
      <span><span class="dot" style="background:#6b7280"></span> matched</span>
      <span><span class="dot" style="background:#c25b5b"></span> underperformed</span>
      <span class="muted">Sample: 150+ minutes, forwards and midfielders. n=${rows.length}.</span>
    </div>`;
}

function renderPlayerStories(allRows) {
  // Use the same fit sample's residuals.
  const sample = allRows.filter((r) => (r.role === "FWD" || r.role === "MID") && r.minutes >= 150);
  const top = [...sample].sort((a, b) => b.resid - a.resid).slice(0, 3);
  const bot = [...sample].sort((a, b) => a.resid - b.resid).slice(0, 2);

  const cards = [...top, ...bot].map((r) => {
    const isOver = r.resid > 0;
    const cls = isOver ? "over" : "under";
    const heading = isOver
      ? `+${r.resid.toFixed(2)} OI/90 above paper`
      : `${r.resid.toFixed(2)} OI/90 below paper`;
    return `<article class="story-card ${cls}">
      <header>${flagHTML(r.flag)} <strong>${escapeHTML(r.name)}</strong>
        <span class="muted small">${escapeHTML(r.team)} · ${escapeHTML(r.position)}</span></header>
      <div class="story-heading">${heading}</div>
      <p class="small">FIFA 23 said ${r.fifa23_overall}. The tournament said
        OI/90 = ${r.oi_per90.toFixed(2)} over ${Math.round(r.minutes)} minutes.</p>
    </article>`;
  }).join("");

  playersStories.innerHTML = cards;
}
