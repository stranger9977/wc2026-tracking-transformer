/* FIFA Mode — Tab 5.
   Story: talent is the floor (top-5 rule), chemistry is the multiplier.
   Renders:
     1. Historical top-rated-vs-winner table (data/historical_fifa.json)
     2. FIFA-23 Overall vs Team Chemistry Density scatter
     3. FIFA-23 Overall vs History Index scatter
     4. WC26 paper-field candidate table (data/wc26_rosters.json)
   Style mirrors the TCD-vs-finish scatter on chemistry-wins.js. */

import { loadJSON, escapeHTML, flagHTML } from "./site.js";

const SEMIS = new Set(["France", "Croatia", "Argentina", "Morocco"]);

// Multi-year scatter config — must be declared before the top-level calls
// below or renderFifaVsFinish hits a temporal-dead-zone error.
const ALL_YEARS = [2006, 2010, 2014, 2018, 2022];
const DEFAULT_YEARS = new Set([2022]);
const YEAR_COLOR = {
  2006: "#7aa6c2",
  2010: "#9b87c8",
  2014: "#d49a6a",
  2018: "#6dbf9e",
  2022: "#d4a23a",
};

const [history, teamRows, wc26, multiYear] = await Promise.all([
  loadJSON("data/historical_fifa.json"),
  loadJSON("data/team_chemistry_vs_paper.json"),
  loadJSON("data/wc26_rosters.json"),
  loadJSON("data/fifa_multi_year.json").catch(() => null),
]);

renderHistorical(history);
renderWc26(wc26);

if (Array.isArray(teamRows)) {
  const data = teamRows.filter(
    (r) => r.overall != null && r.tcd != null && r.stage_int != null && r.history_index_count != null,
  );

  // Build the unified multi-year pool for the FIFA-vs-finish scatter.
  // - WC22 rows come from team_chemistry_vs_paper.json (the existing 30-team set).
  // - Prior WCs (2006-2018) come from fifa_multi_year.json (fifaindex scrape).
  const wc22Rows = data.map((r) => ({
    team: r.team_name,
    year: 2022,
    overall: r.overall,
    stage_int: r.stage_int,
    stage_label: stageLabelFromInt(r.stage_int),
  }));
  const priorRows = (multiYear?.rows ?? [])
    .filter((r) => r.year !== 2022)
    .map((r) => ({
      team: r.team,
      year: r.year,
      overall: r.overall,
      stage_int: r.stage_int,
      stage_label: r.stage_label,
    }));
  const allYearRows = [...wc22Rows, ...priorRows];

  renderFifaVsFinish(allYearRows);
  renderFifaVsTcd(data);
  renderFifaVsHi(data);
}

function stageLabelFromInt(s) {
  return ({2: "Group", 4: "R16", 5: "QF", 6: "Semi", 7: "Final", 8: "Winner"})[s] ?? "—";
}

/* ---------------- FIFA Overall vs WC finish (multi-year) ---------------- */

function renderFifaVsFinish(allRows) {
  const mount = document.getElementById("fifa-vs-finish-scatter");
  const ctrl = document.getElementById("fifa-vs-finish-year-toggle");
  if (!mount) return;

  const activeYears = new Set(DEFAULT_YEARS);

  // Build the year-toggle UI.
  if (ctrl) {
    const yearsPresent = ALL_YEARS.filter((y) => allRows.some((r) => r.year === y));
    ctrl.innerHTML = yearsPresent.map((y) => {
      const checked = activeYears.has(y) ? "checked" : "";
      const n = allRows.filter((r) => r.year === y).length;
      return `<label class="wb-toggle">
        <input type="checkbox" data-year="${y}" ${checked}>
        <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${YEAR_COLOR[y]};vertical-align:1px;margin-right:5px"></span>WC ${String(y).slice(2)} <span class="dim small">(n=${n})</span></span>
      </label>`;
    }).join("");
    ctrl.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const y = Number(cb.dataset.year);
        if (cb.checked) activeYears.add(y); else activeYears.delete(y);
        if (activeYears.size === 0) { activeYears.add(2022); ctrl.querySelector('input[data-year="2022"]').checked = true; }
        draw();
      });
    });
  }

  function draw() {
    const rows = allRows.filter((r) => activeYears.has(r.year));
    const singleYear = activeYears.size === 1 ? [...activeYears][0] : null;

    const W = 1100, H = 500;
    const padL = 86, padR = 48, padT = 22, padB = 64;
    const innerW = W - padL - padR;
    const innerH = H - padT - padB;

    const xs = rows.map((r) => r.overall);
    const ys = rows.map((r) => r.stage_int);
    const xmin = Math.min(...xs) - 2, xmax = Math.max(...xs) + 2;
    const ymin = 1.5, ymax = 8.5;
    const sxV = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
    const syV = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;
    // Jitter Y by tiny per-year offset when multiple years are on, so dots
    // at the same (overall, stage) don't fully overlap.
    const yJitter = (r) => {
      if (singleYear) return 0;
      const yrs = [...activeYears].sort();
      const idx = yrs.indexOf(r.year);
      const span = (yrs.length - 1) || 1;
      return (idx / span - 0.5) * 0.45;  // ±0.225 stage units
    };
    const sx = (r) => sxV(r.overall);
    const sy = (r) => syV(r.stage_int + yJitter(r));

    const rho = spearman(xs, ys);
    const rhoEl = document.getElementById("rho-fifa-finish");
    if (rhoEl) {
      const yrTxt = singleYear
        ? `WC ${String(singleYear).slice(2)}`
        : [...activeYears].sort().map((y) => `'${String(y).slice(2)}`).join("+");
      rhoEl.innerHTML =
        `(${yrTxt} — Spearman &rho; = ${rho >= 0 ? "+" : ""}${rho.toFixed(3)}, n = ${rows.length})`;
    }

    const stageLabels = {2: "Group", 4: "R16", 5: "QF", 6: "Semi", 7: "Final", 8: "Winner"};
    const xTicks = [70, 74, 78, 82, 86];
    const xTickSvg = xTicks.filter((v) => v >= xmin && v <= xmax).map((x) => `
      <text x="${sxV(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
            opacity="0.55" text-anchor="middle">${x}</text>`).join("");
    const yRules = [2, 4, 5, 6, 7, 8].map((y) => `
      <line x1="${padL}" y1="${syV(y)}" x2="${W - padR}" y2="${syV(y)}"
            stroke="currentColor" stroke-width="0.5" opacity="0.10"/>
      <text x="${padL - 8}" y="${syV(y) + 4}" font-size="11" fill="currentColor"
            opacity="0.6" text-anchor="end">${stageLabels[y]}</text>`).join("");

    // Dots: fill = year color; ring = semifinalist of that year (stage_int >= 6).
    const dots = rows.map((r) => {
      const cx = sx(r), cy = sy(r);
      const ring = (r.stage_int >= 6)
        ? `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="9" fill="none" stroke="#d4a23a" stroke-width="1.6" opacity="0.85"/>`
        : "";
      return `${ring}<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5.5"
               fill="${YEAR_COLOR[r.year]}" stroke="var(--bg, #0b1220)" stroke-width="1.2"/>`;
    }).join("");

    // Labels: "Team 'YY" (always include year so multi-year reads cleanly).
    const labelFor = (r) => `${r.team} '${String(r.year).slice(2)}`;
    const labelKey = (r) => `${r.team}__${r.year}`;
    const picks = placeLabels(rows, sx, sy,
      (r) => r.stage_int * 10000 + r.overall * 10 + r.year - 2000,
      { left: padL, top: padT, innerW, innerH },
      labelKey);
    const labels = rows.map((r) => {
      const cx = sx(r), cy = sy(r);
      const p = picks.get(labelKey(r));
      const semiBold = r.stage_int >= 6 ? 700 : 500;
      return `<text x="${(cx + p.dx).toFixed(1)}" y="${(cy + p.dy).toFixed(1)}"
             font-size="11" font-weight="${semiBold}" fill="currentColor"
             opacity="0.92" text-anchor="${p.anchor}">${escapeHTML(labelFor(r))}</text>`;
    }).join("");

    const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - padB + 38}"
      font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
      FIFA Overall (edition shipped immediately before each WC)</text>`;
    const axisY = `<text x="20" y="${padT + innerH / 2}"
      font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle"
      transform="rotate(-90, 20, ${padT + innerH / 2})">WC stage reached</text>`;

    // Least-squares regression over visible points.
    const n = xs.length;
    const meanX = xs.reduce((a, b) => a + b, 0) / n;
    const meanY = ys.reduce((a, b) => a + b, 0) / n;
    let num = 0, den = 0;
    for (let i = 0; i < n; i++) {
      num += (xs[i] - meanX) * (ys[i] - meanY);
      den += (xs[i] - meanX) ** 2;
    }
    const slope = den > 0 ? num / den : 0;
    const intercept = meanY - slope * meanX;
    const lineYat = (x) => slope * x + intercept;
    const lineX1 = xmin + 1, lineX2 = xmax - 1;
    const lineY1 = Math.max(ymin, Math.min(ymax, lineYat(lineX1)));
    const lineY2 = Math.max(ymin, Math.min(ymax, lineYat(lineX2)));
    const trend = `
      <line x1="${sxV(lineX1)}" y1="${syV(lineY1)}" x2="${sxV(lineX2)}" y2="${syV(lineY2)}"
            stroke="#d4a23a" stroke-width="1.5" stroke-dasharray="4,4" opacity="0.55"/>
      <text x="${sxV(lineX2) - 6}" y="${syV(lineY2) - 6}" font-size="10.5"
            fill="#d4a23a" opacity="0.85" text-anchor="end" font-style="italic">
        expected finish given FIFA Overall</text>`;

    // Over/under callouts: only when a single year is selected (else too noisy).
    let callouts = "";
    if (singleYear) {
      const annotated = rows
        .map((r) => ({ ...r, residual: r.stage_int - lineYat(r.overall) }))
        .sort((a, b) => Math.abs(b.residual) - Math.abs(a.residual))
        .slice(0, 6);
      callouts = annotated.map((r) => {
        const over = r.residual > 0;
        const cx = sx(r), cy = sy(r);
        const ax = cx + 14;
        const ay = over ? cy - 22 : cy + 28;
        const tag = over ? "+ overachieved" : "− underachieved";
        const color = over ? "#6dd58c" : "#e07c7c";
        return `
          <line x1="${cx}" y1="${cy}" x2="${ax}" y2="${ay}"
                stroke="${color}" stroke-width="1" opacity="0.55"/>
          <text x="${ax + 3}" y="${ay + 4}" font-size="10.5"
                fill="${color}" opacity="0.95" font-weight="600">${tag}</text>`;
      }).join("");
    }

    // Year legend
    const yearLegend = [...activeYears].sort().map((y) =>
      `<span><span class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${YEAR_COLOR[y]};vertical-align:0px;margin-right:4px"></span>WC ${String(y).slice(2)}</span>`,
    ).join("");

    mount.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
           class="fifa-scatter-svg" role="img"
           aria-label="FIFA Overall vs WC finish scatter">
        ${yRules}
        ${xTickSvg}
        ${trend}
        ${dots}
        ${labels}
        ${callouts}
        ${axisX}
        ${axisY}
      </svg>
      <div class="scatter-legend small muted">
        ${yearLegend}
        <span><span class="dot" style="background:transparent;border:1.5px solid #d4a23a;border-radius:50%;display:inline-block;width:9px;height:9px;"></span> semifinalist+ (gold ring)</span>
        <span class="muted">Dashed gold line = least-squares fit over visible years. Above = overachieved; below = underachieved. ${singleYear ? "" : "Y-jitter applied so same (overall, stage) dots don't overlap across years."}</span>
      </div>`;
  }

  draw();
}

/* ---------------- historical table ---------------- */

function renderHistorical(doc) {
  const tbody = document.getElementById("historical-fifa-rows");
  if (!tbody || !doc?.rows) return;
  tbody.innerHTML = doc.rows.map((r) => {
    const finalCell = r.top_ranked_made_final ? "Yes" : "No";
    const top5Cell = r.winner_in_top_5
      ? `<span class="chip" style="background:#d4a23a22;border:1px solid #d4a23a">Yes</span>`
      : `<span class="chip">No</span>`;
    return `<tr>
      <td class="num tabular"><strong>${r.year}</strong></td>
      <td>${escapeHTML(r.host)}</td>
      <td class="small muted">${escapeHTML(r.fifa_video_game_edition || "—")}</td>
      <td>${escapeHTML(r.pre_tournament_top_ranked)}</td>
      <td><strong>${escapeHTML(r.winner)}</strong></td>
      <td>${finalCell}</td>
      <td>${top5Cell}</td>
    </tr>`;
  }).join("");
}

/* ---------------- shared spearman + label-placement ---------------- */

function spearman(xs, ys) {
  const rank = (arr) => {
    const idx = arr.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]);
    const r = new Array(arr.length);
    let i = 0;
    while (i < idx.length) {
      let j = i;
      while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k++) r[idx[k][1]] = avg;
      i = j + 1;
    }
    return r;
  };
  const rx = rank(xs), ry = rank(ys);
  const n = xs.length;
  const mx = rx.reduce((a, b) => a + b, 0) / n;
  const my = ry.reduce((a, b) => a + b, 0) / n;
  let num = 0, dx2 = 0, dy2 = 0;
  for (let i = 0; i < n; i++) {
    num += (rx[i] - mx) * (ry[i] - my);
    dx2 += (rx[i] - mx) ** 2;
    dy2 += (ry[i] - my) ** 2;
  }
  return num / Math.sqrt(dx2 * dy2);
}

function placeLabels(rows, sx, sy, sortKey, padding, keyFn) {
  const keyOf = keyFn || ((r) => r.team_name);
  const labelW = 64, labelH = 14;
  const lineSpacing = labelH + 2;
  const intersects = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);
  const order = [...rows].sort((a, b) => sortKey(b) - sortKey(a));
  const placed = [];
  const picks = new Map();
  for (const r of order) {
    const cx = sx(r), cy = sy(r);
    const stackDown = cy > padding.top + padding.innerH * 0.7;
    const anchor = cx > padding.left + padding.innerW * 0.65 ? "end" : "start";
    const dx = anchor === "start" ? 9 : -9;
    let dy = stackDown ? -10 : 10;
    const step = stackDown ? -lineSpacing : lineSpacing;
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
    picks.set(keyOf(r), { anchor, dx, dy });
  }
  return picks;
}

/* Dot fill = WC22 stage_int ramp (2..8). Light gray to deep teal. */
function stageFill(stageInt) {
  const t = Math.max(0, Math.min(1, (stageInt - 2) / 6));
  const lo = [200, 205, 212], hi = [30, 90, 160];
  const r = Math.round(lo[0] + (hi[0] - lo[0]) * t);
  const g = Math.round(lo[1] + (hi[1] - lo[1]) * t);
  const b = Math.round(lo[2] + (hi[2] - lo[2]) * t);
  return `rgb(${r},${g},${b})`;
}

/* ---------------- scatter 1: FIFA Overall vs TCD ---------------- */

function renderFifaVsTcd(rows) {
  const mount = document.getElementById("fifa-vs-tcd-scatter");
  if (!mount) return;

  const W = 1100, H = 500;
  const padL = 86, padR = 48, padT = 22, padB = 72;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const xs = rows.map((r) => r.overall);
  const ys = rows.map((r) => r.tcd);
  const xmin = Math.min(...xs) - 2, xmax = Math.max(...xs) + 2;
  const ymin = Math.min(...ys) - 6, ymax = Math.max(...ys) + 6;
  const sxV = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const syV = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;
  const sx = (r) => sxV(r.overall);
  const sy = (r) => syV(r.tcd);

  const rho = spearman(xs, ys);
  document.getElementById("rho-fifa-tcd").innerHTML =
    `(Spearman &rho; = ${rho >= 0 ? "+" : ""}${rho.toFixed(3)}, n = ${rows.length})`;

  const xTicks = [70, 74, 78, 82, 86];
  const yTicks = [0, 25, 50, 75, 100, 125, 150];
  const xTickSvg = xTicks.filter((v) => v >= xmin && v <= xmax).map((x) => `
    <text x="${sxV(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="middle">${x}</text>`).join("");
  const yRules = yTicks.filter((v) => v >= ymin && v <= ymax).map((y) => `
    <line x1="${padL}" y1="${syV(y)}" x2="${W - padR}" y2="${syV(y)}"
          stroke="currentColor" stroke-width="0.5" opacity="0.10"/>
    <text x="${padL - 8}" y="${syV(y) + 4}" font-size="11" fill="currentColor"
          opacity="0.6" text-anchor="end">${y}</text>`).join("");

  const dots = rows.map((r) => {
    const cx = sx(r), cy = sy(r);
    const ring = SEMIS.has(r.team_name)
      ? `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="9" fill="none" stroke="#d4a23a" stroke-width="2"/>`
      : "";
    return `${ring}<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5.5"
             fill="${stageFill(r.stage_int)}" stroke="var(--bg, #0b1220)" stroke-width="1.2"/>`;
  }).join("");

  const picks = placeLabels(rows, sx, sy,
    (r) => r.stage_int * 1000 + r.tcd,
    { left: padL, top: padT, innerW, innerH });
  const labels = rows.map((r) => {
    const cx = sx(r), cy = sy(r);
    const p = picks.get(r.team_name);
    const fw = SEMIS.has(r.team_name) ? 700 : 500;
    return `<text x="${(cx + p.dx).toFixed(1)}" y="${(cy + p.dy).toFixed(1)}"
           font-size="11.5" font-weight="${fw}" fill="currentColor"
           opacity="0.92" text-anchor="${p.anchor}">${escapeHTML(r.team_name)}</text>`;
  }).join("");

  const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - padB + 38}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
    FIFA-23 Overall</text>`;
  const axisY = `<text x="20" y="${padT + innerH / 2}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle"
    transform="rotate(-90, 20, ${padT + innerH / 2})">Team Chemistry Density</text>`;

  mount.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         class="fifa-scatter-svg" role="img"
         aria-label="FIFA-23 Overall vs Team Chemistry Density scatter">
      ${yRules}
      ${xTickSvg}
      ${dots}
      ${labels}
      ${axisX}
      ${axisY}
      ${stageRamp(W, H, padR)}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#d4a23a; border-radius:50%;"></span> WC22 semifinalist (gold ring)</span>
      <span class="muted">Dot fill = WC22 finish (light = group exit, dark = winner).</span>
    </div>`;
}

/* ---------------- scatter 2: FIFA Overall vs History Index ---------------- */

function renderFifaVsHi(rows) {
  const mount = document.getElementById("fifa-vs-hi-scatter");
  if (!mount) return;

  const W = 1100, H = 480;
  const padL = 86, padR = 48, padT = 22, padB = 64;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const xs = rows.map((r) => r.overall);
  const ys = rows.map((r) => r.history_index_count);
  const xmin = Math.min(...xs) - 2, xmax = Math.max(...xs) + 2;
  const ymin = Math.min(...ys) - 2, ymax = Math.max(...ys) + 2;
  const sxV = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const syV = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;
  const sx = (r) => sxV(r.overall);
  const sy = (r) => syV(r.history_index_count);

  const rho = spearman(xs, ys);
  document.getElementById("rho-fifa-hi").innerHTML =
    `(Spearman &rho; = ${rho >= 0 ? "+" : ""}${rho.toFixed(3)}, n = ${rows.length})`;

  const xTicks = [70, 74, 78, 82, 86];
  const yTicks = [0, 5, 10, 15, 20];
  const xTickSvg = xTicks.filter((v) => v >= xmin && v <= xmax).map((x) => `
    <text x="${sxV(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="middle">${x}</text>`).join("");
  const yRules = yTicks.filter((v) => v >= ymin && v <= ymax).map((y) => `
    <line x1="${padL}" y1="${syV(y)}" x2="${W - padR}" y2="${syV(y)}"
          stroke="currentColor" stroke-width="0.5" opacity="0.10"/>
    <text x="${padL - 8}" y="${syV(y) + 4}" font-size="11" fill="currentColor"
          opacity="0.6" text-anchor="end">${y}</text>`).join("");

  const dots = rows.map((r) => {
    const cx = sx(r), cy = sy(r);
    const ring = SEMIS.has(r.team_name)
      ? `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="9" fill="none" stroke="#d4a23a" stroke-width="2"/>`
      : "";
    return `${ring}<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5.5"
             fill="${stageFill(r.stage_int)}" stroke="var(--bg, #0b1220)" stroke-width="1.2"/>`;
  }).join("");

  const picks = placeLabels(rows, sx, sy,
    (r) => r.stage_int * 1000 + r.history_index_count,
    { left: padL, top: padT, innerW, innerH });
  const labels = rows.map((r) => {
    const cx = sx(r), cy = sy(r);
    const p = picks.get(r.team_name);
    const fw = SEMIS.has(r.team_name) ? 700 : 500;
    return `<text x="${(cx + p.dx).toFixed(1)}" y="${(cy + p.dy).toFixed(1)}"
           font-size="11.5" font-weight="${fw}" fill="currentColor"
           opacity="0.92" text-anchor="${p.anchor}">${escapeHTML(r.team_name)}</text>`;
  }).join("");

  const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - padB + 38}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
    FIFA-23 Overall</text>`;
  const axisY = `<text x="20" y="${padT + innerH / 2}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle"
    transform="rotate(-90, 20, ${padT + innerH / 2})">History Index (squad players with a national-squad club-mate)</text>`;

  mount.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         class="fifa-scatter-svg" role="img"
         aria-label="FIFA-23 Overall vs History Index scatter">
      ${yRules}
      ${xTickSvg}
      ${dots}
      ${labels}
      ${axisX}
      ${axisY}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#d4a23a; border-radius:50%;"></span> WC22 semifinalist (gold ring)</span>
      <span class="muted">Dot fill = WC22 finish (light = group exit, dark = winner).</span>
    </div>`;
}

function stageRamp(W, H, padR) {
  const rampW = 200;
  const rampX = W - padR - rampW;
  const rampY = H - 14;
  const stops = [2, 3.5, 5, 6.5, 8];
  return `
    <g transform="translate(${rampX}, ${rampY})">
      <text x="${rampW}" y="-18" font-size="10.5" fill="currentColor" opacity="0.75" text-anchor="end">
        dot fill = WC22 finish</text>
      ${stops.map((v, i) =>
        `<rect x="${i * (rampW / stops.length)}" y="-10" width="${rampW / stops.length}" height="9" fill="${stageFill(v)}"/>`,
      ).join("")}
      <text x="0" y="6" font-size="10" fill="currentColor" opacity="0.6">Group</text>
      <text x="${rampW}" y="6" font-size="10" fill="currentColor" opacity="0.6" text-anchor="end">Winner</text>
    </g>`;
}

/* ---------------- WC26 candidate table ---------------- */

function renderWc26(doc) {
  const mount = document.getElementById("wc26-table");
  if (!mount || !doc?.teams) return;
  const sorted = [...doc.teams].sort((a, b) => (b.overall ?? 0) - (a.overall ?? 0)).slice(0, 12);
  const rows = sorted.map((t) => {
    const ovr = t.overall != null ? t.overall : "—";
    const licensed = t.ea_licensed ? "" : '<span class="muted" title="EA FC 26 did not license this nation; Overall is an analyst proxy from individual player Overalls.">*</span>';
    const stars = (t.stars || []).slice(0, 3).map((s) =>
      `<span class="chip">${escapeHTML(s.name)} <span class="muted">${s.overall}</span></span>`,
    ).join(" ");
    return `<tr>
      <td><span class="team-cell">${flagHTML(t.flag)} ${escapeHTML(t.team)}</span></td>
      <td class="num tabular"><strong>${ovr}</strong>${licensed}</td>
      <td class="num tabular">${t.att ?? "—"}</td>
      <td class="num tabular">${t.mid ?? "—"}</td>
      <td class="num tabular">${t.def ?? "—"}</td>
      <td class="small">${stars || `<span class="muted">—</span>`}</td>
    </tr>`;
  }).join("");
  mount.innerHTML = `
    <table class="data-table fifa-data-table">
      <thead><tr>
        <th>Team</th>
        <th class="num">EA FC 26 Overall</th>
        <th class="num">Att</th>
        <th class="num">Mid</th>
        <th class="num">Def</th>
        <th>Top stars</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="small muted" style="margin-top:0.6rem;">
      * = EA FC 26 did not license this nation; Overall is an analyst proxy from
      individual player Overalls aggregated 4-3-3.
    </p>`;
}
