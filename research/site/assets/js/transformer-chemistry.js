import { loadJSON, escapeHTML, fmtNum, fmtInt, renderEmpty, flagHTML, posChip, makeSortableTable } from "./site.js";

const aucEl = document.getElementById("auc-table");
const attGrid = document.getElementById("attention-grid");
const teamSearchEl = document.getElementById("att-search");
const tableEl = document.getElementById("attention-pairs-table");
const sparkEl = document.getElementById("attention-pairs-spark");
const attnTabs = document.querySelectorAll(".attn-tabs button");
const attnSearchEl = document.getElementById("attn-search");
const attnMinMinEl = document.getElementById("attn-min-min");
const attnShowGksEl = document.getElementById("attn-show-gks");
const sizeSelect = document.getElementById("attn-group-size");

// Three colours, matched to the team-map edge palette.
const CAT_COLOR = { off: "#d4793a", def: "#3b6ea0", cross: "#7a4f9a", mixed: "#888" };
const CAT_LABEL = { off: "Off ↔ Off", def: "Def ↔ Def", cross: "Cross", mixed: "Mixed" };

let pairsRaw = [];
let groupsRaw = [];
let state = { category: "all", search: "", minMin: 60, size: 2, showGks: false };

function rowHasGk(r) {
  if (!r) return false;
  if (r.role_p === "GK" || r.role_q === "GK") return true;
  if (r.pos_p === "GK" || r.pos_q === "GK") return true;
  if (Array.isArray(r.members)) return r.members.some((m) => m.role === "GK" || m.position === "GK");
  return false;
}

// ───────────────── AUC table ─────────────────
function renderAuc(metrics, baseline) {
  if (!metrics) return;
  const m = metrics.metrics || {};
  const evScore = baseline?.score_auc ?? 0.681;
  const evConc  = baseline?.concede_auc ?? 0.671;
  const fmtBrier = (v) => Number.isFinite(v) ? fmtNum(v, 4) : "—";
  aucEl.innerHTML = `
    <h3 class="mt-0">Frame-level transformer metrics (held-out validation set)</h3>
    <p class="small dim mt-0">
      Trained on <strong>${fmtInt(metrics.n_train_matches)}</strong> matches
      (${fmtInt(metrics.n_train_frames)} frames); validated on
      <strong>${fmtInt(metrics.n_val_matches)}</strong> held-out matches
      (${fmtInt(metrics.n_val_frames)} frames). Each frame predicts the next
      <strong>${metrics.look_ahead_s} s</strong> at ${metrics.frame_rate_hz} Hz.
    </p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>
          <th>Head</th>
          <th class="num">Event baseline AUC<br><span class="small muted">(JOI/JDI gate)</span></th>
          <th class="num">Frame-level AUC<br><span class="small muted">(per 5 Hz frame)</span></th>
          <th class="num">Brier</th>
          <th class="num">Loss</th>
        </tr></thead>
        <tbody>
          <tr><td><strong>P(score in next 10 s)</strong></td>
              <td class="num">${fmtNum(evScore, 3)}</td>
              <td class="num"><span class="chip green tabular">${fmtNum(m.val_auc_score, 3)}</span></td>
              <td class="num">${fmtBrier(m.val_brier_score)}</td>
              <td class="num">${fmtBrier(m.val_loss_score)}</td></tr>
          <tr><td><strong>P(concede in next 10 s)</strong></td>
              <td class="num">${fmtNum(evConc, 3)}</td>
              <td class="num"><span class="chip red tabular">${fmtNum(m.val_auc_concede, 3)}</span></td>
              <td class="num">${fmtBrier(m.val_brier_concede)}</td>
              <td class="num">${fmtBrier(m.val_loss_concede)}</td></tr>
        </tbody>
      </table>
    </div>
    <p class="small muted mt-1">
      The two AUC columns are <em>not</em> directly comparable — the event-level
      number ranks SPADL actions; the frame-level number ranks tracking frames
      at 5 Hz (300× more rows, mostly off-ball). Both reach the same neighbourhood
      of skill (≈0.7-0.8): a frame-level extension of the same framework is
      feasible and lets us emit a probability every 0.2 s instead of every action.
    </p>`;
}

// ───────────────── Per-team attention figure grid ─────────────────
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

// ───────────────── Leaderboard ─────────────────
function categoryChip(cat) {
  const color = CAT_COLOR[cat] || "#888";
  return `<span class="cat-chip" style="background:${color}1A;color:${color};border-color:${color}50">${escapeHTML(CAT_LABEL[cat] || cat)}</span>`;
}

function fmtGoalsAssists(g, a) {
  if (!g && !a) return `<span class="muted tabular">0 / 0</span>`;
  return `<span class="tabular">${g} <span class="muted">/</span> ${a}</span>`;
}

function fmtMembers(members) {
  return members.map(m => `<strong>${escapeHTML(m.name)}</strong>${posChip(m.position)}`).join(" <span class='muted'>·</span> ");
}

function applyPairFilters(rows) {
  return rows.filter((r) => {
    if (state.category !== "all" && r.category !== state.category) return false;
    if ((r.minutes_together ?? 0) < state.minMin) return false;
    if (!state.showGks && rowHasGk(r)) return false;
    const q = state.search.trim().toLowerCase();
    if (q) {
      const hay = `${r.name_p || ""} ${r.name_q || ""} ${r.team_name || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function applyGroupFilters(rows) {
  return rows.filter((r) => {
    if (r.size !== state.size) return false;
    if (state.category !== "all" && r.category !== state.category) return false;
    if (!state.showGks && rowHasGk(r)) return false;
    const q = state.search.trim().toLowerCase();
    if (q) {
      const hay = `${r.team_name || ""} ${r.members.map(m => m.name).join(" ")}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function renderTable() {
  // Always re-read the current select value — this avoids a desync where the
  // change event missed (autofill, keyboard nav, browser caching) and JS state
  // disagrees with what the DOM shows.
  if (sizeSelect) {
    const fromDom = Number(sizeSelect.value);
    if (Number.isFinite(fromDom) && fromDom > 0) state.size = fromDom;
  }
  document.getElementById("attn-min-min-row")?.classList.toggle("hidden", state.size !== 2);

  if (state.size === 2) {
    const rows = applyPairFilters(pairsRaw);
    renderPairsTable(rows);
    renderSparkline(rows);
  } else {
    const rows = applyGroupFilters(groupsRaw);
    renderGroupsTable(rows);
    renderSparkline(rows);
  }
}

function renderPairsTable(rows) {
  if (!rows.length) {
    renderEmpty(tableEl, "No pairs match these filters.",
      "Try widening the category, lowering minutes, or clearing the search.");
    return;
  }
  const cols = [
    { key: "team_name", label: "Team",
      render: (r) => `${flagHTML(r.flag_code)}${escapeHTML(r.team_name || "")}` },
    { key: "name_p", label: "Pair",
      render: (r) => `<strong>${escapeHTML(r.name_p)}</strong>${posChip(r.pos_p)} <span class="muted">+</span> <strong>${escapeHTML(r.name_q)}</strong>${posChip(r.pos_q)}` },
    { key: "category", label: "Edge type",
      render: (r) => categoryChip(r.category) },
    { key: "minutes_together", label: "Min", num: true, digits: 0 },
    { key: "goals_together", label: "Goals / Assists (together)",
      render: (r) => fmtGoalsAssists(r.goals_together || 0, r.assists_together || 0) },
    { key: "attention_per90", label: "Attn / 90", num: true, digits: 2 },
    { key: "attention_lift", label: "Lift × team baseline",
      num: true, digits: 2, defaultSort: true, defaultDir: "desc",
      render: (r) => `<span class="tabular"><strong>${fmtNum(r.attention_lift, 2)}×</strong></span>` },
  ];
  // makeSortableTable doesn't render until .render() is called.
  makeSortableTable({ data: rows, columns: cols, container: tableEl,
    emptyLabel: "No attention pairs." }).render();
}

function renderGroupsTable(rows) {
  if (!rows.length) {
    renderEmpty(tableEl, `No ${state.size}-player groups match these filters.`,
      "Try widening the category or clearing the search.");
    return;
  }
  const cols = [
    { key: "team_name", label: "Team",
      render: (r) => `${flagHTML(r.flag_code)}${escapeHTML(r.team_name || "")}` },
    { key: "members", label: `${state.size}-player unit`,
      render: (r) => fmtMembers(r.members) },
    { key: "category", label: "Type",
      render: (r) => categoryChip(r.category) },
    { key: "n_pairs_observed", label: "Pairs measured",
      num: true, digits: 0,
      render: (r) => `<span class="tabular">${r.n_pairs_observed} / ${(r.size * (r.size - 1)) / 2}</span>` },
    { key: "avg_pair_attention_per90", label: "Avg pair attn / 90", num: true, digits: 2 },
    { key: "attention_lift", label: "Lift × team baseline",
      num: true, digits: 2, defaultSort: true, defaultDir: "desc",
      render: (r) => `<span class="tabular"><strong>${fmtNum(r.attention_lift, 2)}×</strong></span>` },
  ];
  makeSortableTable({ data: rows, columns: cols, container: tableEl,
    emptyLabel: "No groups." }).render();
}

function renderSparkline(rows) {
  if (!sparkEl) return;
  if (!rows || rows.length < 2) {
    sparkEl.innerHTML = `<div class="empty-state small">Need ≥ 2 rows for a distribution.</div>`;
    return;
  }
  const W = 320, H = 90, PAD = 4;
  const innerW = W - PAD * 2;
  const innerH = H - 22;
  const key = state.size === 2 ? "attention_lift" : "attention_lift";
  const vals = rows.map(r => Number(r[key])).filter(Number.isFinite).slice().sort((a, b) => a - b);
  const lo = vals[0], hi = vals[vals.length - 1];
  const range = (hi - lo) || 1;
  const nBins = Math.max(10, Math.min(24, Math.ceil(Math.sqrt(vals.length))));
  const counts = new Array(nBins).fill(0);
  for (const v of vals) {
    let idx = Math.floor((v - lo) / range * nBins);
    if (idx >= nBins) idx = nBins - 1;
    counts[idx] += 1;
  }
  const maxC = Math.max(...counts);
  const barW = innerW / nBins;
  let bars = "";
  for (let i = 0; i < nBins; i++) {
    const h = (counts[i] / maxC) * innerH;
    const x = PAD + i * barW;
    bars += `<rect x="${x.toFixed(1)}" y="${(PAD + innerH - h).toFixed(1)}" width="${(barW - 0.5).toFixed(1)}" height="${h.toFixed(1)}" fill="currentColor" opacity="0.55"/>`;
  }
  const top = rows[0];
  const topX = PAD + ((Number(top[key]) - lo) / range) * innerW;
  bars += `<line x1="${topX.toFixed(1)}" y1="${PAD}" x2="${topX.toFixed(1)}" y2="${(PAD+innerH).toFixed(1)}" stroke="currentColor" stroke-width="1" opacity="0.9"/>`;
  const topLabel = state.size === 2
    ? `${top.name_p} + ${top.name_q} · ${fmtNum(top.attention_lift, 2)}×`
    : `${top.team_name} ${state.size}-player · ${fmtNum(top.attention_lift, 2)}×`;
  const labelAnchor = topX > W * 0.7 ? "end" : topX < W * 0.25 ? "start" : "middle";
  sparkEl.innerHTML = `
    <div class="spark-title">${rows.length} rows · lift × baseline</div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" class="spark-svg" role="img" aria-label="Lift distribution">
      ${bars}
      <text x="${topX.toFixed(1)}" y="${(H - 3).toFixed(0)}" text-anchor="${labelAnchor}" font-size="10" fill="currentColor" opacity="0.9">${escapeHTML(topLabel)}</text>
      <text x="${PAD}" y="${(H - 14).toFixed(0)}" font-size="9" fill="currentColor" opacity="0.5" text-anchor="start">${fmtNum(lo, 2)}×</text>
      <text x="${W - PAD}" y="${(H - 14).toFixed(0)}" font-size="9" fill="currentColor" opacity="0.5" text-anchor="end">${fmtNum(hi, 2)}×</text>
    </svg>
    <div class="spark-caption">Vertical mark = leading row in the table; bars = histogram across the filtered set.</div>
  `;
}

// ───────────────── Wire-up ─────────────────
attnTabs.forEach((b) => b.addEventListener("click", () => {
  attnTabs.forEach((x) => x.classList.toggle("active", x === b));
  state.category = b.dataset.cat;
  renderTable();
}));

if (attnSearchEl) attnSearchEl.addEventListener("input", () => {
  state.search = attnSearchEl.value || "";
  renderTable();
});

if (attnMinMinEl) attnMinMinEl.addEventListener("input", () => {
  state.minMin = Number(attnMinMinEl.value) || 0;
  renderTable();
});

if (attnShowGksEl) {
  attnShowGksEl.checked = state.showGks;
  attnShowGksEl.addEventListener("change", () => {
    state.showGks = !!attnShowGksEl.checked;
    renderTable();
  });
}

if (sizeSelect) sizeSelect.addEventListener("change", () => {
  state.size = Number(sizeSelect.value);
  // Min-minutes only applies to pairs.
  document.getElementById("attn-min-min-row")?.classList.toggle("hidden", state.size !== 2);
  renderTable();
});

// ───────────────── Load ─────────────────
const overview = await loadJSON("data/overview.json").catch(() => null);
const metrics = await loadJSON("data/vaep_metrics_transformer.json").catch(() => null);
renderAuc(metrics, overview?.vaep_metrics);

const idx = await loadJSON("data/attention_figures_index.json").catch(() => []);
renderAttentionGrid(idx, "");
if (teamSearchEl) teamSearchEl.addEventListener("input", () => renderAttentionGrid(idx, teamSearchEl.value));

pairsRaw = (await loadJSON("data/attention_pairs.json").catch(() => [])) || [];
groupsRaw = (await loadJSON("data/attention_groups.json").catch(() => [])) || [];
renderTable();
