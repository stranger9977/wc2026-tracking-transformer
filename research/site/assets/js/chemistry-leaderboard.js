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
