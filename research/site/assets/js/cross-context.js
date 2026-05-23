import { loadJSON, escapeHTML, fmtNum, fmtInt, renderEmpty, flagHTML, posChip, makeSortableTable } from "./site.js";

const tableEl = document.getElementById("cc-table");
const searchEl = document.getElementById("cc-search");
const compEl = document.getElementById("cc-comp");
const metricEl = document.getElementById("cc-metric");
const playerSel = document.getElementById("cc-player");
const detailEl = document.getElementById("cc-player-detail");
const calibrationEl = document.getElementById("cc-calibration");
const tabs = document.querySelectorAll(".tab-bar button");

let mode = "drops";
let raw = null;
let table = null;

const COMP_LABELS = {
  wc_2022_pff: "WC22 (PFF)",
  wc_2022_sb: "WC22 (StatsBomb)",
  euro_2024: "Euro 2024",
  copa_america_2024: "Copa America 2024",
  ligue1_22_23: "Ligue 1 2022/23",
  bundesliga_23_24: "Bundesliga 2023/24",
  laliga_20_21: "La Liga 2020/21",
};

function compLabel(c) {
  return COMP_LABELS[c] || c;
}

function fmtPlayer(row) {
  return `<strong>${escapeHTML(row.name_in_source || "")}</strong>${posChip(row.position)}`;
}
function fmtTeam(row) {
  return `${flagHTML(row.flag_code, { alt: row.team_name })}${escapeHTML(row.team_name || "")}`;
}
function fmtComp(row) {
  return escapeHTML(compLabel(row.competition));
}
function fmtDelta(row) {
  const d = Number(row.delta_vs_wc22 ?? 0);
  const cls = d >= 0 ? "green" : "red";
  return `<span class="chip ${cls}">${(d >= 0 ? "+" : "") + fmtNum(d, 2)}</span>`;
}

function fmtDeltaCol(key) {
  return (row) => {
    const d = Number(row[key] ?? 0);
    const cls = d >= 0 ? "green" : "red";
    return `<span class="chip ${cls}">${(d >= 0 ? "+" : "") + fmtNum(d, 2)}</span>`;
  };
}

function buildTable() {
  const data = mode === "drops" ? raw.club_better_than_wc22 : raw.wc22_better_than_club;
  const metric = metricEl ? metricEl.value : "z";
  const deltaKey = metric === "raw" ? "delta_vs_wc22"
                  : metric === "touch" ? "delta_per_touch_vs_wc22"
                  : "delta_z_vs_wc22";
  const otherKey = metric === "raw" ? "oi_per90"
                  : metric === "touch" ? "oi_per_touch"
                  : "z_oi_per90";
  const wcKey = metric === "raw" ? "wc22_oi_per90"
                  : metric === "touch" ? "wc22_oi_per_touch"
                  : "wc22_z_oi_per90";
  const digits = metric === "touch" ? 3 : 2;
  const otherLabel = metric === "raw" ? "Other OI/90"
                  : metric === "touch" ? "Other OI/touch"
                  : "Other z";
  const wcLabel = metric === "raw" ? "WC22 OI/90"
                  : metric === "touch" ? "WC22 OI/touch"
                  : "WC22 z";
  const cols = [
    { key: "name_in_source", label: "Player", render: fmtPlayer },
    { key: "team_name", label: "WC22 team", render: fmtTeam },
    { key: "competition", label: "Other competition", render: fmtComp },
    { key: otherKey, label: otherLabel, num: true, digits },
    { key: wcKey, label: wcLabel, num: true, digits },
    { key: deltaKey, label: "Δ", render: fmtDeltaCol(deltaKey),
      defaultSort: true, defaultDir: mode === "drops" ? "desc" : "asc" },
    { key: "minutes", label: "Other min", num: true, digits: 0 },
    { key: "wc22_minutes", label: "WC22 min", num: true, digits: 0 },
  ];
  table = makeSortableTable({
    data,
    columns: cols,
    container: tableEl,
    emptyLabel: "No rows match the current filters.",
  });
  applyFilters();
}

function applyFilters() {
  if (!table || !raw) return;
  const all = mode === "drops" ? raw.club_better_than_wc22 : raw.wc22_better_than_club;
  const q = (searchEl.value || "").toLowerCase().trim();
  const comp = compEl.value;
  const pool = all.filter((r) => {
    if (comp !== "ALL" && r.competition !== comp) return false;
    if (!q) return true;
    return (r.name_in_source || "").toLowerCase().includes(q)
      || (r.team_name || "").toLowerCase().includes(q)
      || (compLabel(r.competition) || "").toLowerCase().includes(q);
  });
  table.setData(pool);
}

function fillCompSelect() {
  const comps = (raw.competitions_present || []).filter((c) => c !== "wc_2022_pff");
  compEl.innerHTML = `<option value="ALL">Any competition</option>` +
    comps.map((c) => `<option value="${escapeHTML(c)}">${escapeHTML(compLabel(c))}</option>`).join("");
}

function fillPlayerSelect() {
  const players = new Map();
  for (const r of raw.rows || []) {
    if (!players.has(r.pff_player_id)) {
      players.set(r.pff_player_id, {
        id: r.pff_player_id,
        name: r.name_in_source,
        team: r.team_name,
        flag: r.flag_code,
      });
    }
  }
  const sorted = [...players.values()].sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  playerSel.innerHTML = sorted.map((p) =>
    `<option value="${escapeHTML(String(p.id))}">${escapeHTML(p.name || "")} — ${escapeHTML(p.team || "")}</option>`
  ).join("");
  if (sorted.length) {
    // default to a recognizable name if present
    const preferred = sorted.find((p) => /Mbapp|Messi|Modric|Bellingham|Kane|Foden/.test(p.name || ""));
    playerSel.value = (preferred || sorted[0]).id;
    renderPlayer(Number(playerSel.value));
  }
}

function renderPlayer(pffId) {
  if (!raw) return;
  const rows = (raw.rows || []).filter((r) => Number(r.pff_player_id) === pffId);
  if (rows.length === 0) {
    detailEl.innerHTML = `<div class="empty-state"><strong>No data for that player.</strong></div>`;
    return;
  }
  const p = rows[0];
  const sorted = rows.slice().sort((a, b) => {
    if (a.competition === "wc_2022_pff") return -1;
    if (b.competition === "wc_2022_pff") return 1;
    return (a.competition || "").localeCompare(b.competition || "");
  });
  const tbody = sorted.map((r) => `
    <tr>
      <td>${escapeHTML(compLabel(r.competition))}</td>
      <td class="num">${fmtNum(r.minutes, 0)}</td>
      <td class="num">${fmtNum(r.oi_total, 2)}</td>
      <td class="num"><strong>${fmtNum(r.oi_per90, 2)}</strong></td>
      <td class="num">${r.competition === "wc_2022_pff" ? "—" : fmtDelta(r)}</td>
    </tr>`).join("");
  detailEl.innerHTML = `
    <div class="card flag-bg-wrap">
      <div class="flag-bg" ${p.flag_code ? `style="background-image:url(https://flagcdn.com/640x480/${p.flag_code}.png)"` : ""}></div>
      <h3 class="mt-0">${flagHTML(p.flag_code, { size: "lg", alt: p.team_name })}<strong>${escapeHTML(p.name_in_source || "")}</strong>${posChip(p.position)}</h3>
      <div class="meta">${escapeHTML(p.team_name || "")}</div>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Competition</th>
              <th class="num">Min</th>
              <th class="num">OI total</th>
              <th class="num">OI/90</th>
              <th class="num">Δ vs WC22</th>
            </tr>
          </thead>
          <tbody>${tbody}</tbody>
        </table>
      </div>
      <p class="small muted">OI = sum of VAEP across offensive actions (pass/cross/dribble/take-on/shot). OI/90 = OI normalized per 90 minutes.</p>
    </div>`;
}

function switchTab(newMode) {
  mode = newMode;
  tabs.forEach((b) => b.classList.toggle("active", b.dataset.tab === newMode));
  buildTable();
}

tabs.forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
searchEl.addEventListener("input", applyFilters);
compEl.addEventListener("change", applyFilters);
if (metricEl) metricEl.addEventListener("change", buildTable);
playerSel.addEventListener("change", () => renderPlayer(Number(playerSel.value)));

function renderCalibration() {
  if (!calibrationEl || !raw?.provider_calibration?.length) return;
  const tbody = raw.provider_calibration.slice(0, 15).map((r) => {
    const d = Number(r.calibration_delta ?? 0);
    const chip = d >= 0 ? "green" : "red";
    return `<tr>
      <td><strong>${escapeHTML(r.name_in_source || "")}</strong>${posChip(r.position)}</td>
      <td>${flagHTML(r.flag_code, { alt: r.team_name })}<span class="muted small">${escapeHTML(r.team_name || "")}</span></td>
      <td class="num">${fmtNum(r.wc22_oi_per90, 2)}</td>
      <td class="num">${fmtNum(r.sb_oi_per90, 2)}</td>
      <td class="num"><span class="chip ${chip}">${(d >= 0 ? "+" : "") + fmtNum(d, 2)}</span></td>
      <td class="num">${fmtNum(r.wc22_minutes, 0)} / ${fmtNum(r.sb_minutes, 0)}</td>
    </tr>`;
  }).join("");
  calibrationEl.innerHTML = `
    <div class="table-wrap"><table class="data-table">
      <thead><tr>
        <th>Player</th><th>Team</th>
        <th class="num">PFF OI/90</th><th class="num">SB OI/90</th>
        <th class="num">Δ (SB − PFF)</th><th class="num">Min (PFF / SB)</th>
      </tr></thead><tbody>${tbody}</tbody>
    </table></div>`;
}

const data = await loadJSON("data/cross_context.json");
if (!data) {
  renderEmpty(tableEl, "Cross-context data not yet computed.",
    "Run research/scripts/compute_cross_context.py and export_site_data.py.");
} else {
  raw = data;
  fillCompSelect();
  buildTable();
  fillPlayerSelect();
  renderCalibration();
}
