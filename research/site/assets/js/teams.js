import { loadJSON, escapeHTML, fmtInt, renderEmpty, flagHTML, nameWithPos } from "./site.js";

function flagBgUrl(code) {
  if (!code) return null;
  return `https://flagcdn.com/320x240/${code}.png`;
}

const gridEl = document.getElementById("team-grid");
const searchEl = document.getElementById("team-search");
const sortEl = document.getElementById("team-sort");
const pickEl = document.getElementById("team-pick");

const teams = await loadJSON("data/teams.json");
const figIndex = await loadJSON("data/team_figures_index.json");

function normalizeFigPath(p) {
  if (!p) return null;
  // server may store an absolute path like /Users/nick/.../research/site/assets/figures/foo.png
  // strip everything before /assets/ so the site can serve from its root
  const idx = p.indexOf("/assets/");
  if (idx !== -1) return p.slice(idx + 1); // drop leading slash, keep "assets/..."
  // already relative
  return p.replace(/^\.?\//, "");
}

function normalizeMetric(m) {
  if (!m) return null;
  const s = String(m).toLowerCase();
  if (s.startsWith("joi") || s === "offensive" || s === "off") return "offensive";
  if (s.startsWith("jdi") || s === "defensive" || s === "def") return "defensive";
  return s;
}

if (!teams || !Array.isArray(teams) || teams.length === 0) {
  renderEmpty(gridEl, "Teams data not yet computed.",
    "Run the export pipeline to produce data/teams.json.");
} else {
  const figByTeam = new Map();
  if (Array.isArray(figIndex)) {
    for (const f of figIndex) {
      const tid = String(f.team_id);
      const metric = normalizeMetric(f.metric);
      const path = normalizeFigPath(f.out_path || f.path);
      if (!metric || !path) continue;
      if (!figByTeam.has(tid)) figByTeam.set(tid, {});
      figByTeam.get(tid)[metric] = path;
    }
  }

  function pairCount(t) {
    // schema variants: qualifying_pairs OR qualifying_pairs_joi/jdi
    if (t.qualifying_pairs !== undefined) return t.qualifying_pairs;
    return Math.max(t.qualifying_pairs_joi ?? 0, t.qualifying_pairs_jdi ?? 0);
  }

  function render() {
    const q = (searchEl.value || "").toLowerCase().trim();
    const sort = sortEl.value;
    const pickedId = pickEl ? pickEl.value : "";

    let pool;
    if (pickedId) {
      pool = teams.filter((t) => String(t.team_id) === String(pickedId));
    } else {
      pool = teams.filter((t) => !q || (t.team_name || "").toLowerCase().includes(q));
    }

    if (sort === "name") {
      pool.sort((a, b) => (a.team_name || "").localeCompare(b.team_name || ""));
    } else if (sort === "pairs") {
      pool.sort((a, b) => pairCount(b) - pairCount(a));
    } else if (sort === "players") {
      pool.sort((a, b) => (b.players_used || 0) - (a.players_used || 0));
    }

    if (pool.length === 0) {
      renderEmpty(gridEl, "No teams match.", "");
      return;
    }

    // Focused-team view: render in a single-column layout so the maps are bigger.
    gridEl.classList.toggle("focused", !!pickedId);
    gridEl.innerHTML = pool.map((t) => renderCard(t, figByTeam.get(String(t.team_id)) || {})).join("");
  }

  // Populate the focus dropdown alphabetically.
  if (pickEl) {
    const opts = teams.slice().sort((a, b) => (a.team_name || "").localeCompare(b.team_name || ""));
    for (const t of opts) {
      const opt = document.createElement("option");
      opt.value = String(t.team_id);
      opt.textContent = t.team_name;
      pickEl.appendChild(opt);
    }
    pickEl.addEventListener("change", render);
  }

  function renderCard(t, figs) {
    const offPath = figs.offensive || null;
    const defPath = figs.defensive || null;
    const pairs = pairCount(t);
    const bgUrl = flagBgUrl(t.flag_code);
    const bgStyle = bgUrl ? `style="background-image:url(${escapeHTML(bgUrl)})"` : "";

    const figBlock = (label, path, badgeClass) => {
      const downloadName = path ? path.split("/").pop() : "";
      const figHTML = path
        ? `<a href="${escapeHTML(path)}" download="${escapeHTML(downloadName)}">
             <img src="${escapeHTML(path)}" alt="${escapeHTML(label)} chemistry map for ${escapeHTML(t.team_name)}" loading="lazy">
           </a>`
        : `<div class="placeholder">PNG not yet generated</div>`;
      return `<div class="team-fig">
          <div class="fig-label">
            <span><span class="chip ${badgeClass}">${escapeHTML(label)}</span></span>
            ${path ? `<a class="btn small" href="${escapeHTML(path)}" download="${escapeHTML(downloadName)}">PNG</a>` : ""}
          </div>
          ${figHTML}
        </div>`;
    };

    const meta = [];
    if (t.n_matches) meta.push(`${fmtInt(t.n_matches)} matches`);
    if (t.players_used) meta.push(`${fmtInt(t.players_used)} players`);
    if (pairs) meta.push(`${fmtInt(pairs)} pairs`);

    let best = "";
    if (t.best_joi_pair) {
      const bp = t.best_joi_pair;
      best += `<p class="small dim">Top JOI: <strong>${escapeHTML(bp.name_p)}</strong> + <strong>${escapeHTML(bp.name_q)}</strong></p>`;
    }
    if (t.best_jdi_pair) {
      const bp = t.best_jdi_pair;
      best += `<p class="small dim">Top JDI: <strong>${escapeHTML(bp.name_p)}</strong> + <strong>${escapeHTML(bp.name_q)}</strong></p>`;
    }

    return `<article class="team-card flag-bg-wrap">
        <div class="flag-bg" ${bgStyle}></div>
        <h3>
          ${flagHTML(t.flag_code, { size: "lg", alt: t.team_name })}
          ${escapeHTML(t.team_name)}
        </h3>
        <div class="meta">${meta.join(" · ")}</div>
        <div class="team-figs">
          ${figBlock("Offensive (JOI)", offPath, "green")}
          ${figBlock("Defensive (JDI)", defPath, "red")}
        </div>
        ${best}
      </article>`;
  }

  searchEl.addEventListener("input", render);
  sortEl.addEventListener("change", render);
  render();
}
