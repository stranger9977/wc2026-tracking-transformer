import { loadJSON, escapeHTML, fmtNum, fmtInt, renderEmpty, flagHTML, posChip, makeSortableTable } from "./site.js";

const aucEl = document.getElementById("auc-table");
const attGrid = document.getElementById("attention-grid");
const searchEl = document.getElementById("att-search");
const pairsEl = document.getElementById("attention-pairs-table");
const sparkEl = document.getElementById("attention-pairs-spark");

function renderAuc(metrics, baseline) {
  if (!metrics) {
    // empty-state already in HTML; leave it.
    return;
  }
  const b = metrics.baseline;
  const a = metrics.augmented;
  const lift = metrics.relative_lift_pct || {};
  const row = (label, base, aug, key) => `
    <tr>
      <td><strong>${escapeHTML(label)}</strong></td>
      <td class="num">${fmtNum(base.auc, 3)}</td>
      <td class="num">${fmtNum(aug.auc, 3)}</td>
      <td class="num"><span class="chip ${lift[key] >= 0 ? "green" : "red"}">${(lift[key] >= 0 ? "+" : "") + fmtNum(lift[key], 2)}% AUC</span></td>
      <td class="num">${fmtNum(base.brier, 4)} → ${fmtNum(aug.brier, 4)}</td>
      <td class="num">${fmtNum(base.logloss, 4)} → ${fmtNum(aug.logloss, 4)}</td>
    </tr>`;
  const refLine = baseline
    ? `<p class="small dim mt-0">Site-wide event-only reference (from Overview): score AUC <strong>${fmtNum(baseline.score_auc, 3)}</strong>, concede AUC <strong>${fmtNum(baseline.concede_auc, 3)}</strong>.</p>`
    : "";
  aucEl.innerHTML = `
    <h3 class="mt-0">Cross-validated metrics (action level, 5-fold by-game)</h3>
    ${refLine}
    <p class="small dim">Baseline columns: event-only features (action types + locations + 3-action context). Augmented columns add ${escapeHTML(String(metrics.transformer_cols?.length || 0))} transformer features per action.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>
          <th>Target (next 10 actions)</th>
          <th class="num">Baseline AUC</th>
          <th class="num">Augmented AUC</th>
          <th class="num">Lift</th>
          <th class="num">Brier (base → aug)</th>
          <th class="num">Log-loss (base → aug)</th>
        </tr></thead>
        <tbody>
          ${row("P-score", b.score, a.score, "score")}
          ${row("P-concede", b.concede, a.concede, "concede")}
        </tbody>
      </table>
    </div>
    <p class="small muted">
      Transformer columns appended: ${(metrics.transformer_cols || []).map((c) => `<code>${escapeHTML(c)}</code>`).join(", ") || "—"}.
    </p>`;
}

function renderAttentionGrid(index, search) {
  if (!index || !Array.isArray(index) || index.length === 0) {
    renderEmpty(attGrid, "Attention figures not rendered yet.",
      "Run research/scripts/render_attention_figures.py to populate data/attention_figures_index.json.");
    return;
  }
  const q = (search || "").toLowerCase().trim();
  const pool = index.filter((t) => !q || (t.team_name || "").toLowerCase().includes(q));
  if (pool.length === 0) {
    renderEmpty(attGrid, "No teams match that search.", "Try a partial name, e.g. \"arg\" for Argentina.");
    return;
  }
  attGrid.innerHTML = pool.map((t) => {
    const path = (t.path || "").replace(/^.*\/site\//, "");
    return `<article class="team-card flag-bg-wrap">
        ${t.flag_code ? `<div class="flag-bg" style="background-image:url(https://flagcdn.com/640x480/${escapeHTML(t.flag_code)}.png)"></div>` : ""}
        <h3>${flagHTML(t.flag_code, { size: "lg", alt: t.team_name })}${escapeHTML(t.team_name)}</h3>
        <div class="meta">${fmtInt(t.n_pairs || 0)} attention pairs rendered</div>
        <a href="${escapeHTML(path)}" download>
          <img src="${escapeHTML(path)}" alt="Attention chemistry network for ${escapeHTML(t.team_name)}" loading="lazy" style="width:100%; border-radius:6px;">
        </a>
      </article>`;
  }).join("");
}

/**
 * Tufte-style histogram in inline SVG: thin strokes, no chartjunk, one annotation.
 * `values` is the per-pair attention_per90 array; `top` is the leading pair (object).
 */
function renderSparkline(values, top) {
  if (!values || values.length === 0) {
    renderEmpty(sparkEl,
      "Distribution will render once attention pairs are available.",
      "Run research/scripts/export_attention_pairs.py to populate data/attention_pairs.json.");
    return;
  }
  const W = 320;
  const H = 110;
  const PAD_L = 4;
  const PAD_R = 4;
  const PAD_T = 8;
  const PAD_B = 22;
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;

  const vals = values.filter((v) => Number.isFinite(v)).slice().sort((a, b) => a - b);
  const lo = vals[0];
  const hi = vals[vals.length - 1];
  const range = hi - lo || 1;

  // Freedman-Diaconis-ish: ~24 bins, clipped.
  const nBins = Math.max(12, Math.min(28, Math.ceil(Math.sqrt(vals.length) * 1.4)));
  const binW = range / nBins;
  const counts = new Array(nBins).fill(0);
  for (const v of vals) {
    let idx = Math.floor((v - lo) / binW);
    if (idx >= nBins) idx = nBins - 1;
    counts[idx] += 1;
  }
  const maxC = Math.max(...counts);
  const barW = innerW / nBins;

  const bars = counts.map((c, i) => {
    const h = (c / maxC) * innerH;
    const x = PAD_L + i * barW;
    const y = PAD_T + (innerH - h);
    return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${(barW - 0.6).toFixed(2)}" height="${h.toFixed(2)}" fill="currentColor" opacity="0.55"></rect>`;
  }).join("");

  const topVal = top && Number.isFinite(top.attention_per90) ? top.attention_per90 : hi;
  const topX = PAD_L + ((topVal - lo) / range) * innerW;
  const topLabel = top
    ? `${top.name_p || "?"} + ${top.name_q || "?"} · ${fmtNum(topVal, 3)}/90`
    : `top: ${fmtNum(topVal, 3)}/90`;

  // Decide label anchor so it doesn't overflow.
  const anchor = topX > W * 0.65 ? "end" : (topX < W * 0.2 ? "start" : "middle");
  const labelX = topX;

  sparkEl.innerHTML = `
    <div class="spark-title">Attention / 90 across ${fmtInt(values.length)} pairs</div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img"
         aria-label="Histogram of attention per 90 across all pairs, with leading pair annotated"
         class="spark-svg">
      ${bars}
      <line x1="${PAD_L}" y1="${PAD_T + innerH + 0.5}" x2="${W - PAD_R}" y2="${PAD_T + innerH + 0.5}"
            stroke="currentColor" stroke-width="0.5" opacity="0.6"></line>
      <line x1="${topX.toFixed(2)}" y1="${PAD_T - 2}" x2="${topX.toFixed(2)}" y2="${PAD_T + innerH}"
            stroke="currentColor" stroke-width="1" opacity="0.95"></line>
      <text x="${labelX.toFixed(2)}" y="${(PAD_T + innerH + 14).toFixed(2)}"
            text-anchor="${anchor}" font-size="10" fill="currentColor" opacity="0.9">
        ${escapeHTML(topLabel)}
      </text>
      <text x="${PAD_L}" y="${H - 4}" text-anchor="start" font-size="9" fill="currentColor" opacity="0.55">${fmtNum(lo, 2)}</text>
      <text x="${W - PAD_R}" y="${H - 4}" text-anchor="end" font-size="9" fill="currentColor" opacity="0.55">${fmtNum(hi, 2)}</text>
    </svg>
    <div class="spark-caption">Each bar = a pair count. The vertical mark is the leading pair in the table.</div>
  `;
}

function renderPairs(rows) {
  if (!rows || rows.length === 0) {
    renderEmpty(pairsEl, "Attention pair data not exported yet.",
      "Run research/scripts/export_attention_pairs.py to populate data/attention_pairs.json.");
    renderSparkline(null);
    return;
  }
  const cols = [
    { key: "team_name", label: "Team", render: (r) => `${flagHTML(r.flag_code)}${escapeHTML(r.team_name || "")}` },
    { key: "name_p", label: "Pair", render: (r) =>
        `<strong>${escapeHTML(r.name_p)}</strong>${posChip(r.pos_p)} <span class="muted">+</span> <strong>${escapeHTML(r.name_q)}</strong>${posChip(r.pos_q)}` },
    { key: "minutes_together", label: "Min", num: true, digits: 0 },
    { key: "attention_total", label: "Attn total", num: true, digits: 3 },
    { key: "attention_per90", label: "Attn / 90", num: true, digits: 3,
      defaultSort: true, defaultDir: "desc" },
  ];
  makeSortableTable({ data: rows, columns: cols, container: pairsEl,
    emptyLabel: "No attention pairs." });

  // Top pair = max attention_per90.
  const top = rows.reduce((acc, r) =>
    (acc == null || (r.attention_per90 ?? -Infinity) > (acc.attention_per90 ?? -Infinity)) ? r : acc, null);
  const values = rows.map((r) => r.attention_per90).filter((v) => Number.isFinite(v));
  renderSparkline(values, top);
}

const overview = await loadJSON("data/overview.json").catch(() => null);
const metrics = await loadJSON("data/vaep_metrics_transformer.json").catch(() => null);
renderAuc(metrics, overview?.vaep_metrics);

const idx = await loadJSON("data/attention_figures_index.json").catch(() => []);
renderAttentionGrid(idx, "");
if (searchEl) searchEl.addEventListener("input", () => renderAttentionGrid(idx, searchEl.value));

const pairs = await loadJSON("data/attention_pairs.json").catch(() => []);
renderPairs(pairs);
