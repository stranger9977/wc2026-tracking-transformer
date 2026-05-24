import { loadJSON, escapeHTML, fmtNum, fmtInt, renderEmpty, makeSortableTable,
         flagHTML, posChip, nameWithPos } from "./site.js";

const tableEl = document.getElementById("pairs-table");
const searchEl = document.getElementById("search");
const minEl = document.getElementById("min-minutes");
const roleEl = document.getElementById("role-filter");
const alphaWrap = document.getElementById("alpha-wrap");
const alphaEl = document.getElementById("alpha");
const alphaVal = document.getElementById("alpha-val");
const tabs = document.querySelectorAll(".tab-bar button");

let raw = [];
let mode = "off";
let table = null;

function fmtPlayers(row) {
  return `<strong>${escapeHTML(row.name_p)}</strong>${posChip(row.pos_p)}`
       + ` <span class="muted">+</span> `
       + `<strong>${escapeHTML(row.name_q)}</strong>${posChip(row.pos_q)}`;
}

function fmtTeam(row) {
  return `${flagHTML(row.flag_code, { alt: row.team_name })}${escapeHTML(row.team_name || row.team_id || "")}`;
}

function fmtGoalsAssists(row) {
  const g = row.goals_together || 0;
  const a = row.assists_together || 0;
  // Tufte: a number-pair is read with eyes. Drop the unlabelled emoji chips,
  // align right with tabular-nums, and let the column header carry the unit.
  if (g === 0 && a === 0) return `<span class="muted tabular">0 / 0</span>`;
  return `<span class="tabular">${g} <span class="muted">/</span> ${a}</span>`;
}

function zNormalize(values) {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return values.map(() => 0);
  const mean = finite.reduce((s, v) => s + v, 0) / finite.length;
  const variance = finite.reduce((s, v) => s + (v - mean) ** 2, 0) / Math.max(finite.length - 1, 1);
  const sd = Math.sqrt(variance) || 1;
  return values.map((v) => Number.isFinite(v) ? (v - mean) / sd : 0);
}

const OFFENSIVE_ROLES = new Set(["FWD", "MID"]);
const DEFENSIVE_ROLES = new Set(["DEF", "GK"]);

function matchesRolePair(row, roleSel) {
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

function applyFilters() {
  if (!table) return;
  const q = (searchEl.value || "").toLowerCase().trim();
  const minMin = Number(minEl.value) || 0;
  const roleSel = roleEl ? roleEl.value : "ALL";

  let pool = raw.filter((r) => {
    if ((r.minutes_together ?? 0) < minMin) return false;
    if (!matchesRolePair(r, roleSel)) return false;
    if (!q) return true;
    return (
      (r.name_p || "").toLowerCase().includes(q) ||
      (r.name_q || "").toLowerCase().includes(q) ||
      (r.team_name || "").toLowerCase().includes(q)
    );
  });

  if (mode === "cross") {
    const alpha = Number(alphaEl.value) / 100;
    const joiZ = zNormalize(pool.map((r) => r.joi90 ?? 0));
    const jdiZ = zNormalize(pool.map((r) => r.jdi90 ?? 0));
    pool = pool.map((r, i) => ({
      ...r,
      cross_chem: alpha * joiZ[i] + (1 - alpha) * jdiZ[i],
      _joi_z: joiZ[i],
      _jdi_z: jdiZ[i],
    }));
  }

  table.setData(pool);
  renderSparkline(pool);
}

function activeMetricKey() {
  if (mode === "off") return "joi90";
  if (mode === "def") return "jdi90";
  return "cross_chem";
}

function metricLabel() {
  if (mode === "off") return "JOI90 (VAEP·90/min)";
  if (mode === "def") return "JDI90 (VAEP·90/min)";
  return "Cross-chem (z-blend)";
}

function renderSparkline(pool) {
  const svg = document.getElementById("pairs-spark-svg");
  const cap = document.getElementById("pairs-spark-caption");
  if (!svg || !cap) return;
  const key = activeMetricKey();
  const sorted = pool
    .map((r) => Number(r[key]))
    .filter((v) => Number.isFinite(v))
    .sort((a, b) => b - a);
  if (sorted.length < 2) {
    svg.innerHTML = "";
    cap.textContent = "Not enough qualifying pairs to draw a distribution.";
    return;
  }
  const W = 320, H = 60, pad = 2;
  const innerW = W - pad * 2;
  const innerH = H - pad * 2;
  const vmin = Math.min(...sorted);
  const vmax = Math.max(...sorted);
  const span = (vmax - vmin) || 1;
  const n = sorted.length;
  const barW = Math.max(0.6, innerW / n - 0.5);
  let bars = "";
  for (let i = 0; i < n; i++) {
    const v = sorted[i];
    const x = pad + (i / n) * innerW;
    const h = Math.max(1, ((v - vmin) / span) * innerH);
    const y = pad + (innerH - h);
    bars += `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barW.toFixed(2)}" height="${h.toFixed(2)}" fill="currentColor" opacity="0.65"></rect>`;
  }
  // Median rule.
  const mid = sorted[Math.floor(n / 2)];
  const midY = pad + innerH - ((mid - vmin) / span) * innerH;
  bars += `<line x1="${pad}" x2="${W - pad}" y1="${midY.toFixed(2)}" y2="${midY.toFixed(2)}" stroke="currentColor" stroke-width="0.5" opacity="0.35" stroke-dasharray="2 2"/>`;
  svg.innerHTML = bars;
  const fmt = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2));
  cap.textContent = `${n} pairs, ${metricLabel()}. min ${fmt(vmin)} · median ${fmt(mid)} · max ${fmt(vmax)}.`;
}

function buildTable() {
  // Column labels carry units — Tufte: numeric columns always state the unit.
  const baseCols = [
    { key: "team_name", label: "Team", render: fmtTeam },
    { key: "name_p", label: "Pair", render: fmtPlayers },
    { key: "minutes_together", label: "Min (shared)", num: true, digits: 0 },
    { key: "goals_together", label: "Goals / Assists (together)", render: fmtGoalsAssists },
  ];

  let cols;
  if (mode === "off") {
    cols = [
      ...baseCols,
      { key: "joi", label: "JOI (raw, VAEP)", num: true, digits: 2 },
      { key: "joi90", label: "JOI90 (VAEP·90/min)", num: true, digits: 2, defaultSort: true, defaultDir: "desc" },
    ];
  } else if (mode === "def") {
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

  table = makeSortableTable({
    data: raw,
    columns: cols,
    container: tableEl,
    emptyLabel: "No pairs match the current filters.",
  });
  applyFilters();
}

function switchTab(newMode) {
  mode = newMode;
  tabs.forEach((b) => b.classList.toggle("active", b.dataset.tab === newMode));
  alphaWrap.classList.toggle("hidden", newMode !== "cross");
  if (roleEl) {
    // Pick the right default for this tab. User can override afterwards.
    if (newMode === "off") roleEl.value = "OFF_ROLES";
    else if (newMode === "def") roleEl.value = "DEF_ROLES";
    else roleEl.value = "ALL";
  }
  buildTable();
}

tabs.forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
searchEl.addEventListener("input", applyFilters);
minEl.addEventListener("input", applyFilters);
if (roleEl) roleEl.addEventListener("change", applyFilters);
alphaEl.addEventListener("input", () => {
  alphaVal.textContent = (Number(alphaEl.value) / 100).toFixed(2);
  applyFilters();
});

const data = await loadJSON("data/pairs.json");
if (!data || !Array.isArray(data) || data.length === 0) {
  renderEmpty(tableEl, "Pairs data not yet computed.",
    "Run the export pipeline to produce data/pairs.json.");
} else {
  raw = data;
  buildTable();
}
