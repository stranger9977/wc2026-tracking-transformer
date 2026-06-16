// space.js — "Space: Soccer's Dark Matter" landing page.
// Reads the certified metric JSONs + two frame-exact clips. Honors the two copy-guards:
//  (1) no single "#1" — boards render as tie-grouped tiers with overlapping Poisson CIs.
//  (2) soft xT reads are flagged directional and never shown as a goal probability.
// Paths are relative to the document (site root).

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const pad3 = (n) => String(n).padStart(3, "0");
const pct = (x) => `${(x * 100).toFixed(1)}%`;

async function loadJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

// team / position colours
const COL = { CM: "#6cb4ee", DM: "#6cb4ee", CB: "#9b8cff", FB: "#9b8cff", W: "#ff6b6b", CF: "#ff6b6b", GK: "#6dd58c" };
const teamColor = (t) => ({ Argentina: "#6cb4ee", France: "#1a3d8f", Morocco: "#c1272d", Croatia: "#e23b3b", Germany: "#d8d8d8", Spain: "#f0b429", Portugal: "#2e8b57", England: "#dfe7f0", Serbia: "#b0413e", Netherlands: "#e7872b" }[t] || "#9aa6b6");

/* ---------------- reveal-on-scroll ---------------- */
function initReveal() {
  const io = new IntersectionObserver((es) => {
    for (const e of es) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }, { threshold: 0.12 });
  $$(".reveal").forEach((el) => io.observe(el));
}

/* ---------------- confidence rail ---------------- */
function initRail() {
  const fill = $("#rail-fill"), pctEl = $("#rail-pct");
  const states = {
    ignored:   { v: 0.58, t: "58% · off-ball filmed" },
    turn:      { v: 0.58, t: "58% · off-ball filmed" },
    occlusion: { v: 0.591, t: "59% · overall filmed" },
    context:   { v: 0.591, t: "59% · overall filmed" },
  };
  const io = new IntersectionObserver((es) => {
    for (const e of es) if (e.isIntersecting) {
      const s = states[e.target.id]; if (!s) continue;
      fill.style.height = `${(s.v * 100).toFixed(0)}%`;
      pctEl.textContent = s.t;
    }
  }, { threshold: 0.4 });
  ["ignored", "turn", "occlusion", "context"].forEach((id) => { const el = $("#" + id); if (el) io.observe(el); });
}

/* ---------------- tie-band board (copy-guard #1) ---------------- */
function tierChips(rows, countKey, { ciKey } = {}) {
  // group by count value, descending; render each value as an unranked chip row
  const groups = new Map();
  for (const r of rows) {
    const c = r[countKey];
    if (!groups.has(c)) groups.set(c, []);
    groups.get(c).push(r);
  }
  const counts = [...groups.keys()].sort((a, b) => b - a);
  const wrap = document.createElement("div");
  counts.forEach((c, i) => {
    const players = groups.get(c);
    const tier = document.createElement("div");
    tier.className = "tier";
    const tie = players.length > 1 ? `${players.length}-way tie` : "single";
    let ci = "";
    if (ciKey && players[0][ciKey]) ci = ` · 95% CI ${players[0][ciKey][0].toFixed(1)}–${players[0][ciKey][1].toFixed(1)}`;
    else if (players[0].ci_lo != null) ci = ` · 95% CI ${players[0].ci_lo.toFixed(1)}–${players[0].ci_hi.toFixed(1)}`;
    tier.innerHTML = `<div class="tier-lab">${c} ${c === 1 ? "time" : "times"} · ${tie}${ci}</div>`;
    const chips = document.createElement("div"); chips.className = "chips";
    for (const p of players) {
      const ch = document.createElement("span"); ch.className = "chip";
      ch.innerHTML = `<span class="fl" style="background:${teamColor(p.team)}"></span>${p.player} <span class="ct">${p.team}</span>`;
      chips.appendChild(ch);
    }
    tier.appendChild(chips);
    wrap.appendChild(tier);
  });
  return wrap;
}

function bars(rows, { labelKey, valKey, max, fmt = (v) => v, colorKey } = {}) {
  const mx = max ?? Math.max(...rows.map((r) => r[valKey]));
  const wrap = document.createElement("div"); wrap.className = "bars";
  for (const r of rows) {
    const row = document.createElement("div"); row.className = "barrow";
    const col = colorKey ? teamColor(r[colorKey]) : "#6cb4ee";
    row.innerHTML = `<span>${r[labelKey]}</span>
      <span class="track"><span class="fill" style="width:${Math.max(4, (r[valKey] / mx) * 100)}%;background:${col}"></span></span>
      <span class="val">${fmt(r[valKey])}</span>`;
    wrap.appendChild(row);
  }
  return wrap;
}

/* ---------------- embedded clip scrubber (P suppressed) ---------------- */
async function buildClip(el) {
  const label = el.dataset.clip;
  let c;
  try { c = await loadJSON(`data/clips/${label}.json`); }
  catch (e) { el.innerHTML = `<div class="evt">clip unavailable: ${label}</div>`; return; }
  const frames = c.frames || [];
  const n = frames.length;
  const mode = el.dataset.mode;
  const badge = mode === "turn" ? `↑ received facing GOAL` : mode === "ignored" ? `open man · ignored` : "";

  el.innerHTML = `
    <div class="stage">
      <img id="img-${label}" alt="${c.title || label}" />
      <svg class="overlay" viewBox="0 0 105 68" preserveAspectRatio="xMidYMid meet" id="ov-${label}"></svg>
    </div>
    <div class="ctrls">
      <button class="play" id="pl-${label}" aria-label="play">▶</button>
      <input type="range" id="rg-${label}" min="0" max="${Math.max(0, n - 1)}" value="0" />
      <span class="tlabel" id="tl-${label}"></span>
    </div>
    <div class="evt" id="ev-${label}">${badge ? `<b class="hl">${badge}</b> — ` : ""}${c.home_team?.short || ""} v ${c.away_team?.short || ""}</div>`;

  const img = $(`#img-${label}`), rg = $(`#rg-${label}`), pl = $(`#pl-${label}`),
        tl = $(`#tl-${label}`), ev = $(`#ev-${label}`);
  const srcFor = (i) => c.image_pattern.replace("{idx:03d}", pad3(frames[i].frame_idx ?? i));

  // preload
  frames.forEach((_, i) => { const im = new Image(); im.src = srcFor(i); });

  const evts = (c.events_in_window || []).slice().sort((a, b) => a.period_rel_ms - b.period_rel_ms);
  function show(i) {
    i = Math.max(0, Math.min(n - 1, i));
    img.src = srcFor(i);
    rg.value = i;
    const ts = frames[i].timestamp_ms;
    tl.textContent = `${i + 1}/${n} · ${(ts / 1000).toFixed(1)}s`;
    // nearest event at/just before this frame
    let cur = null;
    for (const e of evts) if (e.period_rel_ms <= ts + 250) cur = e; else break;
    let txt = badge ? `<b class="hl">${badge}</b>` : "";
    if (cur) {
      const g = cur.is_goal ? `<b>GOAL</b> — ` : "";
      txt += `${txt ? " · " : ""}${g}${cur.type} <b>${cur.actor_name || ""}</b>`;
    }
    ev.innerHTML = txt || `${c.home_team?.short} v ${c.away_team?.short}`;
  }
  let timer = null, playing = false;
  function stop() { playing = false; pl.textContent = "▶"; if (timer) { clearInterval(timer); timer = null; } }
  function play() {
    if (playing) return stop();
    playing = true; pl.textContent = "❚❚";
    timer = setInterval(() => {
      let i = +rg.value + 1;
      if (i >= n) { i = 0; }
      show(i);
    }, 110);
  }
  pl.addEventListener("click", play);
  rg.addEventListener("input", () => { stop(); show(+rg.value); });
  show(0);
}

/* ---------------- occlusion fog ---------------- */
function initFog(occ) {
  const svg = $("#fog-svg"); if (!svg) return;
  const gpgWrap = occ.gate_bias.by_position_group;
  const gpg = Object.fromEntries((gpgWrap.by_position_group || []).map((r) => [r.position_group, r.visible_keep_rate]));
  const xdist = occ.gate_bias.by_position_x_distance.cells || [];
  const xmap = {}; // group -> [{bin, keep}]
  for (const c of xdist) xmap[c.position_group] = c.cells_by_distance.map((d) => ({ bin: d.dist_bin, keep: d.visible_keep_rate }));
  // distance bins available (use CM's as the canonical ladder)
  const ladder = (xmap.CM || []).map((d) => d.bin);
  const slider = $("#fog-dist"), lab = $("#fog-dist-lab");
  slider.max = ladder.length; slider.value = 0;

  // an attacking 4-3-3 (the population the metric ranks), x↑ toward goal
  const squad = [
    { g: "GK", x: 8, y: 34 },
    { g: "CB", x: 26, y: 24 }, { g: "CB", x: 26, y: 44 },
    { g: "FB", x: 34, y: 8 }, { g: "FB", x: 34, y: 60 },
    { g: "DM", x: 46, y: 34 },
    { g: "CM", x: 58, y: 22 }, { g: "CM", x: 58, y: 46 },
    { g: "W", x: 82, y: 10 }, { g: "W", x: 82, y: 58 },
    { g: "CF", x: 90, y: 34 },
  ];
  function keepAt(g, idx) {
    if (idx === 0) return gpg[g] ?? 0.5;               // "all"
    const arr = xmap[g]; if (!arr) return gpg[g] ?? 0.5;
    return (arr[idx - 1] || arr[arr.length - 1]).keep;
  }
  function draw() {
    const idx = +slider.value;
    lab.textContent = idx === 0 ? "all" : ladder[idx - 1];
    let s = `<rect x="0" y="0" width="105" height="68" fill="#0c2a16"/>
      <rect x="0.6" y="0.6" width="103.8" height="66.8" fill="none" stroke="#2f5a3d" stroke-width="0.4"/>
      <line x1="52.5" y1="0.6" x2="52.5" y2="67.4" stroke="#2f5a3d" stroke-width="0.3"/>
      <circle cx="52.5" cy="34" r="7" fill="none" stroke="#2f5a3d" stroke-width="0.3"/>
      <rect x="88" y="14" width="17" height="40" fill="none" stroke="#2f5a3d" stroke-width="0.3"/>`;
    for (const p of squad) {
      const k = keepAt(p.g, idx);
      const op = Math.max(0.06, k).toFixed(2);
      s += `<g class="pdot"><circle cx="${p.x}" cy="${p.y}" r="2.6" fill="${COL[p.g]}" fill-opacity="${op}" stroke="#04140a" stroke-width="0.3"/>
        <text x="${p.x}" y="${p.y + 0.9}" text-anchor="middle" fill-opacity="${Math.min(1, +op + 0.25)}">${p.g}</text></g>`;
    }
    // ball at center
    s += `<circle cx="52.5" cy="34" r="1.5" fill="#fff"/>`;
    svg.innerHTML = s;
  }
  slider.addEventListener("input", draw);
  draw();

  // keep-rate cards
  const keep = $("#fog-keep");
  const order = ["GK", "CF", "W", "CB", "FB", "DM", "CM"];
  keep.innerHTML = order.filter((g) => gpg[g] != null).map((g) =>
    `<div class="kc"><div class="kv" style="color:${COL[g]}">${(gpg[g] * 100).toFixed(0)}%</div><div class="kl">${g} filmed</div></div>`).join("");
}

/* ---------------- EDA context ---------------- */
function pickList(obj, valCandidates) {
  // find first list-of-objects whose items have a string label + one of the value candidates
  const search = obj.leaderboards || obj;
  for (const k of Object.keys(search)) {
    const v = search[k];
    if (Array.isArray(v) && v.length && typeof v[0] === "object") {
      const valKey = valCandidates.find((c) => typeof v[0][c] === "number");
      const labKey = ["team", "player", "name"].find((c) => typeof v[0][c] === "string");
      if (valKey && labKey) return { rows: v, labKey, valKey, key: k };
    }
  }
  return null;
}

async function buildEDA() {
  // line breaks (known shape)
  try {
    const lb = await loadJSON("data/eda_line_breaks.json");
    const players = (lb.players_by_line_breaking_passes_top20 || []).slice(0, 8);
    if (players.length) $("#eda-lb").replaceWith(Object.assign(bars(players, { labelKey: "player", valKey: "line_breaks", colorKey: "team" }), { id: "eda-lb" }));
  } catch (e) { const el = $("#eda-lb"); if (el) el.innerHTML = ""; }
  // space creation (defensive shape)
  try {
    const sp = await loadJSON("data/eda_space.json");
    const found = pickList(sp, ["createsSpace", "creates_space", "space", "count", "total", "n"]);
    if (found) {
      const teamRows = found.rows.filter((r) => r.team && !r.player).slice(0, 8);
      const rows = (teamRows.length ? teamRows : found.rows).slice(0, 8);
      $("#eda-space").replaceWith(Object.assign(bars(rows, { labelKey: found.labKey, valKey: found.valKey, colorKey: "team" }), { id: "eda-space" }));
    }
  } catch (e) { const el = $("#eda-space"); if (el) el.innerHTML = ""; }
  // pills
  const pills = $("#context-pills");
  if (pills) pills.innerHTML = [
    `<span class="pill"><b>64</b> matches</span>`,
    `<span class="pill"><b>Croatia &amp; Argentina</b> led team space + line-breaks</span>`,
    `<span class="pill">final xG <b>ARG 2.76 · 2.27 FRA</b></span>`,
  ].join("");
}

/* ---------------- boards ---------------- */
async function buildBoards() {
  try {
    const coce = await loadJSON("data/coce.json");
    const ic = coce.leaderboards.ignored_creator_by_times_ignored || [];
    const topTwo = (() => {
      const counts = [...new Set(ic.map((r) => r.times_ignored))].sort((a, b) => b - a).slice(0, 2);
      return ic.filter((r) => counts.includes(r.times_ignored));
    })();
    $("#coce-board").appendChild(tierChips(topTwo, "times_ignored"));
    const teams = (coce.leaderboards.team_ignored_open_men || []).slice(0, 6)
      .map((r) => ({ team: r.team, misses: r.misses, per: r.misses_per_game }));
    const tb = bars(teams, { labelKey: "team", valKey: "misses", colorKey: "team", fmt: (v) => `${v}` });
    $("#coce-teams").appendChild(tb);
  } catch (e) { console.warn("coce board", e); }

  try {
    const turn = await loadJSON("data/turn.json");
    const players = (turn.players_by_turn_receptions || []);
    $("#turn-board").appendChild(tierChips(players, "turn_receptions", { ciKey: "turn_receptions_poisson95_ci" }));
  } catch (e) { console.warn("turn board", e); }
}

/* ---------------- boot ---------------- */
(async function () {
  initReveal();
  await buildBoards();
  await Promise.all($$(".clip[data-clip]").map(buildClip));
  await buildEDA();
})();
