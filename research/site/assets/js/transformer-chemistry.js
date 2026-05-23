import { loadJSON, escapeHTML, fmtNum, fmtInt, renderEmpty, flagHTML, posChip, makeSortableTable } from "./site.js";

const aucEl = document.getElementById("auc-table");
const attGrid = document.getElementById("attention-grid");
const searchEl = document.getElementById("att-search");
const pairsEl = document.getElementById("attention-pairs-table");

function pct(x) { return Number.isFinite(x) ? (x.toFixed(2) + "%") : "—"; }

function renderAuc(metrics) {
  if (!metrics) {
    aucEl.innerHTML = `<div class="empty-state">VAEP retraining hasn't run yet.</div>`;
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
      <td class="num"><span class="chip ${lift[key] >= 0 ? "green" : "red"}">${(lift[key] >= 0 ? "+" : "") + fmtNum(lift[key], 2)}%</span></td>
      <td class="num">${fmtNum(base.brier, 4)} → ${fmtNum(aug.brier, 4)}</td>
      <td class="num">${fmtNum(base.logloss, 4)} → ${fmtNum(aug.logloss, 4)}</td>
    </tr>`;
  aucEl.innerHTML = `
    <h3 class="mt-0">Cross-validated metrics</h3>
    <p class="small dim">5-fold by-game splits. Baseline = event-only features (action types + locations + 3-action context). Augmented = baseline + ${escapeHTML(String(metrics.transformer_cols?.length || 0))} transformer features.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>
          <th>Metric</th><th class="num">Baseline AUC</th><th class="num">Augmented AUC</th>
          <th class="num">Lift</th><th class="num">Brier</th><th class="num">Log-loss</th>
        </tr></thead>
        <tbody>
          ${row("P-score (next 10 actions)", b.score, a.score, "score")}
          ${row("P-concede (next 10 actions)", b.concede, a.concede, "concede")}
        </tbody>
      </table>
    </div>
    <p class="small muted">
      Transformer cols: ${(metrics.transformer_cols || []).map((c) => `<code>${escapeHTML(c)}</code>`).join(", ") || "—"}.
    </p>`;
}

function renderAttentionGrid(index, search) {
  if (!index || !Array.isArray(index) || index.length === 0) {
    attGrid.innerHTML = `<div class="empty-state">Attention figures not yet rendered.</div>`;
    return;
  }
  const q = (search || "").toLowerCase().trim();
  const pool = index.filter((t) => !q || (t.team_name || "").toLowerCase().includes(q));
  if (pool.length === 0) {
    attGrid.innerHTML = `<div class="empty-state">No teams match.</div>`;
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

function renderPairs(rows) {
  if (!rows || rows.length === 0) {
    pairsEl.innerHTML = `<div class="empty-state">Attention pair data pending.</div>`;
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
}

const metrics = await loadJSON("data/vaep_metrics_transformer.json").catch(() => null);
renderAuc(metrics);

const idx = await loadJSON("data/attention_figures_index.json").catch(() => []);
renderAttentionGrid(idx, "");
if (searchEl) searchEl.addEventListener("input", () => renderAttentionGrid(idx, searchEl.value));

const pairs = await loadJSON("data/attention_pairs.json").catch(() => []);
renderPairs(pairs);
