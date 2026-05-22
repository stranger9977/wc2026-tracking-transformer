import { loadJSON, escapeHTML, fmtNum, renderEmpty, flagHTML, posChip, nameWithPos } from "./site.js";

const bodyEl = document.getElementById("builder-body");
const selectEl = document.getElementById("team-select");
const formationVal = document.getElementById("formation-val");
const scoreVal = document.getElementById("score-val");

const teams = await loadJSON("data/team_builder.json");

if (!teams || !Array.isArray(teams) || teams.length === 0) {
  renderEmpty(bodyEl, "Team-builder data not yet computed.",
    "Expected file: data/team_builder.json");
} else {
  // sort teams alphabetically
  teams.sort((a, b) => (a.team_name || "").localeCompare(b.team_name || ""));

  selectEl.innerHTML = teams.map((t) =>
    `<option value="${escapeHTML(t.team_id)}">${escapeHTML(t.team_name)}</option>`
  ).join("");

  function findTeam(id) {
    return teams.find((t) => String(t.team_id) === String(id));
  }

  function rolePositions(formation, roles) {
    // place GK at bottom (y=92%), then layered rows by role
    // We support common formations; otherwise space rows evenly.
    const groups = { GK: [], DEF: [], MID: [], FWD: [] };
    roles.forEach((p, i) => {
      const k = (p.role || "").toUpperCase();
      if (groups[k]) groups[k].push({ ...p, _idx: i });
      else groups.MID.push({ ...p, _idx: i });
    });

    const positions = [];
    const rowY = { GK: 92, DEF: 75, MID: 50, FWD: 22 };
    // For 4-2-3-1 split MID into two rows visually
    const isFiveBand = formation && /4-2-3-1|4-1-2-1-2|4-3-2-1/.test(formation);

    function placeRow(players, yPct) {
      const n = players.length;
      players.forEach((p, k) => {
        const xPct = ((k + 1) / (n + 1)) * 100;
        positions.push({ ...p, x: xPct, y: yPct });
      });
    }

    placeRow(groups.GK, rowY.GK);
    placeRow(groups.DEF, rowY.DEF);

    if (isFiveBand && groups.MID.length >= 4) {
      // bottom DM band + top AM band
      const dm = groups.MID.slice(0, 2);
      const am = groups.MID.slice(2);
      placeRow(dm, 60);
      placeRow(am, 38);
    } else {
      placeRow(groups.MID, rowY.MID);
    }
    placeRow(groups.FWD, rowY.FWD);
    return positions;
  }

  function render(teamId) {
    const t = findTeam(teamId);
    if (!t) {
      renderEmpty(bodyEl, "Team not found.", "");
      return;
    }

    formationVal.textContent = t.formation || "—";
    scoreVal.textContent = fmtNum(t.score, 2);

    const positions = rolePositions(t.formation, t.players || []);

    const dots = positions.map((p) => {
      const initials = (p.name || "").split(/\s+/).filter(Boolean).slice(-1)[0] || p.name || "?";
      const posLbl = p.position || p.role || "";
      return `<div class="player-dot" style="left:${p.x}%; top:${p.y}%;">
          <div class="ring"></div>
          <div class="name">${escapeHTML(initials)}</div>
          <div class="role">${escapeHTML(posLbl)}</div>
        </div>`;
    }).join("");

    const list = (t.players || []).map((p) =>
      `<tr>
         <td data-label="Role">${posChip(p.position || p.role)}</td>
         <td data-label="Player"><strong>${escapeHTML(p.name || "")}</strong></td>
         <td data-label="ID" class="num small dim">${escapeHTML(String(p.player_id ?? ""))}</td>
       </tr>`
    ).join("");

    const bgUrl = t.flag_code ? `https://flagcdn.com/640x480/${t.flag_code}.png` : null;
    const bgStyle = bgUrl ? `style="background-image:url(${escapeHTML(bgUrl)})"` : "";

    bodyEl.innerHTML = `
      <div class="grid-2">
        <div class="card flag-bg-wrap">
          <div class="flag-bg" ${bgStyle}></div>
          <h3 class="mt-0">${flagHTML(t.flag_code, { size: "lg", alt: t.team_name })}${escapeHTML(t.team_name)} · ${escapeHTML(t.formation || "")}</h3>
          <div class="pitch" aria-label="Formation pitch view">${dots}</div>
        </div>
        <div class="card">
          <h3 class="mt-0">Lineup</h3>
          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr><th>Pos</th><th>Player</th><th class="num">ID</th></tr>
              </thead>
              <tbody>${list}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  }

  selectEl.addEventListener("change", () => render(selectEl.value));
  // initial render: prefer a default well-known team if present, otherwise first
  const defaultId = teams.find((t) => /Argentina|Brazil|France/.test(t.team_name))?.team_id || teams[0].team_id;
  selectEl.value = defaultId;
  render(defaultId);
}
