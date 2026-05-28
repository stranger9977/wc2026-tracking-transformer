/* Chemistry Leaderboard — Tab 2.
   Headlined by Team Chemistry Density (TCD). One sortable 31-row table;
   clicking a row renders that team's pair network (reused from the old
   Team networks sub-tab). */

import {
  loadJSON, escapeHTML, fmtNum, flagHTML,
  makeSortableTable, renderEmpty,
} from "./site.js";

/* ─────────── data loads ─────────── */

const teamRows        = (await loadJSON("data/team_chemistry_vs_paper.json")) || [];
const teamFullNetworks = (await loadJSON("data/team_full_networks.json")) || {};
const awPairs         = (await loadJSON("data/aw_chemistry.json")) || [];

/* ─────────── derive top AW-JOI pair per team ─────────── */

const topPairByTeam = (() => {
  const best = new Map();
  for (const r of awPairs) {
    if (!Number.isFinite(r.aw_joi90)) continue;
    if (r.role_p === "GK" || r.role_q === "GK") continue;  // off-pair flavor
    const prev = best.get(r.team_id);
    if (!prev || r.aw_joi90 > prev.aw_joi90) {
      best.set(r.team_id, r);
    }
  }
  return best;
})();

function topPairFor(teamId) {
  const r = topPairByTeam.get(teamId);
  if (!r) return null;
  return r;
}

/* ─────────── stage chip colours ─────────── */

const STAGE_COLOR = {
  Winner: "#6dd58c", Final: "#a3d39c", "3rd": "#cbd76c", "4th": "#e3cf6c",
  QF: "#d1a273", R16: "#a87a7a", Group: "#777",
};

/* ─────────── pitch coordinates for team-atom rendering ─────────── */

const POS_XY = {
  GK: [8, 32],
  LCB: [22, 22], RCB: [22, 42], CB: [22, 32],
  LB: [28, 10], RB: [28, 54],
  DM: [42, 32],
  LM: [50, 16], RM: [50, 48], CM: [55, 32], AM: [65, 32],
  LW: [78, 14], RW: [78, 50],
  CF: [88, 32], ST: [88, 32],
};
function pitchXY(position, idx, sameCount) {
  const base = POS_XY[position] || [55, 32];
  const offset = sameCount > 1 ? (idx - (sameCount - 1) / 2) * 8 : 0;
  return [base[0], Math.max(4, Math.min(60, base[1] + offset))];
}

/* ─────────── leaderboard table ─────────── */

const tableEl   = document.getElementById("tcd-table");
const atomEl    = document.getElementById("team-atom");
const jdiPanel  = document.getElementById("team-jdi-panel");
const headingEl = document.getElementById("team-network-heading");
let teamSelected = null;

function safeNum(x) { return Number.isFinite(x) ? x : null; }

function renderLeaderboard() {
  if (!teamRows.length) {
    renderEmpty(tableEl, "Team chemistry data not yet computed.",
      "Run the AW-JOI pipeline first.");
    return;
  }

  // Augment each row with the top-pair string so the column can sort/filter
  // on it (sort by team_name on tie is fine).
  const rows = teamRows.map((r) => {
    const tp = topPairFor(r.team_id);
    return {
      ...r,
      tcd: safeNum(r.tcd) ?? 0,
      tcd_off: safeNum(r.tcd_off) ?? 0,
      tcd_def: safeNum(r.tcd_def) ?? 0,
      tcd_cross_net: safeNum(r.tcd_cross_net) ?? 0,
      overall: safeNum(r.overall),
      history_index_count: safeNum(r.history_index_count) ?? 0,
      history_index_squadN: safeNum(r.history_index_squadN) ?? 0,
      _top_pair_label: tp ? `${tp.name_p} + ${tp.name_q}` : "",
      _top_pair_value: tp ? tp.aw_joi90 : 0,
    };
  });

  const cols = [
    { key: "tcd_rank", label: "#",
      num: true, digits: 0,
      render: (r) => `<span class="muted tabular">${r.tcd_rank ?? ""}</span>` },
    { key: "team_name", label: "Team",
      render: (r) => `<button class="team-pick-btn${teamSelected === r.team_id ? " active" : ""}" data-tid="${escapeHTML(r.team_id)}">${flagHTML(r.flag_code)}<strong>${escapeHTML(r.team_name)}</strong></button>` },
    { key: "tcd", label: "TCD",
      num: true, digits: 0, defaultSort: true, defaultDir: "desc",
      render: (r) => `<span class="tabular delta-pos"><strong>${r.tcd}</strong></span>` },
    { key: "tcd_off", label: "TCD-off",
      num: true, digits: 0,
      render: (r) => `<span class="tabular">${r.tcd_off}</span>` },
    { key: "tcd_def", label: "TCD-def",
      num: true, digits: 0,
      render: (r) => `<span class="tabular">${r.tcd_def}</span>` },
    { key: "tcd_cross_net", label: "TCD-cross",
      num: true, digits: 0,
      render: (r) => {
        const v = r.tcd_cross_net;
        const cls = v > 0 ? "delta-pos" : (v < 0 ? "delta-neg" : "");
        const sign = v > 0 ? "+" : "";
        return `<span class="tabular ${cls}">${sign}${v}</span>`;
      }},
    { key: "overall", label: "FIFA-23 Overall",
      num: true, digits: 1,
      render: (r) => r.overall == null
        ? `<span class="tabular muted">—</span>`
        : `<span class="tabular">${fmtNum(r.overall, 1)}</span>` },
    { key: "stage_int", label: "WC22 finish",
      num: true, digits: 0,
      render: (r) => `<span class="chip" style="background:${STAGE_COLOR[r.stage] || '#444'}22; color:${STAGE_COLOR[r.stage] || '#888'}; border-color:transparent">${escapeHTML(r.stage || "")}</span>` },
    { key: "history_index_count", label: "History Index",
      num: true, digits: 0,
      render: (r) => `<a class="hist-link tabular" href="how-chemistry-develops.html"><strong>${r.history_index_count}</strong><span class="muted small"> / ${r.history_index_squadN}</span></a>` },
    { key: "_top_pair_value", label: "Top pair",
      num: true, digits: 2,
      render: (r) => r._top_pair_label
        ? `<span class="top-pair-cell">${escapeHTML(r._top_pair_label)} <span class="muted small">(${fmtNum(r._top_pair_value, 2)})</span></span>`
        : `<span class="muted">—</span>` },
  ];

  makeSortableTable({
    data: rows, columns: cols, container: tableEl,
    emptyLabel: "No teams.",
  }).render();

  // Default selection: top team by TCD.
  if (!teamSelected) {
    const sorted = rows.slice().sort((a, b) => b.tcd - a.tcd);
    teamSelected = sorted[0]?.team_id;
    if (teamSelected) drawTeamAtom(teamSelected);
  }
  syncActiveButtons();
  populateTeamPicker(rows);
}

function populateTeamPicker(rows) {
  const picker = document.getElementById("team-picker");
  if (!picker) return;
  const alpha = rows.slice().sort((a, b) =>
    (a.team_name || "").localeCompare(b.team_name || ""));
  picker.innerHTML = alpha.map((r) =>
    `<option value="${escapeHTML(r.team_id)}"${r.team_id === teamSelected ? " selected" : ""}>${escapeHTML(r.team_name)}</option>`).join("");
  picker.value = teamSelected;
  // Avoid double-binding on re-render.
  if (!picker.dataset.bound) {
    picker.addEventListener("change", (e) => {
      teamSelected = e.target.value;
      syncActiveButtons();
      drawTeamAtom(teamSelected);
    });
    picker.dataset.bound = "1";
  }
}

// Delegated handler — survives re-renders triggered by header-clicks.
tableEl.addEventListener("click", (e) => {
  const btn = e.target.closest(".team-pick-btn");
  if (!btn) return;
  e.stopPropagation();
  teamSelected = btn.dataset.tid;
  syncActiveButtons();
  drawTeamAtom(teamSelected);
});

function syncActiveButtons() {
  tableEl.querySelectorAll(".team-pick-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.tid === teamSelected));
}

/* ─────────── per-team pair-network atom ─────────── */

function isOff(pos) { return /^(CF|ST|LW|RW|AM|CM|DM|LM|RM)$/.test(pos || ""); }
function isDef(pos) { return /^(CB|LB|RB|LCB|RCB|GK)$/.test(pos || ""); }

function drawTeamAtom(teamId) {
  const net  = teamFullNetworks[teamId];
  const meta = teamRows.find((t) => t.team_id === teamId);
  if (!net || !meta) {
    atomEl.innerHTML = `<div class="empty-state small">Network data missing for ${escapeHTML(teamId)}.</div>`;
    jdiPanel.innerHTML = `<div class="empty-state small">No defensive-edge data for ${escapeHTML(teamId)}.</div>`;
    return;
  }
  headingEl.textContent = `Team pair network — ${meta.team_name}`;

  // Place each node on the pitch by position; fan same-position nodes out.
  const byPos = {};
  for (const n of net.nodes) {
    const p = n.position || "CM";
    (byPos[p] = byPos[p] || []).push(n);
  }
  const placed = new Map();
  for (const pos in byPos) {
    const list = byPos[pos];
    list.sort((a, b) => b.minutes - a.minutes);
    list.forEach((n, i) => {
      const [x, y] = pitchXY(pos, i, list.length);
      placed.set(n.player_id, { ...n, x, y });
    });
  }

  // Edges — threshold so the atom doesn't go to mush.
  const edges = net.edges.filter((e) =>
    placed.has(e.p) && placed.has(e.q) &&
    Number.isFinite(e.aw_joi90) && e.aw_joi90 >= 0.3);
  const maxAW = Math.max(0.4, ...edges.map((e) => e.aw_joi90));

  const W = 100, H = 64, padX = 4, padY = 4;
  const scaleX = (x) => padX + (x / 100) * (W - 2 * padX);
  const scaleY = (y) => padY + (y / 64) * (H - 2 * padY);
  const catColor = { off: "#d4793a", def: "#3b6ea0", cross: "#7a4f9a" };

  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="atom-svg" role="img" aria-label="${escapeHTML(meta.team_name)} chemistry atom">`;
  svg += `<rect x="${padX}" y="${padY}" width="${W - 2*padX}" height="${H - 2*padY}" fill="none" stroke="#2a313d" stroke-width="0.2" />`;
  svg += `<line x1="${W/2}" y1="${padY}" x2="${W/2}" y2="${H - padY}" stroke="#2a313d" stroke-width="0.15" />`;
  svg += `<circle cx="${W/2}" cy="${H/2}" r="5" stroke="#2a313d" stroke-width="0.15" fill="none" />`;

  for (const e of edges) {
    const a = placed.get(e.p), b = placed.get(e.q);
    if (!a || !b) continue;
    const cat = (isOff(a.position) && isOff(b.position)) ? "off"
             : (isDef(a.position) && isDef(b.position)) ? "def" : "cross";
    const ratio = e.aw_joi90 / maxAW;
    const w  = 0.15 + ratio * 0.9;
    const op = (0.25 + ratio * 0.55).toFixed(2);
    svg += `<line x1="${scaleX(a.x).toFixed(1)}" y1="${scaleY(a.y).toFixed(1)}" x2="${scaleX(b.x).toFixed(1)}" y2="${scaleY(b.y).toFixed(1)}" stroke="${catColor[cat]}" stroke-opacity="${op}" stroke-width="${w.toFixed(2)}" stroke-linecap="round"><title>${escapeHTML(e.name_p)} ↔ ${escapeHTML(e.name_q)}: AW-JOI90 ${fmtNum(e.aw_joi90, 2)}</title></line>`;
  }
  for (const n of placed.values()) {
    const r = 0.9 + Math.min(1.0, n.minutes / 600) * 0.7;
    svg += `<circle cx="${scaleX(n.x).toFixed(1)}" cy="${scaleY(n.y).toFixed(1)}" r="${r.toFixed(2)}" fill="#1f2a3a" stroke="#e8eef9" stroke-width="0.18"><title>${escapeHTML(n.name)} (${escapeHTML(n.position)}) · ${fmtNum(n.minutes, 0)} min</title></circle>`;
    const surname = (n.name || "").split(" ").slice(-1)[0] || n.name;
    svg += `<text x="${scaleX(n.x).toFixed(1)}" y="${(scaleY(n.y) + r + 1.6).toFixed(1)}" text-anchor="middle" class="atom-label">${escapeHTML(surname)}</text>`;
  }
  svg += `</svg>`;

  atomEl.innerHTML = `
    <div class="atom-header">
      <div><strong>${flagHTML(meta.flag_code)} ${escapeHTML(meta.team_name)}</strong>
        <span class="dim small">· ${escapeHTML(meta.stage || "")} · TCD ${meta.tcd ?? "—"} · ${edges.length} strong edges</span></div>
      <div class="atom-legend small dim">
        <span><span class="dot" style="background:#d4793a"></span>off↔off</span>
        <span><span class="dot" style="background:#3b6ea0"></span>def↔def</span>
        <span><span class="dot" style="background:#7a4f9a"></span>cross</span>
      </div>
    </div>
    ${svg}
    <p class="dim small" style="margin:0.4rem 0.6rem 0">Edge thickness ∝ AW-JOI90 (offensive joint impact). Edges below 0.3 hidden. Hover for pair-level values.</p>
  `;

  // Defensive panel: top AW-JDI edges for this team.
  drawJdiPanel(net, meta);
}

function drawJdiPanel(net, meta) {
  // GK exclusion — mirrors the off-pair (AW-JOI) filter so the def-pair
  // leaderboard isn't flooded by goalkeepers (they touch the ball on every
  // defensive sequence and the AW-JDI weight floods them).
  const gkIds = new Set(
    (net.nodes || []).filter((n) => (n.position || "").toUpperCase() === "GK").map((n) => n.player_id)
  );
  const jdiEdges = (net.edges || [])
    .filter((e) => Number.isFinite(e.aw_jdi90))
    .filter((e) => !gkIds.has(e.p) && !gkIds.has(e.q))
    .filter((e) => (e.role_p || "").toUpperCase() !== "GK" && (e.role_q || "").toUpperCase() !== "GK")
    .slice()
    .sort((a, b) => b.aw_jdi90 - a.aw_jdi90)
    .slice(0, 8);
  if (!jdiEdges.length) {
    jdiPanel.innerHTML = `<div class="empty-state small">No defensive edges for ${escapeHTML(meta.team_name)}.</div>`;
    return;
  }
  const rows = jdiEdges.map((e) => `
    <tr>
      <td>${escapeHTML(e.name_p)} <span class="muted">+</span> ${escapeHTML(e.name_q)}</td>
      <td class="num tabular">${fmtNum(e.aw_jdi90, 2)}</td>
      <td class="num tabular muted">${fmtNum(e.minutes_together, 0)} min</td>
    </tr>`).join("");
  jdiPanel.innerHTML = `
    <h3 style="font-size:1rem; margin-bottom:0.3rem">Top defensive pairs — ${escapeHTML(meta.team_name)}</h3>
    <p class="small dim" style="margin-top:0">Ranked by AW-JDI90 (attention-weighted joint defensive impact per 90). <span class="dim">(GKs excluded — they dominate every defensive sequence.)</span></p>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>Pair</th><th class="num">AW-JDI90</th><th class="num">Min together</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

/* ─────────── boot ─────────── */

renderLeaderboard();
