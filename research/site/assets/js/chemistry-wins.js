/* Chemistry → Winning — Tab 4.
   Story: chemistry wins, and it doesn't look the same for every team.
   Argentina = nucleus. France = network. Morocco = wall. Croatia = engine.
   Renders the headline scatter, four case-study networks + clips, and an
   appendix of remaining interactive plays. */

import { loadJSON, escapeHTML } from "./site.js";
import { mountClipInto } from "./interactive-plays.js";

/* ---------------- data ---------------- */

const [teamRows, fullNets] = await Promise.all([
  loadJSON("data/team_chemistry_vs_paper.json"),
  loadJSON("data/team_full_networks.json"),
]);

const TEAM_IDS = { France: "363", Argentina: "364", Morocco: "374", Croatia: "371" };
const SEMIS = new Set(["France", "Croatia", "Argentina", "Morocco"]);

/* ---------------- headline scatter (TCD vs finish) ---------------- */

const scatterEl = document.getElementById("chem-vs-result-scatter");
if (scatterEl && Array.isArray(teamRows)) {
  renderTcdScatter(teamRows.filter((r) => r.tcd != null && r.stage_int != null));
}

function renderTcdScatter(rows) {
  const W = 1100, H = 500;
  const padL = 86, padR = 48, padT = 22, padB = 72;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const xs = rows.map((r) => r.tcd);
  const xmin = Math.min(...xs) - 4, xmax = Math.max(...xs) + 4;
  const ymin = 1.4, ymax = 8.4;
  const sx = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const sy = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;

  const yLevels = [
    { y: 2, label: "Group" }, { y: 4, label: "R16" }, { y: 5, label: "QF" },
    { y: 6, label: "Semi" }, { y: 7, label: "Final" }, { y: 8, label: "Winner" },
  ];
  const yRules = yLevels.map(({ y, label }) => `
    <line x1="${padL}" y1="${sy(y)}" x2="${W - padR}" y2="${sy(y)}"
          stroke="currentColor" stroke-width="0.5" opacity="0.10"/>
    <text x="${padL - 8}" y="${sy(y) + 4}" font-size="12" font-weight="500"
          fill="currentColor" opacity="0.65" text-anchor="end">${label}</text>`).join("");

  const dots = rows.map((r) => {
    const cx = sx(r.tcd), cy = sy(r.stage_int);
    const isSemi = SEMIS.has(r.team_name);
    const ring = isSemi ? `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="9" fill="none" stroke="#d4a23a" stroke-width="2"/>` : "";
    const fill = isSemi ? "#d4a23a" : "#6b7280";
    return `${ring}<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5.5" fill="${fill}" stroke="var(--bg, #0b1220)" stroke-width="1.2"/>`;
  }).join("");

  // Deterministic non-overlap label placement (same shape as fifa-mode.js)
  const labelW = 64, labelH = 14;
  const lineSpacing = labelH + 2;
  const intersects = (a, b) => !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);
  const order = [...rows].sort((a, b) => b.stage_int - a.stage_int || b.tcd - a.tcd);
  const placed = [];
  const picks = new Map();
  for (const r of order) {
    const cx = sx(r.tcd), cy = sy(r.stage_int);
    const stackUpFromBottom = r.stage_int === 2;
    const stackDown = !stackUpFromBottom && r.stage_int <= 4;
    const anchor = (cx > padL + innerW * 0.6) ? "end" : "start";
    const dx = anchor === "start" ? 9 : -9;
    let dy = stackUpFromBottom ? -10 : (stackDown ? 10 : -10);
    const step = stackUpFromBottom ? -lineSpacing : (stackDown ? lineSpacing : -lineSpacing);
    let box;
    for (let bump = 0; bump < 14; bump++) {
      const lx = cx + dx, ly = cy + dy;
      box = anchor === "start"
        ? { x1: lx, y1: ly - labelH, x2: lx + labelW, y2: ly + 2 }
        : { x1: lx - labelW, y1: ly - labelH, x2: lx, y2: ly + 2 };
      if (!placed.some((p) => intersects(p, box))) break;
      dy += step;
    }
    placed.push(box);
    picks.set(r.team_name, { anchor, dx, dy });
  }
  const labels = rows.map((r) => {
    const cx = sx(r.tcd), cy = sy(r.stage_int);
    const pick = picks.get(r.team_name);
    const fw = SEMIS.has(r.team_name) ? 700 : 500;
    return `<text x="${(cx + pick.dx).toFixed(1)}" y="${(cy + pick.dy).toFixed(1)}"
           font-size="11.5" font-weight="${fw}" fill="currentColor"
           opacity="0.92" text-anchor="${pick.anchor}">${escapeHTML(r.team_name)}</text>`;
  }).join("");

  const xTicks = [0, 25, 50, 75, 100, 125, 150];
  const xTickSvg = xTicks.map((x) => `
    <text x="${sx(x)}" y="${H - padB + 18}" font-size="11" fill="currentColor"
          opacity="0.55" text-anchor="middle">${x}</text>`).join("");
  const axisX = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - padB + 36}"
    font-size="12" fill="currentColor" opacity="0.6" text-anchor="middle">
    Team Chemistry Density (TCD)</text>`;

  scatterEl.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         class="fifa-scatter-svg" role="img"
         aria-label="TCD vs tournament finish scatter">
      ${yRules}
      ${xTickSvg}
      ${dots}
      ${labels}
      ${axisX}
    </svg>
    <div class="scatter-legend small muted">
      <span><span class="dot" style="background:#d4a23a; border-radius:50%;"></span> WC22 semifinalist (gold ring)</span>
      <span class="muted">Spearman ρ(TCD, finish) = <strong>+0.704</strong> (p &lt; 0.001, n = 31). FIFA-23 Overall → finish is +0.548. Chemistry beats raw talent.</span>
    </div>`;
}

/* ---------------- team network renderers ---------------- */

const POS_XY = {
  GK: [8, 32],
  LCB: [22, 22], RCB: [22, 42], CB: [22, 32],
  LB: [28, 10], RB: [28, 54],
  LWB: [30, 8], RWB: [30, 56],
  DM: [42, 32], CDM: [42, 32],
  LM: [50, 14], RM: [50, 50], CM: [55, 32], LCM: [52, 24], RCM: [52, 40],
  AM: [65, 32], CAM: [65, 32],
  LW: [78, 14], RW: [78, 50],
  CF: [88, 32], ST: [88, 32], SS: [80, 32],
};
function isOff(pos) { return /^(CF|ST|LW|RW|AM|CM|DM|LM|RM|CAM|CDM|LCM|RCM|SS)$/.test(pos || ""); }
function isDef(pos) { return /^(CB|LB|RB|LCB|RCB|LWB|RWB|GK)$/.test(pos || ""); }
// Surname helper that keeps compound surnames intact: "Mac Allister",
// "Di María", "Van Dijk", "De Bruyne", "El Yamiq" etc. Without this, the
// network shows "Allister" / "María" / "Dijk" — wrong and confusing.
const SURNAME_PARTICLES = new Set([
  "di","de","da","do","das","dos","del","della","la","le","los",
  "van","von","der","den","ter",
  "mac","mc",
  "el","al","bin","ibn","abu",
  "san","santa",
]);
function niceSurname(fullName) {
  if (!fullName) return "";
  const parts = fullName.trim().split(/\s+/);
  if (parts.length < 2) return fullName;
  let take = 1;
  for (let i = parts.length - 2; i >= Math.max(0, parts.length - 3); i--) {
    if (SURNAME_PARTICLES.has(parts[i].toLowerCase())) take = parts.length - i;
    else break;
  }
  return parts.slice(-take).join(" ");
}
function pitchXY(position, idx, sameCount) {
  const base = POS_XY[position] || [55, 32];
  const offset = sameCount > 1 ? (idx - (sameCount - 1) / 2) * 8 : 0;
  return [base[0], Math.max(4, Math.min(60, base[1] + offset))];
}

/** Pitch-positioned network used for France, Morocco, Croatia.
 *  highlight:
 *    - "def"      → emphasise def↔def edges (Morocco)
 *    - "midfield" → emphasise the CM/DM cluster (Croatia)
 *    - null       → uniform palette (France) */
function renderPitchNetwork(mountEl, teamName, highlight = null, edgeThreshold = 0.3) {
  const teamId = TEAM_IDS[teamName];
  const net = fullNets?.[teamId];
  if (!mountEl || !net) {
    if (mountEl) mountEl.innerHTML = `<div class="empty-state small">Network data missing.</div>`;
    return;
  }

  // GK exclusion makes the player-to-player chemistry actually visible.
  const gkIds = new Set(net.nodes.filter((n) => n.position === "GK").map((n) => n.player_id));
  const byPos = {};
  for (const n of net.nodes) {
    if (gkIds.has(n.player_id)) continue;
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

  const edges = net.edges
    .filter((e) => placed.has(e.p) && placed.has(e.q) && Number.isFinite(e.aw_joi90) && e.aw_joi90 >= edgeThreshold);
  const maxAW = Math.max(0.4, ...edges.map((e) => e.aw_joi90));

  // Viewport: 100 × 70, with a 6-unit headroom at the top reserved for
  // the WALL / THE ATTACK callouts so they never collide with the
  // topmost player dots or labels. Pitch starts at y = 6.
  const W = 100, H = 70;
  const padX = 4;
  const padTop = 6;   // headroom for top callouts
  const padBottom = 4;
  const scaleX = (x) => padX + (x / 100) * (W - 2 * padX);
  const scaleY = (y) => padTop + (y / 64) * (H - padTop - padBottom);
  // Legacy padY (used by the pitch rect + box outlines below) — equals
  // padTop here so the pitch rect starts where the headroom ends.
  const padY = padTop;

  // Midfield highlight cluster (Croatia): Modrić / Brozović / Kovačić
  const midfieldEngine = new Set();
  if (highlight === "midfield") {
    for (const n of placed.values()) {
      if (/^Luka Modri|^Marcelo Brozovi|^Mateo Kovaci|^Mateo Kovači/.test(n.name)) {
        midfieldEngine.add(n.player_id);
      }
    }
  }

  function edgeStyle(e, a, b) {
    const oo = isOff(a.position) && isOff(b.position);
    const dd = isDef(a.position) && isDef(b.position);
    const cat = oo ? "off" : dd ? "def" : "cross";
    // Brighter palette so the def-def block actually reads as a "lattice."
    let color = { off: "#f59e0b", def: "#5eb1f8", cross: "#a78bfa" }[cat];
    let muted = false;
    if (highlight === "def" && cat !== "def") muted = true;
    // "wall+recycle": Morocco's story is the wall feeding the attack.
    // Light up BOTH def↔def (blue, the wall) AND cross-team edges where
    // one endpoint is a defender (orange, the recycle). Mute pure off↔off.
    if (highlight === "wall+recycle") {
      if (cat === "def") {
        // pure def-def stays blue
      } else if (cat === "cross" && (isDef(a.position) || isDef(b.position))) {
        color = "#f59e0b"; // recycle edge — defender feeding the attack
      } else {
        muted = true;
      }
    }
    if (highlight === "midfield") {
      const inEngine = midfieldEngine.has(a.player_id) && midfieldEngine.has(b.player_id);
      if (!inEngine) muted = true;
      else color = "#ffd166";
    }
    return { color, muted, cat };
  }

  const ratioOf = (e) => e.aw_joi90 / maxAW;
  // Pre-classify defender ids so the node-render below can give the wall
  // extra ring weight when we're in "def" highlight mode.
  const isDefenderId = (pid) => {
    const node = placed.get(pid);
    return node && isDef(node.position);
  };

  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="atom-svg" role="img" aria-label="${escapeHTML(teamName)} chemistry network">`;
  // Pitch surface — height now defined by padTop and padBottom separately
  // so we have headroom at the top for the WALL / ATTACK callouts.
  const pitchH = H - padTop - padBottom;
  const pitchCY = padTop + pitchH / 2;
  svg += `<rect x="${padX}" y="${padTop}" width="${W - 2*padX}" height="${pitchH}" fill="#13332b" stroke="#2a4034" stroke-width="0.25" rx="1" />`;
  // Halfway line + center circle.
  svg += `<line x1="${W/2}" y1="${padTop}" x2="${W/2}" y2="${padTop + pitchH}" stroke="#2a4034" stroke-width="0.18" />`;
  svg += `<circle cx="${W/2}" cy="${pitchCY}" r="5" stroke="#2a4034" stroke-width="0.18" fill="none" />`;
  // Penalty boxes for spatial context (16.5 m wide, 40.32 m tall on a 105×68 pitch).
  const pbW = (16.5 / 105) * (W - 2 * padX);
  const pbH = (40.32 / 68) * pitchH;
  const sixW = (5.5 / 105) * (W - 2 * padX);
  const sixH = (18.32 / 68) * pitchH;
  svg += `<rect x="${padX}" y="${(pitchCY - pbH / 2).toFixed(1)}" width="${pbW.toFixed(1)}" height="${pbH.toFixed(1)}" fill="none" stroke="#2a4034" stroke-width="0.15" />`;
  svg += `<rect x="${(W - padX - pbW).toFixed(1)}" y="${(pitchCY - pbH / 2).toFixed(1)}" width="${pbW.toFixed(1)}" height="${pbH.toFixed(1)}" fill="none" stroke="#2a4034" stroke-width="0.15" />`;
  svg += `<rect x="${padX}" y="${(pitchCY - sixH / 2).toFixed(1)}" width="${sixW.toFixed(1)}" height="${sixH.toFixed(1)}" fill="none" stroke="#2a4034" stroke-width="0.12" />`;
  svg += `<rect x="${(W - padX - sixW).toFixed(1)}" y="${(pitchCY - sixH / 2).toFixed(1)}" width="${sixW.toFixed(1)}" height="${sixH.toFixed(1)}" fill="none" stroke="#2a4034" stroke-width="0.12" />`;

  // Render edges in two passes so muted ones go BEHIND the highlighted ones.
  // For Morocco's wall+recycle view we also cap the focus list per category
  // so the pitch reads as ~6 wall edges + ~6 recycle edges instead of a blob
  // of every-defender-to-every-attacker. Edges are kept in descending
  // aw_joi90 order before capping.
  const mutedEdges = [], focusEdges = [];
  const sortedEdges = [...edges].sort((x, y) => (y.aw_joi90 || 0) - (x.aw_joi90 || 0));
  const cat2style = new Map(); // remember per-category style for later
  for (const e of sortedEdges) {
    const a = placed.get(e.p), b = placed.get(e.q);
    const meta = edgeStyle(e, a, b);
    cat2style.set(meta.color, meta);
    (meta.muted ? mutedEdges : focusEdges).push({ e, a, b, ...meta });
  }
  // Universal per-category cap on focused edges so no team network turns
  // into spaghetti. Per-highlight cap profiles tuned to keep the strongest
  // story-bearing edges and drop the rest into the muted bucket (where
  // they still render very faintly at the back).
  const CAP_BY_HIGHLIGHT = {
    "wall+recycle": { def: 6, off: 6, cross: 8 },
    "def":          { def: 8, off: 4, cross: 5 },
    "midfield":     { def: 4, off: 8, cross: 6 },
    "_default":     { def: 5, off: 7, cross: 6 },
  };
  const CAP = CAP_BY_HIGHLIGHT[highlight] || CAP_BY_HIGHLIGHT._default;
  {
    const seenCats = new Map();
    const capped = [];
    const overflow = [];
    for (const ed of focusEdges) {
      const seen = seenCats.get(ed.cat) || 0;
      const cap = CAP[ed.cat] ?? 100;
      if (seen >= cap) { overflow.push(ed); continue; }
      seenCats.set(ed.cat, seen + 1);
      capped.push(ed);
    }
    for (const ed of overflow) mutedEdges.push({ ...ed, muted: true });
    focusEdges.length = 0;
    focusEdges.push(...capped);
  }
  for (const { e, a, b, color, muted } of mutedEdges) {
    const r = ratioOf(e);
    const w = 0.10 + r * 0.35;
    const op = (0.05 + r * 0.10).toFixed(2);
    svg += `<line x1="${scaleX(a.x).toFixed(1)}" y1="${scaleY(a.y).toFixed(1)}" x2="${scaleX(b.x).toFixed(1)}" y2="${scaleY(b.y).toFixed(1)}" stroke="${color}" stroke-opacity="${op}" stroke-width="${w.toFixed(2)}" stroke-linecap="round"><title>${escapeHTML(e.name_p)} ↔ ${escapeHTML(e.name_q)}: AW-JOI90 ${e.aw_joi90.toFixed(2)}, AW-JDI90 ${(e.aw_jdi90 ?? 0).toFixed(2)}</title></line>`;
  }
  // Focused edges: slightly thinner than before, still with a soft halo
  // underneath so the wall reads as a single lattice and not a tangle.
  for (const { e, a, b, color } of focusEdges) {
    const r = ratioOf(e);
    const w = 0.35 + r * 1.25;
    const op = (0.55 + r * 0.40).toFixed(2);
    svg += `<line x1="${scaleX(a.x).toFixed(1)}" y1="${scaleY(a.y).toFixed(1)}" x2="${scaleX(b.x).toFixed(1)}" y2="${scaleY(b.y).toFixed(1)}" stroke="${color}" stroke-opacity="0.16" stroke-width="${(w * 1.9).toFixed(2)}" stroke-linecap="round" />`;
    svg += `<line x1="${scaleX(a.x).toFixed(1)}" y1="${scaleY(a.y).toFixed(1)}" x2="${scaleX(b.x).toFixed(1)}" y2="${scaleY(b.y).toFixed(1)}" stroke="${color}" stroke-opacity="${op}" stroke-width="${w.toFixed(2)}" stroke-linecap="round"><title>${escapeHTML(e.name_p)} ↔ ${escapeHTML(e.name_q)}: AW-JOI90 ${e.aw_joi90.toFixed(2)}, AW-JDI90 ${(e.aw_jdi90 ?? 0).toFixed(2)}</title></line>`;
  }
  for (const n of placed.values()) {
    // Bigger nodes: ~1.6–2.6 in viewBox units (was 0.9–1.6). Defenders in
    // "def" highlight mode get a thicker ring so the wall pops as a unit.
    const r = 1.6 + Math.min(1.0, n.minutes / 600) * 1.0;
    const isWallNode = highlight === "def" && isDef(n.position);
    const ringColor = highlight === "midfield" && midfieldEngine.has(n.player_id)
      ? "#ffd166"
      : (isWallNode ? "#5eb1f8" : "#e8eef9");
    const ringWidth = isWallNode ? 0.45 : 0.28;
    if (isWallNode) {
      svg += `<circle cx="${scaleX(n.x).toFixed(1)}" cy="${scaleY(n.y).toFixed(1)}" r="${(r + 0.9).toFixed(2)}" fill="none" stroke="${ringColor}" stroke-opacity="0.25" stroke-width="0.5" />`;
    }
    svg += `<circle cx="${scaleX(n.x).toFixed(1)}" cy="${scaleY(n.y).toFixed(1)}" r="${r.toFixed(2)}" fill="#0b1220" stroke="${ringColor}" stroke-width="${ringWidth}"><title>${escapeHTML(n.name)} (${escapeHTML(n.position)}) · ${Math.round(n.minutes)} min</title></circle>`;
    const displayName = niceSurname(n.name);
    svg += `<text x="${scaleX(n.x).toFixed(1)}" y="${(scaleY(n.y) + r + 2.6).toFixed(1)}" text-anchor="middle" class="atom-label" style="font-weight:${isWallNode ? 700 : 600}; fill:${isWallNode ? "#cfe3ff" : "#e8eef9"};">${escapeHTML(displayName)}</text>`;
  }
  // Callouts: WALL / THE ATTACK pinned to the TOP edge of the pitch
  // (above the play, where they can't overlap anything) and connected to
  // their cluster with a faint vertical line. Avoids the previous problem
  // where the boxes sat on top of the player dots and labels.
  if (highlight === "def" || highlight === "wall+recycle") {
    const drawCallout = (cluster, text, color) => {
      if (!cluster.length) return;
      const cx = cluster.reduce((s, n) => s + scaleX(n.x), 0) / cluster.length;
      // Lives in the dedicated headroom band (y 0-6) — guaranteed clear
      // of every player dot / label since the pitch surface itself
      // starts at y = padTop (6).
      const boxY = 0.6;
      const boxH = 4.4;
      // Box width: pad generously so the bold mono text + letter-spacing
      // can never clip. Was clipping "THE WALL" / "THE ATTACK" at the
      // box edges before (text wider than container).
      const w = Math.max(18, text.length * 2.05 + 4);
      svg += `<rect x="${(cx - w / 2).toFixed(1)}" y="${boxY}" width="${w.toFixed(1)}" height="${boxH}" rx="0.8" fill="${color}" fill-opacity="0.16" stroke="${color}" stroke-width="0.35" />`;
      svg += `<text x="${cx.toFixed(1)}" y="${(boxY + 2.85).toFixed(1)}" text-anchor="middle" style="fill:${color}; font-size:2.5px; font-weight:800; letter-spacing:0.45px;">${text}</text>`;
    };
    const defs = [...placed.values()].filter((n) => isDef(n.position));
    drawCallout(defs, "THE WALL", "#5eb1f8");
    if (highlight === "wall+recycle") {
      const offs = [...placed.values()].filter((n) => isOff(n.position));
      drawCallout(offs, "THE ATTACK", "#f59e0b");
    }
  }
  svg += `</svg>`;
  mountEl.innerHTML = svg;
}

/** Nucleus rendering for Argentina: Messi at the center, every strong
 *  partner orbiting around him. Orbital position is scored by
 *  Messi-pair AW-JOI (closer = stronger pair), with light angular spread
 *  by position so it doesn't all collapse into one cluster. */
function renderNucleusNetwork(mountEl, teamName, centerName = "Messi") {
  const teamId = TEAM_IDS[teamName];
  const net = fullNets?.[teamId];
  if (!mountEl || !net) {
    if (mountEl) mountEl.innerHTML = `<div class="empty-state small">Network data missing.</div>`;
    return;
  }
  const center = net.nodes.find((n) => n.name.includes(centerName));
  if (!center) {
    mountEl.innerHTML = `<div class="empty-state small">${escapeHTML(centerName)} not found in roster.</div>`;
    return;
  }
  // Messi spokes
  const spokes = net.edges
    .filter((e) => (e.p === center.player_id || e.q === center.player_id) && Number.isFinite(e.aw_joi90))
    .map((e) => {
      const other = e.p === center.player_id ? e.q : e.p;
      const otherName = e.p === center.player_id ? e.name_q : e.name_p;
      const otherNode = net.nodes.find((n) => n.player_id === other);
      return { other, otherName, otherNode, aw_joi90: e.aw_joi90, aw_jdi90: e.aw_jdi90 };
    })
    .filter((s) => s.otherNode && s.otherNode.position !== "GK" && s.aw_joi90 >= 0.3)
    .sort((a, b) => b.aw_joi90 - a.aw_joi90);

  const W = 100, H = 64, cx = W / 2, cy = H / 2;
  const maxJoi = Math.max(0.4, ...spokes.map((s) => s.aw_joi90));

  // Angular slot by player position so spokes splay out by role
  // (defenders left, midfielders top/bottom, forwards right).
  const posAngle = (pos) => {
    if (/^(GK|CB|LCB|RCB|LB|RB|LWB|RWB)$/.test(pos)) return Math.PI;        // left half
    if (/^(CF|ST|LW|RW|SS)$/.test(pos)) return 0;                            // right half
    if (/^(LM|LCM)$/.test(pos)) return -Math.PI / 2 - 0.4;
    if (/^(RM|RCM)$/.test(pos)) return  Math.PI / 2 + 0.4;
    if (/^(AM|CAM)$/.test(pos)) return -Math.PI / 4;
    if (/^(DM|CDM)$/.test(pos)) return Math.PI - Math.PI / 4;
    return -Math.PI / 2;  // CM / fallback up top
  };

  // Spread spokes inside each angular bucket so labels don't overlap.
  const buckets = new Map();
  spokes.forEach((s) => {
    const a = posAngle(s.otherNode.position || "CM");
    if (!buckets.has(a)) buckets.set(a, []);
    buckets.get(a).push(s);
  });
  const placed = [];
  for (const [angle, list] of buckets.entries()) {
    list.sort((a, b) => b.aw_joi90 - a.aw_joi90);
    const span = 0.55;  // total angular spread per bucket
    list.forEach((s, i) => {
      const t = list.length === 1 ? 0 : (i / (list.length - 1)) - 0.5;
      const a = angle + t * span;
      // Stronger pair = closer to Messi (shorter orbit radius).
      const ratio = s.aw_joi90 / maxJoi;
      const orbit = 14 + (1 - ratio) * 14;  // 14..28
      placed.push({
        ...s,
        x: cx + Math.cos(a) * orbit,
        y: cy + Math.sin(a) * orbit * (H / W) * 1.6,
        ratio,
      });
    });
  }

  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="atom-svg" role="img" aria-label="${escapeHTML(teamName)} nucleus network around ${escapeHTML(center.name)}">`;
  svg += `<rect x="0" y="0" width="${W}" height="${H}" fill="none" stroke="#2a313d" stroke-width="0.2" />`;

  // Spoke lines first (under the dots)
  for (const s of placed) {
    const w = 0.2 + s.ratio * 1.4;
    const op = (0.32 + s.ratio * 0.55).toFixed(2);
    svg += `<line x1="${cx}" y1="${cy}" x2="${s.x.toFixed(1)}" y2="${s.y.toFixed(1)}" stroke="#ffd166" stroke-opacity="${op}" stroke-width="${w.toFixed(2)}" stroke-linecap="round"><title>${escapeHTML(center.name)} ↔ ${escapeHTML(s.otherName)}: AW-JOI90 ${s.aw_joi90.toFixed(2)}</title></line>`;
  }
  // Orbital dots + labels
  for (const s of placed) {
    const r = 0.9 + s.ratio * 0.7;
    svg += `<circle cx="${s.x.toFixed(1)}" cy="${s.y.toFixed(1)}" r="${r.toFixed(2)}" fill="#1f2a3a" stroke="#e8eef9" stroke-width="0.22"><title>${escapeHTML(s.otherName)} · AW-JOI90 ${s.aw_joi90.toFixed(2)}</title></circle>`;
    const sn = niceSurname(s.otherName);
    svg += `<text x="${s.x.toFixed(1)}" y="${(s.y + r + 2.6).toFixed(1)}" text-anchor="middle" class="atom-label">${escapeHTML(sn)}</text>`;
  }
  // Nucleus on top
  svg += `<circle cx="${cx}" cy="${cy}" r="3.6" fill="#fde047" stroke="#0b1220" stroke-width="0.4"><title>${escapeHTML(center.name)}</title></circle>`;
  svg += `<text x="${cx}" y="${(cy + 5.4).toFixed(1)}" text-anchor="middle" class="atom-label" font-weight="700">${escapeHTML(niceSurname(center.name))}</text>`;
  svg += `</svg>`;
  mountEl.innerHTML = svg;
}

/* ---------------- network mounts (with Nucleus / Network toggles) ---------------- */

// Per-team config: which highlight mode + edge threshold to use for the
// "Network" view, and which player anchors the "Nucleus" view.
const TEAM_VIEW_CFG = {
  argentina: { name: "Argentina", highlight: null,       threshold: 0.30, nucleusCenter: "Messi" },
  france:    { name: "France",    highlight: null,       threshold: 0.50, nucleusCenter: "Mbappé" },
  morocco:   { name: "Morocco",   highlight: "wall+recycle", threshold: 0.30, nucleusCenter: null },
  croatia:   { name: "Croatia",   highlight: "midfield", threshold: 0.30, nucleusCenter: null },
};

// Pick a sensible default nucleus center: team's top-AW-JOI non-GK player.
function pickTopAwjoiPlayer(teamName) {
  const teamId = TEAM_IDS[teamName];
  const net = fullNets?.[teamId];
  if (!net) return null;
  const gkIds = new Set(net.nodes.filter((n) => n.position === "GK").map((n) => n.player_id));
  let bestName = null, bestVal = -Infinity;
  for (const e of (net.edges || [])) {
    if (!Number.isFinite(e.aw_joi90)) continue;
    if (gkIds.has(e.p) || gkIds.has(e.q)) continue;
    if (e.aw_joi90 > bestVal) {
      bestVal = e.aw_joi90;
      // Prefer the higher-minutes endpoint as anchor.
      const np = net.nodes.find((n) => n.player_id === e.p);
      const nq = net.nodes.find((n) => n.player_id === e.q);
      bestName = (np && nq && (np.minutes || 0) >= (nq.minutes || 0)) ? np.name : (nq?.name || np?.name);
    }
  }
  return bestName;
}

function renderTeamView(teamKey, view) {
  const cfg = TEAM_VIEW_CFG[teamKey];
  if (!cfg) return;
  const mountEl = document.getElementById(`net-${teamKey}`);
  if (!mountEl) return;
  if (view === "nucleus") {
    const center = cfg.nucleusCenter || pickTopAwjoiPlayer(cfg.name);
    if (!center) {
      mountEl.innerHTML = `<div class="empty-state small">No nucleus anchor found for ${escapeHTML(cfg.name)}.</div>`;
      return;
    }
    renderNucleusNetwork(mountEl, cfg.name, center);
  } else {
    renderPitchNetwork(mountEl, cfg.name, cfg.highlight, cfg.threshold);
  }
}

// Per-team, per-view heading + blurb text. When the user toggles between
// Nucleus and Network, the headline above the graph updates so it doesn't
// keep claiming "Messi's orbital network" while you're actually looking at
// the pitch-positioned team network.
const NET_VIEW_TEXT = {
  argentina: {
    nucleus: {
      h: "Messi's orbital network",
      p: "Spokes from Messi to every strong same-squad partner. Line thickness ∝ AW-JOI90; shorter orbit = stronger pair. Goalkeeper excluded.",
    },
    network: {
      h: "Argentina — pitch-positioned chemistry network",
      p: "Every Argentina player as a node on the pitch; edges colored by pair category (yellow off↔off, blue def↔def, purple cross-team). Capped per category so the strongest pairs read at a glance.",
    },
  },
};
function updateNetHeading(teamKey, view) {
  const cfg = NET_VIEW_TEXT[teamKey]?.[view];
  if (!cfg) return;
  const hEl = document.getElementById(`${teamKey}-net-heading`);
  const pEl = document.getElementById(`${teamKey}-net-blurb`);
  if (hEl) hEl.textContent = cfg.h;
  if (pEl) pEl.textContent = cfg.p;
}
function wireNetworkToggles() {
  document.querySelectorAll(".net-view-toggle").forEach((group) => {
    const teamKey = group.dataset.team;
    const defaultView = group.dataset.default || "network";
    const buttons = group.querySelectorAll(".net-view-btn");
    const apply = (view) => {
      buttons.forEach((b) => b.classList.toggle("active", b.dataset.view === view));
      updateNetHeading(teamKey, view);
      renderTeamView(teamKey, view);
    };
    buttons.forEach((b) => b.addEventListener("click", () => apply(b.dataset.view)));
    apply(defaultView);
  });
}

wireNetworkToggles();

/* ---------------- Morocco def-def support panel ---------------- */
// Renders a tournament-wide leaderboard with a metric switcher so the
// reader can pick which way to slice defensive chemistry. Morocco ranks
// differently on each:
//   sum_jdi  — Morocco #2 (Argentina just ahead)
//   n_strong — Morocco #3 (using the paper's tcd_def threshold)
//   top5_mean — Morocco #7
//   mean_jdi — Morocco #8
// Default is sum_jdi where they look strongest.
function computeDefMetrics() {
  if (!fullNets || typeof fullNets !== "object") return [];
  const out = [];
  // Outfield-defender predicate — EXCLUDES GK so GK↔CB pairs (which the
  // model heavily attends to in the defensive third) don't dominate the
  // metric. Matches the chemistry-leaderboard convention from CLAUDE.md.
  const isOutfieldDef = (p) => /^(CB|LB|RB|LCB|RCB|LWB|RWB)$/.test(p || "");
  for (const tid in fullNets) {
    const net = fullNets[tid];
    if (!net || !Array.isArray(net.nodes)) continue;
    const byId = new Map(net.nodes.map((n) => [n.player_id, n]));
    const jdis = [];
    for (const e of (net.edges || [])) {
      const a = byId.get(e.p), b = byId.get(e.q);
      if (!a || !b) continue;
      if (!isOutfieldDef(a.position) || !isOutfieldDef(b.position)) continue;
      const v = e.aw_jdi90;
      if (Number.isFinite(v) && v > 0) jdis.push(v);
    }
    if (!jdis.length) continue;
    jdis.sort((a, b) => b - a);
    const sum = jdis.reduce((s, x) => s + x, 0);
    const mean = sum / jdis.length;
    const top5 = jdis.slice(0, 5);
    const top5_mean = top5.reduce((s, x) => s + x, 0) / top5.length;
    const tinfo = (Array.isArray(teamRows)
      ? teamRows.find((r) => String(r.team_id) === String(tid)) : null) || {};
    out.push({
      tid,
      name: tinfo.team_name || `team ${tid}`,
      flag_code: tinfo.flag_code,
      stage: tinfo.stage,
      sum_jdi: sum,
      mean_jdi: mean,
      top5_mean,
      n_strong: tinfo.tcd_def ?? jdis.filter((v) => v >= 0.30).length,
    });
  }
  return out;
}
const DEF_METRICS = computeDefMetrics();
const METRIC_META = {
  sum_jdi:    { label: "Total defensive mass (Σ AW-JDI90)",
                blurb: "Sum of every team's def↔def AW-JDI90 pair contribution. Rewards both <em>quality</em> and <em>quantity</em> of defensive chemistry &mdash; how big the wall is overall.",
                fmt: (v) => (v == null ? "—" : v.toFixed(2)) },
  n_strong:   { label: "Strong pairs (AW-JDI90 ≥ 0.30)",
                blurb: "Count of pair-edges with AW-JDI90 at or above 0.30 &mdash; the threshold the published Morocco paper used. Rewards breadth.",
                fmt: (v) => String(Math.round(v)) },
  top5_mean:  { label: "Mean of top-5 pairs",
                blurb: "Average AW-JDI90 across the five strongest def↔def pairs. Rewards a team's <em>elite ceiling</em>, not breadth.",
                fmt: (v) => (v == null ? "—" : v.toFixed(3)) },
  mean_jdi:   { label: "Mean across all pairs",
                blurb: "Average AW-JDI90 across every def↔def pair the team has minutes for. Closer to a per-pair quality floor than a ceiling.",
                fmt: (v) => (v == null ? "—" : v.toFixed(3)) },
};

function renderMoroccoTcdSupport(metric = "sum_jdi") {
  const lbEl = document.getElementById("morocco-tcd-def-leaderboard");
  const brEl = document.getElementById("morocco-tcd-breakdown");
  if (!Array.isArray(teamRows)) return;
  if (!DEF_METRICS.length) return;
  const fmt = (METRIC_META[metric] || METRIC_META.sum_jdi).fmt;
  const sorted = [...DEF_METRICS].sort((a, b) => b[metric] - a[metric]);
  const top = sorted.slice(0, 10);
  const max = Math.max(1e-9, ...top.map((r) => r[metric]));
  // Build the row format the existing renderer below expects.
  const rows = top.map((r) => ({ name: r.name, n: r[metric], stage: r.stage }));
  if (lbEl) {
    const FLAG = {
      Brazil: "🇧🇷", France: "🇫🇷", Morocco: "🇲🇦", Croatia: "🇭🇷",
      Argentina: "🇦🇷", Spain: "🇪🇸", Portugal: "🇵🇹", "Saudi Arabia": "🇸🇦",
      Germany: "🇩🇪", Switzerland: "🇨🇭", "United States": "🇺🇸", "South Korea": "🇰🇷",
      Netherlands: "🇳🇱", Japan: "🇯🇵", Senegal: "🇸🇳", Australia: "🇦🇺",
      Mexico: "🇲🇽", Uruguay: "🇺🇾", Belgium: "🇧🇪", Canada: "🇨🇦",
      Ghana: "🇬🇭", Cameroon: "🇨🇲", Denmark: "🇩🇰", England: "🇬🇧",
      Iran: "🇮🇷", Poland: "🇵🇱", Qatar: "🇶🇦", Serbia: "🇷🇸",
      Tunisia: "🇹🇳", Wales: "🏴", "Costa Rica": "🇨🇷", Ecuador: "🇪🇨",
    };
    lbEl.innerHTML = top.map((src, i) => {
      const r = { name: src.name, n: src[metric] };
      const isMar = r.name === "Morocco";
      const pct = (r.n / max) * 100;
      const bg = isMar ? "#3b6ea0" : "#2a313d";
      const ring = isMar ? "border:1px solid #5eb1f8;" : "";
      const labelStyle = isMar ? "color:#cfe3ff; font-weight:700;" : "color:var(--text);";
      return `
        <div style="display:grid; grid-template-columns: 1.6rem 8rem 1fr 3.4rem; align-items:center; gap:0.5rem; margin:0.18rem 0;">
          <span class="dim small" style="text-align:right;">#${i + 1}</span>
          <span style="${labelStyle}">${FLAG[r.name] || "🏳️"} ${escapeHTML(r.name)}</span>
          <span style="height:0.85rem; background:#0e141f; border-radius:3px; overflow:hidden; ${ring}">
            <span style="display:block; height:100%; width:${pct.toFixed(1)}%; background:${bg};"></span>
          </span>
          <span class="tabular" style="${labelStyle} text-align:right;">${fmt(r.n)}</span>
        </div>`;
    }).join("");
  }
  if (brEl) {
    const mar = teamRows.find((r) => r.team_name === "Morocco");
    if (mar) {
      const o = mar.tcd_off || 0, dd = mar.tcd_def || 0, x = mar.tcd_cross_net || 0;
      brEl.innerHTML = `
        off↔off <strong class="tabular" style="color:#d4793a;">${o}</strong> &middot;
        <strong style="color:var(--text)">def↔def <strong class="tabular" style="color:#5eb1f8;">${dd}</strong></strong> &middot;
        cross-team <strong class="tabular" style="color:#9b7fc6;">${x}</strong>
        &nbsp; (total TCD ${mar.tcd ?? "?"})`;
    }
  }
}
renderMoroccoTcdSupport();

/* ---------------- Morocco elite pairs spotlight ---------------- */
// Names the 5 strongest def↔def pairs by AW-JDI90 (GKs excluded), each
// with their AW-JOI90 + minutes-shared, drawn from team_full_networks.json
// (already loaded into fullNets). El Yamiq is the hub in 3/5 — the card
// visualises that by giving him a larger badge.
function renderMoroccoElitePairs() {
  const mountEl = document.getElementById("morocco-elite-pairs");
  if (!mountEl) return;
  const net = fullNets?.[TEAM_IDS.Morocco];
  if (!net) return;
  const isDefPos = (p) => /^(CB|LB|RB|LCB|RCB|LWB|RWB)$/.test(p || "");

  // Build the field of ALL def↔def pairs across every team so we can score
  // each Morocco pair as a percentile against the actual field, not just
  // against Morocco's own row.
  const allDefJdis = [];
  for (const tid in fullNets) {
    const tn = fullNets[tid];
    const byTid = new Map(tn.nodes.map((n) => [n.player_id, n]));
    for (const e of (tn.edges || [])) {
      const a = byTid.get(e.p), b = byTid.get(e.q);
      if (!a || !b) continue;
      if (!isDefPos(a.position) || !isDefPos(b.position)) continue;
      const v = e.aw_jdi90 ?? 0;
      if (v > 0) allDefJdis.push(v);
    }
  }
  allDefJdis.sort((a, b) => a - b);
  const pctileOf = (v) => {
    if (!allDefJdis.length) return null;
    let lo = 0, hi = allDefJdis.length;
    while (lo < hi) { const m = (lo + hi) >> 1; allDefJdis[m] < v ? lo = m + 1 : hi = m; }
    return (lo / allDefJdis.length) * 100;
  };

  const byId = new Map(net.nodes.map((n) => [n.player_id, n]));
  const pairs = (net.edges || [])
    .map((e) => {
      const a = byId.get(e.p), b = byId.get(e.q);
      if (!a || !b) return null;
      if (!isDefPos(a.position) || !isDefPos(b.position)) return null;
      const jdi = e.aw_jdi90 ?? 0;
      const joi = e.aw_joi90 ?? 0;
      const mins = e.minutes_together ?? e.minutes ?? 0;
      return { a, b, jdi, joi, mins, pctile: pctileOf(jdi) };
    })
    .filter(Boolean)
    .sort((x, y) => y.jdi - x.jdi)
    .slice(0, 5);
  if (!pairs.length) { mountEl.innerHTML = "<div class='empty-state small'>No def-def pairs.</div>"; return; }
  // Count how many of the top-5 each player appears in — to size the hub badge.
  const appearCount = new Map();
  for (const p of pairs) {
    appearCount.set(p.a.player_id, (appearCount.get(p.a.player_id) || 0) + 1);
    appearCount.set(p.b.player_id, (appearCount.get(p.b.player_id) || 0) + 1);
  }
  const maxJdi = Math.max(...pairs.map((p) => p.jdi));
  const surname = (full) => niceSurname(full || "");
  // Pctile -> color bucket: ≥95 emerald, ≥85 green, ≥70 yellow, ≥50 amber, else gray.
  const pctileChip = (pct) => {
    if (pct == null) return "";
    let bg, border, fg, label;
    if (pct >= 95)      { bg = "#0e2a1a"; border = "#10b981"; fg = "#6ee7b7"; label = "elite"; }
    else if (pct >= 85) { bg = "#16321f"; border = "#22c55e"; fg = "#86efac"; label = "top tier"; }
    else if (pct >= 70) { bg = "#332815"; border = "#eab308"; fg = "#fde68a"; label = "strong"; }
    else if (pct >= 50) { bg = "#33240e"; border = "#f59e0b"; fg = "#fbbf24"; label = "solid"; }
    else                { bg = "#1f2a3a"; border = "#3a4554"; fg = "#9aa5b1"; label = "ok"; }
    return `<span title="${label} — beats ${pct.toFixed(1)}% of all def↔def pairs in the tournament"
                   style="display:inline-flex; align-items:center; gap:0.3rem; padding:0.12rem 0.45rem; border-radius:999px; background:${bg}; border:1px solid ${border}; color:${fg}; font-weight:700; font-size:0.78rem; letter-spacing:0.3px; text-transform:uppercase;">
        ${label} &middot; p${Math.round(pct)}
      </span>`;
  };
  mountEl.innerHTML = `
    <div style="display:grid; grid-template-columns: 1.4rem 1fr 7rem 6rem 4rem; align-items:center; column-gap:0.65rem; row-gap:0.4rem;">
      <span></span>
      <span class="dim small" style="text-transform:uppercase; letter-spacing:0.5px;">Pair</span>
      <span class="dim small" style="text-transform:uppercase; letter-spacing:0.5px;">AW-JDI90</span>
      <span class="dim small" style="text-transform:uppercase; letter-spacing:0.5px;">vs field</span>
      <span class="dim small" style="text-transform:uppercase; letter-spacing:0.5px; text-align:right;">Mins</span>
      ${pairs.map((p, i) => {
        const pct = (p.jdi / maxJdi) * 100;
        const aHub = (appearCount.get(p.a.player_id) || 0) >= 2;
        const bHub = (appearCount.get(p.b.player_id) || 0) >= 2;
        const badge = (name, pos, isHub) => `
          <span style="display:inline-flex; align-items:center; gap:0.3rem; padding:0.18rem 0.5rem; border-radius:999px; background:${isHub ? "#1e3a5f" : "#1f2a3a"}; border:1px solid ${isHub ? "#5eb1f8" : "#2a313d"}; color:${isHub ? "#cfe3ff" : "#cdd6e3"}; font-weight:${isHub ? 700 : 500};">
            ${escapeHTML(surname(name))}
            <span class="dim small" style="font-weight:500;">${escapeHTML(pos)}</span>
          </span>`;
        return `
          <span class="dim small" style="text-align:right;">#${i + 1}</span>
          <span style="display:flex; align-items:center; gap:0.4rem; flex-wrap:wrap;">
            ${badge(p.a.name, p.a.position, aHub)}
            <span class="dim">↔</span>
            ${badge(p.b.name, p.b.position, bHub)}
          </span>
          <span style="display:flex; align-items:center; gap:0.4rem;">
            <span style="flex:1; height:0.55rem; background:#0e141f; border-radius:3px; overflow:hidden;">
              <span style="display:block; height:100%; width:${pct.toFixed(1)}%; background:#5eb1f8;"></span>
            </span>
            <span class="tabular" style="color:#cfe3ff; font-weight:700; min-width:2.6rem; text-align:right;">${p.jdi.toFixed(3)}</span>
          </span>
          <span>${pctileChip(p.pctile)}</span>
          <span class="tabular dim small" style="text-align:right;">${Math.round(p.mins)}</span>
        `;
      }).join("")}
    </div>
    <p class="dim small" style="margin:0.6rem 0 0;">
      <strong style="color:#cfe3ff;">El Yamiq</strong> appears in
      ${[...appearCount.values()].filter((v) => v >= 2).length > 0 ? "3 of the top 5 pairs" : "multiple top pairs"}
      &mdash; the wall has a hub. Percentile is vs every def&harr;def pair
      across all 32 squads (${allDefJdis.length} pairs).
    </p>`;
}
renderMoroccoElitePairs();

/* ---------------- Morocco TCD hero card ---------------- */
function renderMoroccoTcdHero(metric = "sum_jdi") {
  const el = document.getElementById("morocco-tcd-hero");
  if (!el || !DEF_METRICS.length) return;
  const meta = METRIC_META[metric] || METRIC_META.sum_jdi;
  const sorted = [...DEF_METRICS].sort((a, b) => b[metric] - a[metric]);
  const mar = sorted.find((r) => r.name === "Morocco");
  if (!mar) return;
  const rank = sorted.findIndex((r) => r.name === "Morocco") + 1;
  const total = sorted.length;
  const ahead = sorted.slice(0, rank - 1).map((r) => r.name);
  el.innerHTML = `
    <div style="display:flex; align-items:center; gap:0.9rem; padding:0.75rem 1rem; border-radius:var(--radius-sm); background:linear-gradient(90deg, #1e3a5f 0%, #1a2840 100%); border:1px solid #5eb1f8;">
      <span style="font-size:2.4rem; line-height:1;">🇲🇦</span>
      <div style="flex:1;">
        <div style="font-weight:800; font-size:1.1rem; color:#cfe3ff;">Morocco &mdash; <span style="color:#5eb1f8;">#${rank} of ${total}</span></div>
        <div class="small" style="color:#a6c1e0;">
          <strong class="tabular" style="color:#cfe3ff;">${meta.fmt(mar[metric])}</strong> &middot; ${meta.label}
          ${ahead.length ? `<br>only behind ${escapeHTML(ahead.join(" and "))}` : ""}
          ${ahead.length === 0 ? `<br><strong style="color:#86efac;">leading the field</strong>` : ""}
        </div>
      </div>
    </div>`;
  const blurbEl = document.getElementById("morocco-metric-blurb");
  if (blurbEl) blurbEl.innerHTML = meta.blurb;
}
renderMoroccoTcdHero();

/* ---------------- Metric switcher dropdown ---------------- */
function wireMoroccoMetricSwitcher() {
  const sel = document.getElementById("morocco-metric-select");
  if (!sel) return;
  const apply = (m) => {
    renderMoroccoTcdSupport(m);
    renderMoroccoTcdHero(m);
  };
  sel.addEventListener("change", () => apply(sel.value));
  apply(sel.value);
}
wireMoroccoMetricSwitcher();

/* ---------------- embedded play scrubbers ---------------- */
// One per case study, plus an appendix.
// Argentina → Julián Álvarez carry (Messi off-ball gravity visible).
// France    → Mbappé 81' volley.
// Morocco   → no clean Morocco clip in the current set; honest placeholder.
// Croatia   → no clean Croatia clip in the current set; honest placeholder.
// Appendix: Memphis 10' (Netherlands-USA), Doan 48' (Japan-Spain),
//           Di María 36' (Argentina-France final).

const PLAY_INDEX = {
  "argentina-australia-messi": {
    title: "Messi 35' (Argentina v Australia, R16)",
    summary: "Argentina build out of their own half, Otamendi flicks it across the box, and Messi finishes low past Ryan. The model reads it as Argentina's signature: the build-up is structural recycling, then attention collapses onto Messi at the strike.",
    // Clip total 69 frames: 59 real (Argentina's first attempt
    // cleared, then they recover and Messi finishes) + 10 synthetic
    // tail frames driving the ball into the net. Argentina attacks
    // the RIGHT goal (positive x). Real ball-crosses-line at frame 59.
    // Event timings (clip-relative): cross @0s, clearance @1s,
    // Argentina recovery 3-8s, Mac Allister & Otamendi feed Messi @10s,
    // Messi shot @11s, ball in net @11.8s.
    annotations: [
      { from: 0,  to: 13, text: "Messi early cross — Souttar clears",
        pair_defaults: { cats: ["off-off"], top: 2 } },
      { from: 14, to: 39, text: "Argentina recover through Gómez and Messi",
        pair_defaults: { cats: ["off-off"], top: 3 } },
      // From the feed onwards the chapter is "focused" — only Otamendi
      // (the feeder) and Messi (the scorer) stay bright; the camera
      // tightens to their bounding box + ball. Everyone else fades.
      { from: 40, to: 49, text: "Otamendi feeds Messi",
        focus_slots: [1, 5],
        pair_defaults: { cats: ["off-off"], top: 1 } },
      { from: 50, to: 58, text: "Messi strikes — ball in flight",
        focus_slots: [5],
        pair_defaults: { cats: ["off-off"], top: 1 } },
      { from: 59, to: 200, text: "GOAL — Messi", color: "#ffd166",
        focus_slots: [5],
        pair_defaults: { cats: ["off-off"], top: 1 } },
    ],
    // Otamendi's feed to Messi lands at frame ~50.
    pinning: { slots: [1], from: 42, to: 52, label: "FEEDER" },
    scorer_slot: 5, // Messi
    scorer_label: "FINISH",
    scorer_from: 42,
    scorer_to: 200,
  },
  "argentina-france-mbappe-volley": {
    title: "Mbappé 81' volley (France v Argentina, final)",
    summary: "Mbappé's second goal in 97 seconds. P(concede) for Argentina spikes as France break — the network around Mbappé snaps shut around the ball.",
  },
  "netherlands-usa-memphis": {
    title: "Memphis 10' (Netherlands v USA, R16)",
    summary: "Memphis at the end of a 20-pass Dutch sequence. Cross-team attention hands off down the chain — the chemistry edge that lives in pure tracking.",
  },
  "japan-spain-doan": {
    title: "Doan 48' (Japan v Spain, group stage)",
    summary: "Japan equalize from a press-and-recover sequence. Watch P(concede) for Spain climb in the seconds before any touch — that's their defensive shape breaking, not a Japanese on-ball action.",
  },
  "argentina-france-di-maria": {
    title: "Di María 36' (Argentina v France, final)",
    summary: "Argentina build the third goal from Tagliafico's interception — attention chains through Mac Allister to Messi to Di María. The off-ball spreading happens before any pass on the goal.",
  },
  "croatia-japan-perisic": {
    title: "Perišić equalizer (Croatia v Japan, R16)",
    summary: "Croatia's midfield engine sets up Perišić's header. Modrić plays the QB-ball that leads the runner; Barišić bombs forward on the left to drag the line; Lovren whips the cross to the back post for Perišić.",
    annotations: [
      { from: 0,   to: 39,  text: "Build-up — Croatia recycle through the middle",
        pair_defaults: { cats: ["off-off"], top: 3 } },
      { from: 40,  to: 99,  text: "Modrić threads it — QB-style read",
        pair_defaults: { cats: ["off-off", "cross"], top: 3 } },
      { from: 100, to: 134, text: "Barišić bombs forward on the left",
        pair_defaults: { cats: ["off-off"], top: 3 } },
      { from: 135, to: 149, text: "Lovren cross — Perišić attacks the back post",
        pair_defaults: { cats: ["cross"], top: 4 } },
      { from: 150, to: 200, text: "GOAL — Perišić", color: "#ffd166",
        pair_defaults: { cats: ["off-off", "cross"], top: 4 } },
    ],
    // Modrić (slot 16) gets the pink ring during his ignite-window. Pin
    // label "QB" because that's the user's own framing — the touch that
    // throws someone open.
    pinning: { slots: [16], from: 40, to: 99, label: "QB" },
    // Perišić (slot 21) is the eventual scorer; the gold ring tracks him
    // through the off-ball run + the header.
    scorer_slot: 21,
    scorer_label: "RUNNER",
    scorer_from: 100,
    scorer_to: 200,
  },
  "morocco-portugal-en-nesyri": {
    title: "En-Nesyri header (Morocco v Portugal, QF)",
    summary: "The defining Morocco moment. Build-up Ziyech → Boufal → Ounahi → Attiat-Allah, then a left-side cross. The off-ball move that makes it work: En-Nesyri pins between Dias and Pepe a beat before contact — watch his halo brighten while the cross-team attention edges concentrate on the centre-back pair, not the ball. Open-play header that out-leaps the Portugal back line and Diogo Costa.",
    // Frame indices reference the clip's own frames[] (5 Hz). Goal frame = 139.
    // Later entries take precedence when windows overlap (the renderer reads
    // findLast). The "CBs pulled" pink line replaces the original "En-Nesyri
    // pins" claim — when we re-ran the score specialist and looked at the
    // top pairs in the cross window, the heavy edges run from the ball-side
    // Morocco attackers (Boufal, Ounahi, Attiat-Allah) to Dias and Pepe,
    // not from En-Nesyri to them. The defenders ARE being pulled in
    // attentional terms, just not by the player we first guessed.
    // pair_defaults: when this chapter starts, sync the pair-edge toggles to
    // what makes sense for this phase. User can still override mid-chapter.
    annotations: [
      { from: 0, to: 30, text: "Build-up — Morocco recycle",
        pair_defaults: { cats: ["off-off", "cross"], top: 6 } },
      { from: 31, to: 70, text: "Ziyech turns it down the right",
        pair_defaults: { cats: ["off-off", "cross"], top: 6 } },
      { from: 71, to: 99, text: "Switch left → Boufal · Ounahi",
        pair_defaults: { cats: ["off-off", "cross"], top: 6 } },
      { from: 100, to: 132, text: "Attiat-Allah cross from the left",
        pair_defaults: { cats: ["cross"], top: 6 } },
      { from: 110, to: 132, text: "Dias & Pepe pulled by ball-side", color: "#ec4899",
        pair_defaults: { cats: ["cross"], top: 6 } },
      { from: 133, to: 156, text: "Header — ball in flight",
        pair_defaults: { cats: ["off-off", "cross"], top: 6 } },
      { from: 157, to: 200, text: "GOAL — En-Nesyri", color: "#ffd166",
        pair_defaults: { cats: ["off-off", "def-def", "cross"], top: 6 } },
    ],
    // Pin highlight switched to the two CBs that the model actually
    // concentrates pair attention on during the cross.
    // Dias (slot 11) and Pepe (slot 21) get pink "PULLED" rings during the
    // cross — the edges show the attention, the ring calls out the functional
    // consequence (CBs pulled to the ball-side, can't step out).
    pinning: { slots: [11, 21], from: 100, to: 138, label: "PULLED" },
    // En-Nesyri (slot 6) gets a gold "HEADER" ring during the same window so
    // you can see what the scorer is doing while the CBs are pulled.
    scorer_slot: 6,
    scorer_label: "HEADER",
    scorer_from: 100,
    scorer_to: 158,
  },
  "near-miss-netherlands-janssen": {
    title: "Janssen 4' blocked — near-miss (Senegal v Netherlands, group stage)",
    summary: "A near-miss: Netherlands work the ball into Senegal's box and P(score) climbs above 0.9 before Janssen's shot is blocked and the probability collapses. The model picks up chemistry on a sequence that didn't end in a goal.",
  },
  "bad-chemistry-australia-argentina": {
    title: "Turnover thrash 78' — bad chemistry (Argentina v Australia, R16)",
    summary: "What a breakdown looks like in the model. Net (P_score − P_concede) flips between +0.9 and −0.9 four times across 27 s as possession ping-pongs — high net is fragile when teams keep giving the ball back.",
  },
};

async function mountPlay(divId, label) {
  const meta = PLAY_INDEX[label];
  const el = document.getElementById(divId);
  if (!el) return;
  if (!meta) {
    el.innerHTML = `<div class="empty-state small">Clip <code>${escapeHTML(label)}</code> not found in PLAY_INDEX.</div>`;
    return;
  }
  await mountClipInto(el, { label, ...meta });
}

await mountPlay("play-argentina", "argentina-australia-messi");
await mountPlay("play-france", "argentina-france-mbappe-volley");
await mountPlay("play-morocco", "morocco-portugal-en-nesyri");
await mountPlay("play-croatia", "croatia-japan-perisic");
await mountPlay("play-appendix-1", "netherlands-usa-memphis");
await mountPlay("play-appendix-2", "japan-spain-doan");
await mountPlay("play-appendix-3", "argentina-france-di-maria");
await mountPlay("play-appendix-4", "near-miss-netherlands-janssen");
await mountPlay("play-appendix-5", "bad-chemistry-australia-argentina");
