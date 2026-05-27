/* Unified Chemistry Leaderboards page.
   Three modes share the same dataset(s) but have independent UI state. */

import {
  loadJSON, escapeHTML, fmtNum, fmtInt, renderEmpty,
  makeSortableTable, flagHTML, posChip,
} from "./site.js";

/* ─────────── shared formatting helpers ─────────── */

const CAT_COLOR = { off: "#d4793a", def: "#3b6ea0", cross: "#7a4f9a", mixed: "#888" };
const CAT_LABEL = { off: "Off ↔ Off", def: "Def ↔ Def", cross: "Cross", mixed: "Mixed" };
const OFFENSIVE_ROLES = new Set(["FWD", "MID"]);
const DEFENSIVE_ROLES = new Set(["DEF", "GK"]);

function fmtPair(row) {
  return `<strong>${escapeHTML(row.name_p)}</strong>${posChip(row.pos_p)}`
       + ` <span class="muted">+</span> `
       + `<strong>${escapeHTML(row.name_q)}</strong>${posChip(row.pos_q)}`;
}
function fmtTeam(row) {
  return `${flagHTML(row.flag_code, { alt: row.team_name })}${escapeHTML(row.team_name || row.team_id || "")}`;
}
function fmtGoalsAssists(g, a) {
  if (!g && !a) return `<span class="muted tabular">0 / 0</span>`;
  return `<span class="tabular">${g} <span class="muted">/</span> ${a}</span>`;
}
function categoryChip(cat) {
  const color = CAT_COLOR[cat] || "#888";
  return `<span class="cat-chip" style="background:${color}1A;color:${color};border-color:${color}50">${escapeHTML(CAT_LABEL[cat] || cat)}</span>`;
}
function rowHasGk(r) {
  if (!r) return false;
  if (r.role_p === "GK" || r.role_q === "GK") return true;
  if (r.pos_p === "GK" || r.pos_q === "GK") return true;
  return false;
}
function pairKey(r) {
  // Unordered (team_id, player_p, player_q).
  const lo = Math.min(r.player_p, r.player_q);
  const hi = Math.max(r.player_p, r.player_q);
  return `${r.team_id}|${lo}|${hi}`;
}
function zNormalize(values) {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return values.map(() => 0);
  const mean = finite.reduce((s, v) => s + v, 0) / finite.length;
  const variance = finite.reduce((s, v) => s + (v - mean) ** 2, 0) / Math.max(finite.length - 1, 1);
  const sd = Math.sqrt(variance) || 1;
  return values.map((v) => Number.isFinite(v) ? (v - mean) / sd : 0);
}

/* ─────────── load data once ─────────── */

const pairsRaw = (await loadJSON("data/pairs.json")) || [];
const attnPairsRaw = (await loadJSON("data/attention_pairs.json")) || [];

/* ─────────── mode switching ─────────── */

const modeButtons = document.querySelectorAll(".mode-bar button");
const sections = {
  event: document.getElementById("mode-event"),
  attention: document.getElementById("mode-attention"),
  disagree: document.getElementById("mode-disagree"),
  outcome: document.getElementById("mode-outcome"),
  awjoi: document.getElementById("mode-awjoi"),
  nucleus: document.getElementById("mode-nucleus"),
  team: document.getElementById("mode-team"),
};
let currentMode = "event";

modeButtons.forEach((b) => b.addEventListener("click", () => {
  currentMode = b.dataset.mode;
  modeButtons.forEach((x) => x.classList.toggle("active", x === b));
  for (const [k, el] of Object.entries(sections)) {
    el.classList.toggle("active", k === currentMode);
  }
  // disagree-mode needs a render kick if it hasn't shown yet
  if (currentMode === "disagree") renderDisagree();
  if (currentMode === "outcome") ocRender();
  if (currentMode === "awjoi") awRender();
  if (currentMode === "nucleus") nucRender();
  if (currentMode === "team") teamRender();
}));

/* ═══════════════════════════════════════════════════════════
   MODE 1 — Event-based (JOI / JDI / Cross)
   Adapted from pairs.js.
   ═══════════════════════════════════════════════════════════ */

const evState = { tab: "off" };
const evTabs = document.querySelectorAll("#event-tabs button");
const evSearchEl = document.getElementById("ev-search");
const evMinEl = document.getElementById("ev-min-minutes");
const evRoleEl = document.getElementById("ev-role-filter");
const evAlphaWrap = document.getElementById("ev-alpha-wrap");
const evAlphaEl = document.getElementById("ev-alpha");
const evAlphaVal = document.getElementById("ev-alpha-val");
const evTableEl = document.getElementById("ev-table");
let evTable = null;

function evMatchesRolePair(row, roleSel) {
  if (!roleSel || roleSel === "ALL") return true;
  const a = row.role_p || "";
  const b = row.role_q || "";
  const pair = new Set([a, b]);
  if (roleSel === "OFF_ROLES") return OFFENSIVE_ROLES.has(a) && OFFENSIVE_ROLES.has(b);
  if (roleSel === "DEF_ROLES") return DEFENSIVE_ROLES.has(a) && DEFENSIVE_ROLES.has(b);
  if (roleSel === "GK-ANY") return pair.has("GK");
  const [r1, r2] = roleSel.split("-");
  if (r1 === r2) return a === r1 && b === r2;
  return pair.has(r1) && pair.has(r2);
}

function evActiveMetricKey() {
  if (evState.tab === "off") return "joi90";
  if (evState.tab === "def") return "jdi90";
  return "cross_chem";
}
function evMetricLabel() {
  if (evState.tab === "off") return "JOI90 (VAEP·90/min)";
  if (evState.tab === "def") return "JDI90 (VAEP·90/min)";
  return "Cross-chem (z-blend)";
}

function evApplyFilters() {
  if (!evTable) return;
  const q = (evSearchEl.value || "").toLowerCase().trim();
  const minMin = Number(evMinEl.value) || 0;
  const roleSel = evRoleEl.value;

  let pool = pairsRaw.filter((r) => {
    if ((r.minutes_together ?? 0) < minMin) return false;
    if (!evMatchesRolePair(r, roleSel)) return false;
    if (!q) return true;
    return (
      (r.name_p || "").toLowerCase().includes(q) ||
      (r.name_q || "").toLowerCase().includes(q) ||
      (r.team_name || "").toLowerCase().includes(q)
    );
  });

  if (evState.tab === "cross") {
    const alpha = Number(evAlphaEl.value) / 100;
    const joiZ = zNormalize(pool.map((r) => r.joi90 ?? 0));
    const jdiZ = zNormalize(pool.map((r) => r.jdi90 ?? 0));
    pool = pool.map((r, i) => ({
      ...r,
      cross_chem: alpha * joiZ[i] + (1 - alpha) * jdiZ[i],
    }));
  }

  evTable.setData(pool);
  evRenderSpark(pool);
}

function evRenderSpark(pool) {
  const svg = document.getElementById("ev-spark-svg");
  const cap = document.getElementById("ev-spark-caption");
  if (!svg || !cap) return;
  const key = evActiveMetricKey();
  const sorted = pool.map((r) => Number(r[key])).filter(Number.isFinite).sort((a, b) => b - a);
  if (sorted.length < 2) {
    svg.innerHTML = "";
    cap.textContent = "Not enough qualifying pairs to draw a distribution.";
    return;
  }
  const W = 320, H = 60, pad = 2;
  const innerW = W - pad * 2, innerH = H - pad * 2;
  const vmin = Math.min(...sorted), vmax = Math.max(...sorted);
  const span = (vmax - vmin) || 1, n = sorted.length;
  const barW = Math.max(0.6, innerW / n - 0.5);
  let bars = "";
  for (let i = 0; i < n; i++) {
    const v = sorted[i];
    const x = pad + (i / n) * innerW;
    const h = Math.max(1, ((v - vmin) / span) * innerH);
    const y = pad + (innerH - h);
    bars += `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barW.toFixed(2)}" height="${h.toFixed(2)}" fill="currentColor" opacity="0.65"></rect>`;
  }
  const mid = sorted[Math.floor(n / 2)];
  const midY = pad + innerH - ((mid - vmin) / span) * innerH;
  bars += `<line x1="${pad}" x2="${W - pad}" y1="${midY.toFixed(2)}" y2="${midY.toFixed(2)}" stroke="currentColor" stroke-width="0.5" opacity="0.35" stroke-dasharray="2 2"/>`;
  svg.innerHTML = bars;
  const fmt = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2));
  cap.textContent = `${n} pairs, ${evMetricLabel()}. min ${fmt(vmin)} · median ${fmt(mid)} · max ${fmt(vmax)}.`;
}

function evBuildTable() {
  const baseCols = [
    { key: "team_name", label: "Team", render: fmtTeam },
    { key: "name_p", label: "Pair", render: fmtPair },
    { key: "minutes_together", label: "Min (shared)", num: true, digits: 0 },
    { key: "goals_together", label: "Goals / Assists (together)",
      render: (r) => fmtGoalsAssists(r.goals_together || 0, r.assists_together || 0) },
  ];
  let cols;
  if (evState.tab === "off") {
    cols = [
      ...baseCols,
      { key: "joi", label: "JOI (raw, VAEP)", num: true, digits: 2 },
      { key: "joi90", label: "JOI90 (VAEP·90/min)", num: true, digits: 2, defaultSort: true, defaultDir: "desc" },
    ];
  } else if (evState.tab === "def") {
    cols = [
      ...baseCols,
      { key: "jdi", label: "JDI (raw, VAEP saved)", num: true, digits: 3 },
      { key: "jdi90", label: "JDI90 (VAEP·90/min)", num: true, digits: 3, defaultSort: true, defaultDir: "desc" },
    ];
  } else {
    cols = [
      ...baseCols,
      { key: "joi90", label: "JOI90 (VAEP·90/min)", num: true, digits: 2 },
      { key: "jdi90", label: "JDI90 (VAEP·90/min)", num: true, digits: 3 },
      { key: "cross_chem", label: "Cross-chem (z-blend)", num: true, digits: 2, defaultSort: true, defaultDir: "desc" },
    ];
  }
  evTable = makeSortableTable({
    data: pairsRaw,
    columns: cols,
    container: evTableEl,
    emptyLabel: "No pairs match the current filters.",
  });
  evApplyFilters();
}

function evSwitchTab(tab) {
  evState.tab = tab;
  evTabs.forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  evAlphaWrap.classList.toggle("hidden", tab !== "cross");
  if (tab === "off") evRoleEl.value = "OFF_ROLES";
  else if (tab === "def") evRoleEl.value = "DEF_ROLES";
  else evRoleEl.value = "ALL";
  evBuildTable();
}

evTabs.forEach((b) => b.addEventListener("click", () => evSwitchTab(b.dataset.tab)));
evSearchEl.addEventListener("input", evApplyFilters);
evMinEl.addEventListener("input", evApplyFilters);
evRoleEl.addEventListener("change", evApplyFilters);
evAlphaEl.addEventListener("input", () => {
  evAlphaVal.textContent = (Number(evAlphaEl.value) / 100).toFixed(2);
  evApplyFilters();
});

/* ═══════════════════════════════════════════════════════════
   MODE 2 — Attention-based
   Adapted from transformer-chemistry.js (pairs only — groups
   are also supported via the same data file).
   ═══════════════════════════════════════════════════════════ */

const attState = { category: "all", search: "", minMin: 60, size: 2, showGks: false };
const attTabs = document.querySelectorAll("#att-tabs button");
const attSizeEl = document.getElementById("att-group-size");
const attSearchEl = document.getElementById("att-search");
const attMinEl = document.getElementById("att-min-min");
const attShowGksEl = document.getElementById("att-show-gks");
const attTableEl = document.getElementById("att-table");
const attSparkEl = document.getElementById("att-spark");

// Load groups lazily (only needed when size > 2).
let attGroupsRaw = null;
async function ensureGroups() {
  if (attGroupsRaw !== null) return;
  attGroupsRaw = (await loadJSON("data/attention_groups.json")) || [];
}

function attFilterPairs(rows) {
  return rows.filter((r) => {
    if (attState.category !== "all" && r.category !== attState.category) return false;
    if ((r.minutes_together ?? 0) < attState.minMin) return false;
    if (!attState.showGks && rowHasGk(r)) return false;
    const q = attState.search.trim().toLowerCase();
    if (q) {
      const hay = `${r.name_p || ""} ${r.name_q || ""} ${r.team_name || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}
function attFilterGroups(rows) {
  return rows.filter((r) => {
    if (r.size !== attState.size) return false;
    if (attState.category !== "all" && r.category !== attState.category) return false;
    if (!attState.showGks && Array.isArray(r.members)
        && r.members.some((m) => m.role === "GK" || m.position === "GK")) return false;
    const q = attState.search.trim().toLowerCase();
    if (q) {
      const hay = `${r.team_name || ""} ${r.members.map((m) => m.name).join(" ")}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function attRenderPairs(rows) {
  if (!rows.length) {
    renderEmpty(attTableEl, "No pairs match these filters.",
      "Try widening the category, lowering minutes, or clearing the search.");
    return;
  }
  const cols = [
    { key: "team_name", label: "Team",
      render: (r) => `${flagHTML(r.flag_code)}${escapeHTML(r.team_name || "")}` },
    { key: "name_p", label: "Pair",
      render: (r) => fmtPair(r) },
    { key: "category", label: "Edge type", render: (r) => categoryChip(r.category) },
    { key: "minutes_together", label: "Min", num: true, digits: 0 },
    { key: "goals_together", label: "Goals / Assists (together)",
      render: (r) => fmtGoalsAssists(r.goals_together || 0, r.assists_together || 0) },
    { key: "attention_per90", label: "Attn / 90", num: true, digits: 2 },
    { key: "attention_lift", label: "Lift × team baseline",
      num: true, digits: 2, defaultSort: true, defaultDir: "desc",
      render: (r) => `<span class="tabular"><strong>${fmtNum(r.attention_lift, 2)}×</strong></span>` },
  ];
  // makeSortableTable doesn't render until .render() is called (commit 6e1713c).
  makeSortableTable({ data: rows, columns: cols, container: attTableEl,
    emptyLabel: "No attention pairs." }).render();
}

function attRenderGroups(rows) {
  if (!rows.length) {
    renderEmpty(attTableEl, `No ${attState.size}-player groups match these filters.`,
      "Try widening the category or clearing the search.");
    return;
  }
  const cols = [
    { key: "team_name", label: "Team",
      render: (r) => `${flagHTML(r.flag_code)}${escapeHTML(r.team_name || "")}` },
    { key: "members", label: `${attState.size}-player unit`,
      render: (r) => r.members.map((m) => `<strong>${escapeHTML(m.name)}</strong>${posChip(m.position)}`).join(" <span class='muted'>·</span> ") },
    { key: "category", label: "Type", render: (r) => categoryChip(r.category) },
    { key: "n_pairs_observed", label: "Pairs measured",
      num: true, digits: 0,
      render: (r) => `<span class="tabular">${r.n_pairs_observed} / ${(r.size * (r.size - 1)) / 2}</span>` },
    { key: "avg_pair_attention_per90", label: "Avg pair attn / 90", num: true, digits: 2 },
    { key: "attention_lift", label: "Lift × team baseline",
      num: true, digits: 2, defaultSort: true, defaultDir: "desc",
      render: (r) => `<span class="tabular"><strong>${fmtNum(r.attention_lift, 2)}×</strong></span>` },
  ];
  makeSortableTable({ data: rows, columns: cols, container: attTableEl,
    emptyLabel: "No groups." }).render();
}

function attRenderSpark(rows) {
  if (!attSparkEl) return;
  if (!rows || rows.length < 2) {
    attSparkEl.innerHTML = `<div class="empty-state small">Need ≥ 2 rows for a distribution.</div>`;
    return;
  }
  const W = 320, H = 90, PAD = 4;
  const innerW = W - PAD * 2, innerH = H - 22;
  const vals = rows.map((r) => Number(r.attention_lift)).filter(Number.isFinite).slice().sort((a, b) => a - b);
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
  const topX = PAD + ((Number(top.attention_lift) - lo) / range) * innerW;
  bars += `<line x1="${topX.toFixed(1)}" y1="${PAD}" x2="${topX.toFixed(1)}" y2="${(PAD + innerH).toFixed(1)}" stroke="currentColor" stroke-width="1" opacity="0.9"/>`;
  const topLabel = attState.size === 2
    ? `${top.name_p} + ${top.name_q} · ${fmtNum(top.attention_lift, 2)}×`
    : `${top.team_name} ${attState.size}-player · ${fmtNum(top.attention_lift, 2)}×`;
  const labelAnchor = topX > W * 0.7 ? "end" : topX < W * 0.25 ? "start" : "middle";
  attSparkEl.innerHTML = `
    <div class="spark-title">${rows.length} rows · lift × baseline</div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" class="spark-svg" role="img" aria-label="Lift distribution">
      ${bars}
      <text x="${topX.toFixed(1)}" y="${(H - 3).toFixed(0)}" text-anchor="${labelAnchor}" font-size="10" fill="currentColor" opacity="0.9">${escapeHTML(topLabel)}</text>
      <text x="${PAD}" y="${(H - 14).toFixed(0)}" font-size="9" fill="currentColor" opacity="0.5" text-anchor="start">${fmtNum(lo, 2)}×</text>
      <text x="${W - PAD}" y="${(H - 14).toFixed(0)}" font-size="9" fill="currentColor" opacity="0.5" text-anchor="end">${fmtNum(hi, 2)}×</text>
    </svg>
    <div class="spark-caption">Vertical mark = leading row; bars = histogram of lift across the filtered set.</div>`;
}

async function attRender() {
  document.getElementById("att-min-min-row")?.classList.toggle("hidden", attState.size !== 2);
  if (attState.size === 2) {
    const rows = attFilterPairs(attnPairsRaw);
    attRenderPairs(rows);
    attRenderSpark(rows);
  } else {
    await ensureGroups();
    const rows = attFilterGroups(attGroupsRaw || []);
    attRenderGroups(rows);
    attRenderSpark(rows);
  }
}

attTabs.forEach((b) => b.addEventListener("click", () => {
  attTabs.forEach((x) => x.classList.toggle("active", x === b));
  attState.category = b.dataset.cat;
  attRender();
}));
attSearchEl.addEventListener("input", () => { attState.search = attSearchEl.value || ""; attRender(); });
attMinEl.addEventListener("input", () => { attState.minMin = Number(attMinEl.value) || 0; attRender(); });
attShowGksEl.addEventListener("change", () => { attState.showGks = !!attShowGksEl.checked; attRender(); });
attSizeEl.addEventListener("change", () => { attState.size = Number(attSizeEl.value); attRender(); });

/* ═══════════════════════════════════════════════════════════
   MODE 3 — Where they disagree
   Join by team_id + unordered (player_p, player_q).
   Compute percentile rank on each side, take |gap|.
   ═══════════════════════════════════════════════════════════ */

const disSearchEl = document.getElementById("dis-search");
const disDirEl = document.getElementById("dis-direction");
const disMinEl = document.getElementById("dis-min-minutes");
const disTableEl = document.getElementById("dis-table");

// Compute percentiles ONCE over the whole datasets (GK pairs excluded so
// the ranking isn't dominated by goalkeepers, who'd otherwise sit at the
// top of the attention distribution).
function computePercentiles(rows, key) {
  const filtered = rows.filter((r) => !rowHasGk(r));
  // Sort ascending; pct = (rank - 1) / (n - 1)  in [0,1].
  const indexed = filtered.map((r, i) => ({ r, v: Number(r[key]), i }))
    .filter((x) => Number.isFinite(x.v));
  indexed.sort((a, b) => a.v - b.v);
  const n = indexed.length;
  const pct = new Map();
  indexed.forEach((x, rank) => {
    pct.set(pairKey(x.r), n > 1 ? rank / (n - 1) : 0.5);
  });
  return pct;
}

const joiPct = computePercentiles(pairsRaw, "joi90");
const attnPct = computePercentiles(attnPairsRaw, "attention_lift");

// Build the joined dataset once. Each row has both pair metrics and the
// gap; filters then apply on top.
function buildDisagreeRows() {
  // Index event pairs by key for fast lookup.
  const evByKey = new Map();
  for (const r of pairsRaw) {
    if (rowHasGk(r)) continue;
    evByKey.set(pairKey(r), r);
  }
  const out = [];
  for (const ar of attnPairsRaw) {
    if (rowHasGk(ar)) continue;
    const k = pairKey(ar);
    const er = evByKey.get(k);
    if (!er) continue;
    const pJ = joiPct.get(k);
    const pA = attnPct.get(k);
    if (pJ === undefined || pA === undefined) continue;
    const gap = pA - pJ;          // > 0 -> attention high, JOI low
    out.push({
      team_id: ar.team_id,
      team_name: ar.team_name || er.team_name,
      flag_code: ar.flag_code || er.flag_code,
      player_p: ar.name_p, pos_p: ar.pos_p,
      player_q: ar.name_q, pos_q: ar.pos_q,
      // pairs.js / transformer-chemistry use name_p/name_q + pos_p/pos_q
      // so reuse those keys for fmtPair compatibility.
      name_p: ar.name_p, name_q: ar.name_q,
      minutes_together: Math.min(er.minutes_together ?? 0, ar.minutes_together ?? 0),
      joi90: er.joi90,
      attention_lift: ar.attention_lift,
      joi_pct: pJ,
      attn_pct: pA,
      gap,
      abs_gap: Math.abs(gap),
    });
  }
  return out;
}

const disRows = buildDisagreeRows();

function renderDisagree() {
  const q = (disSearchEl.value || "").toLowerCase().trim();
  const dir = disDirEl.value;
  const minMin = Number(disMinEl.value) || 0;
  let pool = disRows.filter((r) => {
    if ((r.minutes_together ?? 0) < minMin) return false;
    if (dir === "attn_high" && r.gap <= 0) return false;
    if (dir === "joi_high" && r.gap >= 0) return false;
    if (!q) return true;
    return (
      (r.name_p || "").toLowerCase().includes(q) ||
      (r.name_q || "").toLowerCase().includes(q) ||
      (r.team_name || "").toLowerCase().includes(q)
    );
  });
  pool.sort((a, b) => b.abs_gap - a.abs_gap);
  pool = pool.slice(0, 20);

  if (!pool.length) {
    renderEmpty(disTableEl, "No pairs survived the filters.",
      "Lower the minutes threshold or widen the direction filter.");
    return;
  }

  const cols = [
    { key: "rank", label: "#", render: (r) => `<span class="muted tabular">${r._rank}</span>` },
    { key: "team_name", label: "Team", render: fmtTeam },
    { key: "name_p", label: "Pair", render: fmtPair },
    { key: "minutes_together", label: "Min (shared)", num: true, digits: 0 },
    { key: "joi90", label: "JOI90",
      num: true, digits: 2,
      render: (r) => `<span class="tabular">${fmtNum(r.joi90, 2)}<br><span class="muted small">p${Math.round(r.joi_pct * 100)}</span></span>` },
    { key: "attention_lift", label: "Attn lift",
      num: true, digits: 2,
      render: (r) => `<span class="tabular">${fmtNum(r.attention_lift, 2)}×<br><span class="muted small">p${Math.round(r.attn_pct * 100)}</span></span>` },
    { key: "gap", label: "Gap (Attn − JOI)",
      num: true, digits: 0,
      render: (r) => {
        const pct = Math.round(r.gap * 100);
        const cls = pct >= 0 ? "delta-pos" : "delta-neg";
        const arrow = pct >= 0 ? "▲" : "▼";
        return `<span class="tabular ${cls}"><strong>${arrow} ${Math.abs(pct)} pts</strong></span>`;
      } },
    { key: "story", label: "Reads as",
      render: (r) => {
        if (r.gap > 0) return `<span class="muted small">Model watches them, ball rarely connects</span>`;
        return `<span class="muted small">Connect on the ball, model doesn't co-attend</span>`;
      } },
  ];
  pool.forEach((r, i) => { r._rank = i + 1; });

  makeSortableTable({
    data: pool, columns: cols, container: disTableEl,
    emptyLabel: "No disagreement rows.",
  }).render();
}

disSearchEl.addEventListener("input", renderDisagree);
disDirEl.addEventListener("change", renderDisagree);
disMinEl.addEventListener("input", renderDisagree);

/* ═══════════════════════════════════════════════════════════
   MODE 4 — Outcome-conditional attention
   Score-frame lift = attn_score_per_frame / attn_neutral_per_frame.
   Defaults to off-off (offensive chemistry isolated from GK bias).
   ═══════════════════════════════════════════════════════════ */

const ocState = { category: "off", rank: "lift_score", search: "", minMin: 60, showGks: false };
const ocRaw = (await loadJSON("data/attention_by_outcome.json")) || [];
const ocTabs = document.querySelectorAll("#oc-tabs button");
const ocRankEl = document.getElementById("oc-rank");
const ocSearchEl = document.getElementById("oc-search");
const ocMinEl = document.getElementById("oc-min-min");
const ocShowGksEl = document.getElementById("oc-show-gks");
const ocTableEl = document.getElementById("oc-table");

function ocFilter(rows) {
  const q = ocState.search.trim().toLowerCase();
  return rows.filter((r) => {
    if (ocState.category !== "all" && r.category !== ocState.category) return false;
    if ((r.minutes_together ?? 0) < ocState.minMin) return false;
    if (!ocState.showGks && rowHasGk(r)) return false;
    if (q) {
      const hay = `${r.name_p || ""} ${r.name_q || ""} ${r.team_name || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    // Require finite lift on the active rank metric.
    return Number.isFinite(r[ocState.rank]);
  });
}

function ocRender() {
  if (!ocRaw.length) {
    renderEmpty(ocTableEl, "Outcome-conditional attention not yet computed.",
      "Run research/scripts/extract_attention_by_outcome.py then analyze_attention_by_outcome.py.");
    return;
  }
  const rows = ocFilter(ocRaw).slice().sort((a, b) => b[ocState.rank] - a[ocState.rank]);
  if (!rows.length) {
    renderEmpty(ocTableEl, "No pairs match these filters.",
      "Lower minutes, widen the category, or toggle GKs.");
    return;
  }
  const rankLabel = ocState.rank === "lift_score" ? "Score lift" : "Concede lift";
  const scoreCol = ocState.rank === "lift_score" ? "attn_score_per_frame" : "attn_concede_per_frame";
  const scoreColLabel = ocState.rank === "lift_score" ? "Attn / frame (score)" : "Attn / frame (concede)";
  const liftKey = ocState.rank;
  const cols = [
    { key: "team_name", label: "Team",
      render: (r) => `${flagHTML(r.flag_code)}${escapeHTML(r.team_name || "")}` },
    { key: "name_p", label: "Pair", render: fmtPair },
    { key: "category", label: "Edge", render: (r) => categoryChip(r.category) },
    { key: "minutes_together", label: "Min", num: true, digits: 0 },
    { key: scoreCol, label: scoreColLabel, num: true, digits: 4 },
    { key: "attn_neutral_per_frame", label: "Attn / frame (neutral)", num: true, digits: 4 },
    { key: liftKey, label: `${rankLabel} (highlighted)`,
      num: true, digits: 2, defaultSort: true, defaultDir: "desc",
      render: (r) => `<span class="tabular delta-pos"><strong>${fmtNum(r[liftKey], 2)}×</strong></span>` },
  ];
  makeSortableTable({
    data: rows.slice(0, 300), columns: cols, container: ocTableEl,
    emptyLabel: "No outcome-conditional rows.",
  }).render();
}

ocTabs.forEach((b) => b.addEventListener("click", () => {
  ocTabs.forEach((x) => x.classList.toggle("active", x === b));
  ocState.category = b.dataset.cat;
  ocRender();
}));
ocRankEl.addEventListener("change", () => { ocState.rank = ocRankEl.value; ocRender(); });
ocSearchEl.addEventListener("input", () => { ocState.search = ocSearchEl.value || ""; ocRender(); });
ocMinEl.addEventListener("input", () => { ocState.minMin = Number(ocMinEl.value) || 0; ocRender(); });
ocShowGksEl.addEventListener("change", () => { ocState.showGks = !!ocShowGksEl.checked; ocRender(); });

/* ═══════════════════════════════════════════════════════════
   MODE 5 — AW-JOI · attention × value
   Sum over frames of (attn[p] × attn[q]) × max(±ΔV, 0), per pair,
   per-90 normalised. Score-specialist for AW-JOI side, concede-
   specialist for AW-JDI side. Net = AW-JOI − AW-JDI.
   ═══════════════════════════════════════════════════════════ */

// Default sort: AW-JOI90 (positive offensive chemistry) rather than Net.
// Net mixes AW-JOI and AW-JDI semantically and tilts toward forwards (who
// naturally have low AW-JDI). Showing the two separately is more honest.
// Default min minutes 200 — at 60 the per-90 normalisation gets dominated
// by small-sample pairs from teams that exited early (e.g. Mitrović+Radonjić
// 1.49 AW-JOI90 over 67 min vs Messi+Di María 0.63 over 294 min).
const awState = { category: "off", sortBy: "aw_joi90", search: "", minMin: 200 };
const awRaw = (await loadJSON("data/aw_chemistry.json")) || [];
const awTabs = document.querySelectorAll("#aw-tabs button");
const awSortEl = document.getElementById("aw-sort");
const awSearchEl = document.getElementById("aw-search");
const awMinEl = document.getElementById("aw-min-min");
const awTableEl = document.getElementById("aw-table");

function awFilter(rows) {
  const q = awState.search.trim().toLowerCase();
  return rows.filter((r) => {
    if (awState.category !== "all" && r.category !== awState.category) return false;
    if ((r.minutes_together ?? 0) < awState.minMin) return false;
    // Always exclude GK pairs from AW-JOI (the metric is supposed to surface
    // off-ball chemistry; GKs dominate raw attention regardless).
    if (r.role_p === "GK" || r.role_q === "GK") return false;
    if (q) {
      const hay = `${r.name_p || ""} ${r.name_q || ""} ${r.team_name || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return Number.isFinite(r[awState.sortBy]);
  });
}

function awRender() {
  if (!awRaw.length) {
    renderEmpty(awTableEl, "AW-JOI not yet computed.",
      "Run research/scripts/extract_aw_joi.py.");
    return;
  }
  const rows = awFilter(awRaw).slice().sort((a, b) => b[awState.sortBy] - a[awState.sortBy]);
  if (!rows.length) {
    renderEmpty(awTableEl, "No pairs match these filters.",
      "Lower minutes, widen the category, or change the sort.");
    return;
  }
  const sortKey = awState.sortBy;
  const isJoi = sortKey === "aw_joi90" || sortKey === "aw_joi_sum";
  const isJdi = sortKey === "aw_jdi90";
  const cols = [
    { key: "team_name", label: "Team",
      render: (r) => `${flagHTML(r.flag_code)}${escapeHTML(r.team_name || "")}` },
    { key: "name_p", label: "Pair", render: fmtPair },
    { key: "category", label: "Edge", render: (r) => categoryChip(r.category) },
    { key: "minutes_together", label: "Min", num: true, digits: 0 },
    { key: "aw_joi90", label: isJoi && sortKey === "aw_joi90" ? "AW-JOI90 ★" : "AW-JOI90",
      num: true, digits: 4, defaultSort: sortKey === "aw_joi90", defaultDir: "desc",
      render: (r) => {
        const v = r.aw_joi90;
        return sortKey === "aw_joi90"
          ? `<span class="tabular delta-pos"><strong>${fmtNum(v, 4)}</strong></span>`
          : `<span class="tabular">${fmtNum(v, 4)}</span>`;
      }},
    { key: "aw_jdi90", label: isJdi ? "AW-JDI90 ★" : "AW-JDI90",
      num: true, digits: 4, defaultSort: isJdi, defaultDir: "desc",
      render: (r) => {
        const v = r.aw_jdi90;
        return isJdi
          ? `<span class="tabular delta-neg"><strong>${fmtNum(v, 4)}</strong></span>`
          : `<span class="tabular dim">${fmtNum(v, 4)}</span>`;
      }},
    { key: "aw_net90", label: sortKey === "aw_net90" ? "Net ★" : "Net",
      num: true, digits: 4, defaultSort: sortKey === "aw_net90", defaultDir: "desc",
      render: (r) => {
        const v = r.aw_net90;
        const cls = v >= 0 ? "delta-pos" : "delta-neg";
        const bold = sortKey === "aw_net90";
        const sign = v >= 0 ? "+" : "";
        return bold
          ? `<span class="tabular ${cls}"><strong>${sign}${fmtNum(v, 4)}</strong></span>`
          : `<span class="tabular ${cls}">${sign}${fmtNum(v, 4)}</span>`;
      }},
    { key: "aw_joi_sum", label: sortKey === "aw_joi_sum" ? "AW-JOI sum ★" : "AW-JOI sum",
      num: true, digits: 2, defaultSort: sortKey === "aw_joi_sum", defaultDir: "desc",
      render: (r) => {
        const v = r.aw_joi_sum;
        return sortKey === "aw_joi_sum"
          ? `<span class="tabular delta-pos"><strong>${fmtNum(v, 2)}</strong></span>`
          : `<span class="tabular dim">${fmtNum(v, 2)}</span>`;
      }},
  ];
  makeSortableTable({
    data: rows.slice(0, 300), columns: cols, container: awTableEl,
    emptyLabel: "No AW-JOI rows.",
  }).render();
}

awTabs.forEach((b) => b.addEventListener("click", () => {
  awTabs.forEach((x) => x.classList.toggle("active", x === b));
  awState.category = b.dataset.cat;
  awRender();
}));
awSortEl.addEventListener("change", () => { awState.sortBy = awSortEl.value; awRender(); });
awSearchEl.addEventListener("input", () => { awState.search = awSearchEl.value || ""; awRender(); });
awMinEl.addEventListener("input", () => { awState.minMin = Number(awMinEl.value) || 0; awRender(); });

/* ═══════════════════════════════════════════════════════════
   MODE 6 — Nucleus networks
   Each player's chemistry network = sum of their AW-JOI across all
   teammates. Click a player to see their star-graph (nucleus + 8 spokes).
   Tufte-styled: no chartjunk, edge thickness ∝ AW-JOI90, partner-dot
   size ∝ AW-JOI90, partners arranged radially around the nucleus.
   ═══════════════════════════════════════════════════════════ */

// Default sort: breadth (# strong partners) — this is the story-rich metric.
// Top 10 by this sort is 4 France / 3 Croatia / 2 Morocco / 1 Argentina —
// the four deepest tournament sides. The "chemistry network shape predicts
// how far you go" finding only surfaces under this aggregation.
const nucState = { role: "all", sortBy: "n_strong_partners", search: "", selected: null };
const nucRaw = (await loadJSON("data/nucleus_networks.json")) || [];
const nucSearchEl = document.getElementById("nuc-search");
const nucRoleEl = document.getElementById("nuc-role");
const nucSortEl = document.getElementById("nuc-sort");
const nucTableEl = document.getElementById("nuc-table");
const nucDetailEl = document.getElementById("nuc-detail");

function nucFilter(rows) {
  const q = nucState.search.trim().toLowerCase();
  return rows.filter((r) => {
    if (nucState.role !== "all" && r.role !== nucState.role) return false;
    if (q) {
      const hay = `${r.name || ""} ${r.team_name || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return Number.isFinite(r[nucState.sortBy]);
  });
}

function nucRender() {
  if (!nucRaw.length) {
    renderEmpty(nucTableEl, "Nucleus networks not yet computed.", "Run the AW-JOI pipeline first.");
    return;
  }
  const rows = nucFilter(nucRaw).slice().sort((a, b) => b[nucState.sortBy] - a[nucState.sortBy]).slice(0, 50);
  if (!rows.length) {
    renderEmpty(nucTableEl, "No players match these filters.", "Lower minutes, widen the role, or change the sort.");
    return;
  }
  // Formatting per sort key
  const fmts = {
    network_joi90:      (v) => fmtNum(v, 2),
    network_top5_joi90: (v) => fmtNum(v, 2),
    network_joi_sum:    (v) => fmtNum(v, 1),
    network_net90:      (v) => (v >= 0 ? "+" : "") + fmtNum(v, 2),
    n_strong_partners:  (v) => String(Math.round(v)),
    team_lift:          (v) => fmtNum(v, 2) + "×",
  };
  const fmtField = fmts[nucState.sortBy] || ((v) => fmtNum(v, 2));
  nucTableEl.innerHTML = rows.map((r, i) => `
    <button class="nucleus-row${r.player_id === nucState.selected ? " active" : ""}" data-pid="${r.player_id}">
      <span class="nuc-rank">${i + 1}</span>
      <span class="nuc-flag">${flagHTML(r.flag_code)}</span>
      <span class="nuc-name">${escapeHTML(r.name)}<span class="nuc-pos">${escapeHTML(r.position || "")}</span></span>
      <span class="nuc-team">${escapeHTML(r.team_name || "")}</span>
      <span class="nuc-val tabular delta-pos"><strong>${fmtField(r[nucState.sortBy])}</strong></span>
    </button>
  `).join("");
  // Default-select the top row if nothing's selected yet
  if (!nucState.selected || !rows.find((r) => r.player_id === nucState.selected)) {
    nucState.selected = rows[0].player_id;
  }
  nucTableEl.querySelectorAll(".nucleus-row").forEach((btn) => {
    btn.addEventListener("click", () => {
      nucState.selected = Number(btn.dataset.pid);
      nucTableEl.querySelectorAll(".nucleus-row").forEach((b) => b.classList.toggle("active", Number(b.dataset.pid) === nucState.selected));
      drawNucleusDetail();
    });
  });
  drawNucleusDetail();
}

function drawNucleusDetail() {
  if (!nucState.selected) {
    nucDetailEl.innerHTML = `<div class="empty-state small">Click a player row to see their chemistry network.</div>`;
    return;
  }
  const r = nucRaw.find((x) => x.player_id === nucState.selected);
  if (!r) return;
  const spokes = (r.spokes || []).slice(0, 8);
  // Layout: wider canvas + more breathing room. Edges are fixed-length
  // (deterministic geometry — easier to read than length-encoded), with
  // partner-dot SIZE + edge THICKNESS doing the AW-JOI encoding.
  const W = 560, H = 460;
  const cx = W / 2, cy = H / 2;
  const radius = 150;
  const maxAW = spokes.reduce((m, s) => Math.max(m, s.aw_joi90 || 0), 1e-6);
  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="nucleus-svg" role="img" aria-label="${escapeHTML(r.name)} chemistry network">`;
  // Edges (under dots)
  spokes.forEach((s, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI / spokes.length);
    const ratio = (s.aw_joi90 || 0) / maxAW;
    const xEnd = cx + Math.cos(angle) * radius;
    const yEnd = cy + Math.sin(angle) * radius;
    // Stop the edge at the nucleus radius (28) so it doesn't overlap the center dot
    const xStart = cx + Math.cos(angle) * 26;
    const yStart = cy + Math.sin(angle) * 26;
    const width = 1.0 + ratio * 5.0;
    svg += `<line x1="${xStart.toFixed(1)}" y1="${yStart.toFixed(1)}" x2="${xEnd.toFixed(1)}" y2="${yEnd.toFixed(1)}" stroke="#f1ad7a" stroke-opacity="${(0.4 + ratio * 0.5).toFixed(2)}" stroke-width="${width.toFixed(2)}" stroke-linecap="round" />`;
  });
  // Partner dots + labels (above edges)
  spokes.forEach((s, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI / spokes.length);
    const ratio = (s.aw_joi90 || 0) / maxAW;
    const x = cx + Math.cos(angle) * radius;
    const y = cy + Math.sin(angle) * radius;
    const dotR = 6 + ratio * 6;
    svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${dotR.toFixed(1)}" fill="#1f2a3a" stroke="#e8eef9" stroke-width="1.3" />`;
    // Label: outside the dot, along the radial. The text-anchor flips so labels
    // on the left of the circle right-align, labels on the right left-align.
    const lOff = dotR + 9;
    const lx = cx + Math.cos(angle) * (radius + lOff);
    const ly = cy + Math.sin(angle) * (radius + lOff);
    const cosA = Math.cos(angle);
    const anchor = Math.abs(cosA) < 0.25 ? "middle" : (cosA > 0 ? "start" : "end");
    // Stack name on top, value below — shift so the *pair* (name + value) is
    // centered on the spoke endpoint.
    const surname = (s.partner_name || "").split(" ").slice(-1)[0] || s.partner_name;
    svg += `<text x="${lx.toFixed(1)}" y="${(ly - 4).toFixed(1)}" text-anchor="${anchor}" class="nuc-label">${escapeHTML(surname)} <tspan class="nuc-pos-small">${escapeHTML(s.partner_pos || "")}</tspan></text>`;
    svg += `<text x="${lx.toFixed(1)}" y="${(ly + 11).toFixed(1)}" text-anchor="${anchor}" class="nuc-edge-val">${fmtNum(s.aw_joi90, 2)}</text>`;
  });
  // Nucleus (on top) — slightly larger + cleaner inner type
  svg += `<circle cx="${cx}" cy="${cy}" r="26" fill="#0b1220" stroke="#6dd58c" stroke-width="2.2" />`;
  const surname = (r.name || "").split(" ").slice(-1)[0] || r.name;
  svg += `<text x="${cx}" y="${(cy - 3).toFixed(1)}" text-anchor="middle" class="nuc-center-name">${escapeHTML(surname)}</text>`;
  svg += `<text x="${cx}" y="${(cy + 12).toFixed(1)}" text-anchor="middle" class="nuc-center-pos">${escapeHTML(r.position || "")}</text>`;
  svg += `</svg>`;

  nucDetailEl.innerHTML = `
    <div class="nucleus-header">
      <div class="nucleus-hd-name">${flagHTML(r.flag_code)} <strong>${escapeHTML(r.name)}</strong> <span class="dim small">· ${escapeHTML(r.team_name || "")} · ${escapeHTML(r.position || "")}</span></div>
      <div class="nucleus-hd-stats">
        <span><span class="muted small">AW-JOI90</span> <strong class="tabular delta-pos">${fmtNum(r.network_joi90, 2)}</strong></span>
        <span><span class="muted small">Top-5 sum</span> <strong class="tabular">${fmtNum(r.network_top5_joi90, 2)}</strong></span>
        <span><span class="muted small">Strong partners</span> <strong class="tabular">${r.n_strong_partners} / ${r.n_partners}</strong></span>
        <span><span class="muted small">Team lift</span> <strong class="tabular">${fmtNum(r.team_lift, 2)}×</strong></span>
        <span><span class="muted small">Minutes</span> <strong class="tabular">${fmtNum(r.minutes_played, 0)}</strong></span>
      </div>
    </div>
    ${svg}
    <p class="dim small" style="margin: 0 0.6rem;">Edge thickness ∝ AW-JOI90 with that partner. Numbers under each name are AW-JOI90 values. Top-8 partners shown.</p>
  `;
}

nucSearchEl.addEventListener("input", () => { nucState.search = nucSearchEl.value || ""; nucRender(); });
nucRoleEl.addEventListener("change", () => { nucState.role = nucRoleEl.value; nucRender(); });
nucSortEl.addEventListener("change", () => { nucState.sortBy = nucSortEl.value; nucRender(); });

/* ═══════════════════════════════════════════════════════════
   MODE 7 — Team networks
   Per-team chemistry density: strong-pair counts (off / def / cross),
   mean AW-JOI90, Gini coefficient of pair-AW-JOI90 distribution.
   The headline pattern: top 4 by total strong pairs = 4 semifinalists.
   ═══════════════════════════════════════════════════════════ */

const teamRaw = (await loadJSON("data/team_networks.json")) || [];
const teamTableEl = document.getElementById("team-table");
const STAGE_COLOR = {
  Winner: "#6dd58c", Final: "#a3d39c", "3rd": "#cbd76c", "4th": "#e3cf6c",
  QF: "#d1a273", R16: "#a87a7a", Group: "#777"
};

function teamRender() {
  if (!teamRaw.length) {
    renderEmpty(teamTableEl, "Team networks not yet computed.", "Run the AW-JOI pipeline first.");
    return;
  }
  const cols = [
    { key: "team_name", label: "Team",
      render: (r) => `${flagHTML(r.flag_code)}<strong>${escapeHTML(r.team_name)}</strong>` },
    { key: "stage_rank", label: "Stage",
      render: (r) => `<span class="chip" style="background:${STAGE_COLOR[r.stage] || '#444'}22; color:${STAGE_COLOR[r.stage] || '#888'}; border-color:transparent">${escapeHTML(r.stage)}</span>` },
    { key: "n_strong_total", label: "Strong pairs",
      num: true, digits: 0, defaultSort: true, defaultDir: "desc",
      render: (r) => `<span class="tabular delta-pos"><strong>${r.n_strong_total}</strong></span>` },
    { key: "n_strong_off", label: "off-off",
      num: true, digits: 0,
      render: (r) => `<span class="tabular">${r.n_strong_off}</span>` },
    { key: "n_strong_def", label: "def-def",
      num: true, digits: 0,
      render: (r) => `<span class="tabular">${r.n_strong_def}</span>` },
    { key: "n_strong_cross", label: "cross",
      num: true, digits: 0,
      render: (r) => `<span class="tabular dim">${r.n_strong_cross}</span>` },
    { key: "mean_aw_joi90_all", label: "Mean AW-JOI90",
      num: true, digits: 2 },
    { key: "max_aw_joi90", label: "Max pair",
      num: true, digits: 2 },
    { key: "gini_aw_joi90", label: "Gini (lower = even)",
      num: true, digits: 2,
      render: (r) => {
        const v = r.gini_aw_joi90;
        const cls = v < 0.32 ? "delta-pos" : (v > 0.40 ? "delta-neg" : "");
        return `<span class="tabular ${cls}">${fmtNum(v, 2)}</span>`;
      }},
  ];
  makeSortableTable({ data: teamRaw, columns: cols, container: teamTableEl, emptyLabel: "No teams." }).render();
}

/* ─────────── boot ─────────── */

if (!pairsRaw.length) {
  renderEmpty(evTableEl, "Pairs data not yet computed.",
    "Run the export pipeline to produce data/pairs.json.");
} else {
  evBuildTable();
}
if (!attnPairsRaw.length) {
  renderEmpty(attTableEl, "Attention pairs not yet computed.",
    "Run scripts/analyze_space_and_chemistry.py to produce data/attention_pairs.json.");
} else {
  attRender();
}
// Disagree mode renders on first show; pre-render so first click is instant.
renderDisagree();
// Outcome mode renders on first show; pre-render too.
ocRender();
