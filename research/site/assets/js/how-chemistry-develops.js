import { loadJSON, escapeHTML } from "./site.js";

// History Index vs Team Chemistry Density scatter for Tab 3.
// Data path: research/site/data/team_chemistry_vs_paper.json
//   (the same per-team rows used by the leaderboard / fifa-mode pages)
const scatterEl = document.getElementById("history-vs-chem-scatter");

const chem = await loadJSON("data/team_chemistry_vs_paper.json");
if (!chem || !scatterEl) {
  if (scatterEl) {
    scatterEl.innerHTML = `<div class="empty-state"><strong>Team chemistry data missing.</strong></div>`;
  }
} else {
  const rows = chem.filter((r) => r.n_strong_total != null && r.history_index_count != null);
  renderHistoryVsChemScatter(rows);
}

function renderHistoryVsChemScatter(rows) {
  const W = 1100, H = 480;
  const padL = 80, padR = 24, padT = 22, padB = 56;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const xs = rows.map((r) => r.history_index_count ?? 0);
  const ys = rows.map((r) => r.n_strong_total);
  const xmin = 0;
  const xmax = Math.max(...xs) * 1.1 + 1;
  const ymin = Math.min(...ys) - 4;
  const ymax = Math.max(...ys) + 4;
  const sx = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const sy = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;

  // Linear fit for visual trend
  const n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    num += (xs[i] - mx) * (ys[i] - my);
    den += (xs[i] - mx) ** 2;
  }
  const slope = den ? num / den : 0;
  const intercept = my - slope * mx;
  const fitLine = `<line x1="${sx(xmin)}" y1="${sy(slope * xmin + intercept)}"
    x2="${sx(xmax)}" y2="${sy(slope * xmax + intercept)}"
    stroke="currentColor" stroke-width="1.0" opacity="0.35" stroke-dasharray="4 4"/>`;

  const semis = new Set(["France", "Croatia", "Argentina", "Morocco"]);
  const dotColor = (r) => (semis.has(r.team_name) ? "#d4a23a" : "#6b7280");

  const dots = rows.map((r) => {
    const cx = sx(r.history_index_count ?? 0);
    const cy = sy(r.n_strong_total);
    return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5"
       fill="${dotColor(r)}" stroke="var(--bg, #0b1220)" stroke-width="1.0"/>`;
  }).join("");

  // Deterministic non-overlap label placement
  const labelW = 64, labelH = 14;
  const lineSpacing = labelH + 2;
  const intersects = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);
  const order = [...rows].sort(
    (a, b) => b.n_strong_total - a.n_strong_total
      || (b.history_index_count ?? 0) - (a.history_index_count ?? 0),
  );
  const placed = [];
  const picks = new Map();
  for (const r of order) {
    const cx = sx(r.history_index_count ?? 0);
    const cy = sy(r.n_strong_total);
    const stackDown = r.n_strong_total < 50;
    const anchor = cx > padL + innerW * 0.65 ? "end" : "start";
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

  const labels = rows.map((r) => {
    const cx = sx(r.history_index_count ?? 0);
    const cy = sy(r.n_strong_total);
    const pick = picks.get(r.team_name);
    const fw = semis.has(r.team_name) ? 700 : 500;
    return `<text x="${(cx + pick.dx).toFixed(1)}" y="${(cy + pick.dy).toFixed(1)}"
           font-size="11" font-weight="${fw}" fill="currentColor"
           opacity="0.92" text-anchor="${pick.anchor}">${escapeHTML(r.team_name)}</text>`;
  }).join("");

  const xTicks = [0, 4, 8, 12, 16, 20];
  const xTickSvg = xTicks.filter((x) => x <= xmax).map((x) => `
    <text x="${sx(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="middle">${x}</text>
  `).join("");
  const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - 6}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
    History Index — squad players with a club-mate inside the national squad</text>`;
  const axisY = `<text x="${20}" y="${padT + innerH / 2}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle"
    transform="rotate(-90, 20, ${padT + innerH / 2})">Team Chemistry Density (strong AW-JOI pairs)</text>`;

  scatterEl.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         class="fifa-scatter-svg" role="img"
         aria-label="History Index vs team chemistry density scatter">
      ${fitLine}
      ${xTickSvg}
      ${dots}
      ${labels}
      ${axisX}
      ${axisY}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#d4a23a"></span> WC22 semifinalists</span>
      <span class="muted">Spearman &rho; = <strong>+0.348</strong> (p &asymp; 0.055, n = 31). Directional, not deterministic.</span>
    </div>`;
}
