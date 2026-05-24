/**
 * Club vs National — page extras:
 *   1. "Step 1 · Form at the tournament" leaderboards (over / under).
 *   2. Story cards: club vs WC22 z-score paired bars for 4–5 named players.
 *   3. "Open questions" — per-stage P(score)/P(concede) bar chart and a
 *      club-vs-WC22 OI/90 scatter.
 *
 * The cross-context table itself is rendered by `cross-context.js`; this file
 * adds the framing-and-narrative bits the partner wanted in the video brief.
 *
 * No new dependencies — vanilla JS + inline SVG.
 */
import { loadJSON, escapeHTML, fmtNum, flagHTML, posChip } from "./site.js";

const STAGES_ORDER = ["Group", "R16", "QF", "SF", "Final/3rd"];

/* ----------------------------- form leaderboard ---------------------------- */

function renderFormLeaderboard(form, teamFlag) {
  const root = document.getElementById("form-leaderboard");
  const tabs = document.querySelectorAll("#form-tabs button");
  if (!root || !form) return;
  let mode = "over";

  function rows() {
    return mode === "over" ? form.over_performers : form.under_performers;
  }

  function render() {
    const data = rows().slice(0, 15);
    const tbody = data
      .map((r) => {
        const d = Number(r.delta_per90 ?? 0);
        const cls = d >= 0 ? "green" : "red";
        const fc = teamFlag.get(r.team_name) || "";
        return `<tr>
          <td><strong>${escapeHTML(r.player_name || "")}</strong>${posChip(r.position)}</td>
          <td>${flagHTML(fc, { alt: r.team_name })}<span class="muted small">${escapeHTML(r.team_name || "")}</span></td>
          <td class="num">${fmtNum(r.total_minutes, 0)}</td>
          <td class="num">${fmtNum(r.actual_oi_total, 2)}</td>
          <td class="num">${fmtNum(r.expected_oi_total, 2)}</td>
          <td class="num"><span class="chip ${cls}">${(d >= 0 ? "+" : "") + fmtNum(d, 2)}</span></td>
        </tr>`;
      })
      .join("");
    root.innerHTML = `
      <div class="table-wrap"><table class="data-table">
        <thead><tr>
          <th>Player</th><th>National team</th>
          <th class="num">WC22 min</th>
          <th class="num">Actual OI</th>
          <th class="num">Expected OI</th>
          <th class="num">Δ OI/90</th>
        </tr></thead>
        <tbody>${tbody}</tbody>
      </table></div>`;
  }

  tabs.forEach((b) =>
    b.addEventListener("click", () => {
      mode = b.dataset.tab;
      tabs.forEach((x) => x.classList.toggle("active", x === b));
      render();
    }),
  );
  render();
}

/* ------------------------------- story cards ------------------------------- */

// Five hand-picked story templates. Player matching is by substring on
// `name_in_source` so we tolerate the long/short-name divergence between PFF
// and StatsBomb without hard-coding IDs.
const STORIES = [
  {
    id: "mbappe",
    title: "Mbappé: club genius that <em>partially</em> travels",
    matchPff: "Kylian Mbappé",
    pffComp: "wc_2022_pff",
    otherCompSubstr: "ligue1",
    blurb:
      "PSG gives Mbappé an attack that orbits him entirely: he is z = +3.3 in Ligue 1 2022/23, well clear of any other Ligue 1 forward. France in WC22 still rates him a top-of-cohort forward (z ≈ +1.6) — elite, but a full standard-deviation drop. He's not the same isolated star at international level; he's one of three or four equivalent threats. That's not chemistry friction in the bad sense, it's the cost of sharing.",
  },
  {
    id: "hakimi",
    title: "Hakimi: the lift that doesn't survive the trip",
    matchPff: "Achraf Hakimi",
    pffComp: "wc_2022_pff",
    otherCompSubstr: "ligue1",
    blurb:
      "At PSG, Hakimi is a +2.2 z right-back overlapping into a system that gives him the touchline. For Morocco at WC22, in a deeper defensive block built to contain rather than to overlap, he reads z = −0.5. Same player, same tournament window — the system around him changed. This is the chemistry-friction signal in its purest form.",
  },
  {
    id: "havertz",
    title: "Havertz at WC22 ≠ Havertz at Euro 2024",
    matchPff: "Kai Havertz",
    pffComp: "wc_2022_pff",
    otherCompSubstr: "euro_2024",
    blurb:
      "Group-stage rebuilding Germany in 2022 used Havertz as a connecting 10; he reads z = +1.5 in a small WC22 sample. The 2024 Euro version of the same player, asked to lead the line in a much more structured Nagelsmann setup, dropped to z = −0.9. Two tournaments, two different roles, two different national-team performances — and the underlying technical profile didn't change.",
  },
  {
    id: "morata",
    title: "Morata: better with Spain than with anyone",
    matchPff: "Álvaro Morata",
    pffComp: "wc_2022_pff",
    otherCompSubstr: "euro_2024",
    blurb:
      "Morata at WC22 is one of the strongest WC22 forwards by Δ-OI (+1.7), a player who out-played his expected profile by a comfortable margin. Two years later at Euro 2024, in a near-identical Spain setup, he reads roughly average for a tournament forward (z ≈ −0.1). The chemistry that flattered him in 2022 — Pedri/Gavi-led build, full backs pushed high — was less present in 2024. The player is more or less a constant; the supply is not.",
  },
  {
    id: "dieng",
    title: "Bamba Dieng: tournament-only riser",
    matchPff: "Bamba Dieng",
    pffComp: "wc_2022_pff",
    otherCompSubstr: null, // no club coverage in our open-data set
    blurb:
      "Dieng arrived at WC22 with no Champions League minutes, no big-five-league track record, no Euro/Copa data we can pull. In 77 WC22 minutes for Senegal he posted Δ OI/90 of +1.80 — the single largest over-performance vs the positional baseline in the entire tournament. That is the platonic case of a national-team setup making a player. Without club data we can't say if he was ever this good for Pau or Lorient. With WC2026 around the corner, his Marseille minutes will be the look-ahead.",
  },
];

function renderStoryCards(crossContext) {
  const root = document.getElementById("story-cards");
  if (!root) return;
  const rows = crossContext?.rows || [];

  // Normalize names so "Álvaro Morata" and "Alvaro Borja Morata Martín" both
  // contain the canonical {alvaro, morata} word set.
  const norm = (s) =>
    (s || "")
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "") // strip diacritics
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();

  // Match by requiring every word of the canonical short name to appear in the
  // candidate's normalized name. Avoids the "Hakim" → "Hakim Ziyech" collision
  // we'd get from naive substring matching.
  function findRow(matchPff, competition) {
    const want = new Set(norm(matchPff).split(" ").filter((w) => w.length >= 2));
    return rows.find((r) => {
      if (r.competition !== competition) return false;
      const have = new Set(norm(r.name_in_source).split(" "));
      for (const w of want) if (!have.has(w)) return false;
      return true;
    });
  }

  function findRowSubstr(matchPff, substr) {
    const want = new Set(norm(matchPff).split(" ").filter((w) => w.length >= 2));
    return rows.find((r) => {
      if (!substr || !r.competition.includes(substr)) return false;
      const have = new Set(norm(r.name_in_source).split(" "));
      for (const w of want) if (!have.has(w)) return false;
      return true;
    });
  }

  const html = STORIES.map((s) => {
    const pff = findRow(s.matchPff, s.pffComp);
    const other = s.otherCompSubstr ? findRowSubstr(s.matchPff, s.otherCompSubstr) : null;
    const cards = [pff, other].filter(Boolean);
    if (!pff) return ""; // no PFF row → skip
    return `
      <article class="card story-card" id="story-${s.id}">
        <h3 class="mt-0">${s.title}</h3>
        <div class="story-card-body">
          <div class="story-chart">${storyChartSVG(pff, other)}</div>
          <div class="story-meta">
            <div class="meta">
              ${flagHTML(pff.flag_code, { alt: pff.team_name })}
              <strong>${escapeHTML(pff.name_in_source || s.matchPff)}</strong>
              ${posChip(pff.position)}
              <span class="muted small">${escapeHTML(pff.team_name || "")}</span>
            </div>
            <ul class="small story-numbers">
              ${cards.map((r) => `
                <li>
                  <span class="muted">${escapeHTML(prettyComp(r.competition))}</span>
                  <strong>${(r.z_oi_per90 ?? 0) >= 0 ? "+" : ""}${fmtNum(r.z_oi_per90, 2)} z</strong>
                  · ${fmtNum(r.oi_per90, 2)} OI/90 · ${fmtNum(r.minutes, 0)} min
                </li>`).join("")}
              ${!other && s.otherCompSubstr === null
                ? `<li class="muted">No club coverage in open data — see <em>tournament-only</em> framing.</li>`
                : ""}
            </ul>
            <p class="small">${s.blurb}</p>
          </div>
        </div>
      </article>`;
  }).join("");
  root.innerHTML = html;
}

function prettyComp(c) {
  const map = {
    wc_2022_pff: "WC22 (PFF)",
    wc_2022_sb: "WC22 (StatsBomb)",
    euro_2024: "Euro 2024",
    copa_america_2024: "Copa America 2024",
    ligue1_22_23: "Ligue 1 2022/23",
    bundesliga_23_24: "Bundesliga 2023/24",
    laliga_20_21: "La Liga 2020/21",
  };
  return map[c] || c;
}

/* Tiny inline-SVG paired-bar chart (z-scored OI/90). */
function storyChartSVG(pff, other) {
  const W = 240, H = 110, M = { l: 6, r: 6, t: 18, b: 18 };
  const cx = (W - M.l - M.r) / 2;
  const midY = M.t + (H - M.t - M.b) / 2;
  const zMax = 3.5;
  const yFor = (z) => {
    const range = (H - M.t - M.b) / 2;
    return midY - (z / zMax) * range;
  };
  const bar = (x, z, label, color) => {
    const y = yFor(z);
    const h = Math.max(2, Math.abs(midY - y));
    const top = z >= 0 ? y : midY;
    const labelY = z >= 0 ? y - 4 : y + 12;
    return `
      <rect x="${x - 26}" y="${top}" width="52" height="${h}" fill="${color}" rx="2"/>
      <text x="${x}" y="${labelY}" text-anchor="middle" font-size="11" fill="#cdd6e0">${(z >= 0 ? "+" : "") + z.toFixed(2)}</text>
      <text x="${x}" y="${H - 4}" text-anchor="middle" font-size="10" fill="#8a96a3">${label}</text>`;
  };
  const a = bar(M.l + cx / 2, pff?.z_oi_per90 ?? 0, "WC22 (PFF)", "#ffb24a");
  const b = other
    ? bar(M.l + cx + cx / 2, other.z_oi_per90 ?? 0, prettyCompShort(other.competition), "#6aa3ff")
    : `<text x="${M.l + cx + cx / 2}" y="${midY}" text-anchor="middle" font-size="10" fill="#5b6470">no club data</text>`;
  return `
    <svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Z-score comparison">
      <line x1="${M.l}" x2="${W - M.r}" y1="${midY}" y2="${midY}" stroke="#3a4350" stroke-width="1"/>
      <text x="${M.l}" y="${M.t - 4}" font-size="9" fill="#5b6470">+z</text>
      <text x="${M.l}" y="${H - M.b + 10}" font-size="9" fill="#5b6470">−z</text>
      ${a}${b}
    </svg>`;
}

function prettyCompShort(c) {
  const map = {
    wc_2022_pff: "WC22",
    wc_2022_sb: "WC22 (SB)",
    euro_2024: "Euro 24",
    copa_america_2024: "Copa 24",
    ligue1_22_23: "Ligue 1",
    bundesliga_23_24: "BuLi",
    laliga_20_21: "La Liga",
  };
  return map[c] || c;
}

/* --------------------------- per-stage attack/def -------------------------- */

function renderStagesChart(extras) {
  const root = document.getElementById("stages-chart");
  const summary = document.getElementById("stages-summary");
  if (!root || !extras?.per_stage_attack_defence) return;
  const stages = extras.per_stage_attack_defence.filter((s) => STAGES_ORDER.includes(s.stage));
  if (!stages.length) return;

  const W = 640, H = 220, M = { l: 60, r: 80, t: 22, b: 36 };
  const innerW = W - M.l - M.r;
  const innerH = H - M.t - M.b;
  const xStep = innerW / Math.max(1, stages.length);

  const allScore = stages.map((s) => s.avg_p_score);
  const allConc = stages.map((s) => s.avg_p_concede);
  // independent axes for the two series (different magnitudes)
  const sMax = Math.max(...allScore) * 1.15;
  const cMax = Math.max(...allConc) * 1.15;
  const yScore = (v) => M.t + innerH - (v / sMax) * innerH;
  const yConc = (v) => M.t + innerH - (v / cMax) * innerH;

  const groupW = xStep * 0.7;
  const barW = groupW / 2 - 2;

  const bars = stages
    .map((s, i) => {
      const cx = M.l + i * xStep + xStep / 2;
      const x1 = cx - groupW / 2;
      const x2 = cx + 2;
      const ys = yScore(s.avg_p_score);
      const yc = yConc(s.avg_p_concede);
      return `
        <g>
          <rect x="${x1}" y="${ys}" width="${barW}" height="${M.t + innerH - ys}" fill="#6aa3ff" rx="2"/>
          <text x="${x1 + barW / 2}" y="${ys - 4}" font-size="9" fill="#cdd6e0" text-anchor="middle">${s.avg_p_score.toFixed(4)}</text>
          <rect x="${x2}" y="${yc}" width="${barW}" height="${M.t + innerH - yc}" fill="#ffb24a" rx="2"/>
          <text x="${x2 + barW / 2}" y="${yc - 4}" font-size="9" fill="#cdd6e0" text-anchor="middle">${s.avg_p_concede.toFixed(4)}</text>
          <text x="${cx}" y="${H - 12}" text-anchor="middle" font-size="11" fill="#8a96a3">${s.stage}</text>
          <text x="${cx}" y="${H - 1}" text-anchor="middle" font-size="9" fill="#5b6470">${s.n_actions.toLocaleString()} actions</text>
        </g>`;
    })
    .join("");

  // axis labels
  const legend = `
    <g transform="translate(${W - M.r + 6}, ${M.t})">
      <rect x="0" y="0" width="10" height="10" fill="#6aa3ff" rx="2"/>
      <text x="14" y="9" font-size="11" fill="#cdd6e0">P(score)</text>
      <rect x="0" y="18" width="10" height="10" fill="#ffb24a" rx="2"/>
      <text x="14" y="27" font-size="11" fill="#cdd6e0">P(concede)</text>
    </g>`;

  const yAxisScore = `
    <text x="${M.l - 8}" y="${M.t - 6}" font-size="10" fill="#6aa3ff" text-anchor="end">${sMax.toFixed(4)}</text>
    <text x="${M.l - 8}" y="${M.t + innerH}" font-size="10" fill="#6aa3ff" text-anchor="end">0</text>`;
  const yAxisConc = `
    <text x="${W - M.r + 4}" y="${M.t - 6}" font-size="10" fill="#ffb24a">${cMax.toFixed(4)}</text>`;

  root.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Per-stage attack and defence">
      <line x1="${M.l}" x2="${W - M.r}" y1="${M.t + innerH}" y2="${M.t + innerH}" stroke="#3a4350" stroke-width="1"/>
      ${bars}
      ${yAxisScore}
      ${yAxisConc}
      ${legend}
    </svg>`;

  // 1-line summary of the trend.
  // Soften the verdict when the magnitudes are tiny relative to the series
  // mean — readers should see "essentially flat" rather than a story-shaped
  // claim driven by Δ in the fourth decimal.
  const first = stages[0], last = stages[stages.length - 1];
  const scoreTrend = last.avg_p_score - first.avg_p_score;
  const concTrend = last.avg_p_concede - first.avg_p_concede;
  const scoreMean = allScore.reduce((a, b) => a + b, 0) / allScore.length;
  const concMean  = allConc.reduce((a, b) => a + b, 0) / allConc.length;
  // Treat a swing as "real" only if it moves the series mean by ≥10%.
  const scoreReal = Math.abs(scoreTrend) >= 0.10 * Math.abs(scoreMean || 1);
  const concReal  = Math.abs(concTrend)  >= 0.10 * Math.abs(concMean  || 1);
  let verdict;
  if (!scoreReal && !concReal) {
    verdict = `Both series essentially flat across stages: Δ P(score) = ${(scoreTrend > 0 ? "+" : "") + scoreTrend.toFixed(4)}, Δ P(concede) = ${(concTrend > 0 ? "+" : "") + concTrend.toFixed(4)} (Group → Final). At this sample size the league average shows no chemistry-by-stage effect.`;
  } else if (scoreReal && concReal && scoreTrend > 0 && concTrend < 0) {
    verdict = "Offence rises, defence holds — consistent with attackers gelling faster than back lines.";
  } else if (scoreReal && scoreTrend > 0 && !concReal) {
    verdict = `Offence drifts up (+${scoreTrend.toFixed(4)} P(score) Group → Final); defence sits roughly flat (Δ P(concede) = ${(concTrend > 0 ? "+" : "") + concTrend.toFixed(4)}, within noise).`;
  } else if (concReal && concTrend > 0 && !scoreReal) {
    verdict = `Defence drifts up (+${concTrend.toFixed(4)} P(concede) Group → Final); offence is flat (Δ P(score) = ${(scoreTrend > 0 ? "+" : "") + scoreTrend.toFixed(4)}, within noise). Stronger remaining opponents is the likelier explanation.`;
  } else {
    verdict = `Δ P(score) = ${(scoreTrend > 0 ? "+" : "") + scoreTrend.toFixed(4)}, Δ P(concede) = ${(concTrend > 0 ? "+" : "") + concTrend.toFixed(4)} (Group → Final). Mixed signal — small magnitudes relative to the series mean.`;
  }
  if (summary) summary.innerHTML = verdict;
}

/* ----------------------------- mean scatter ------------------------------- */

function renderMeanScatter(extras) {
  const root = document.getElementById("mean-scatter");
  const summary = document.getElementById("mean-summary");
  if (!root || !extras?.club_vs_wc22_scatter) return;
  const data = extras.club_vs_wc22_scatter;
  if (!data.length) return;

  const W = 640, H = 360, M = { l: 50, r: 30, t: 20, b: 44 };
  const innerW = W - M.l - M.r;
  const innerH = H - M.t - M.b;

  const xs = data.map((d) => d.club_oi_per90);
  const ys = data.map((d) => d.wc22_oi_per90);
  const padding = 0.2;
  const xMin = Math.min(...xs) - padding, xMax = Math.max(...xs) + padding;
  const yMin = Math.min(...ys) - padding, yMax = Math.max(...ys) + padding;
  const xFor = (v) => M.l + ((v - xMin) / (xMax - xMin)) * innerW;
  const yFor = (v) => M.t + (1 - (v - yMin) / (yMax - yMin)) * innerH;

  // axes and zero lines
  const x0 = xFor(0), y0 = yFor(0);
  const xZero = x0 >= M.l && x0 <= M.l + innerW
    ? `<line x1="${x0}" x2="${x0}" y1="${M.t}" y2="${M.t + innerH}" stroke="#3a4350" stroke-dasharray="3,3"/>`
    : "";
  const yZero = y0 >= M.t && y0 <= M.t + innerH
    ? `<line x1="${M.l}" x2="${M.l + innerW}" y1="${y0}" y2="${y0}" stroke="#3a4350" stroke-dasharray="3,3"/>`
    : "";

  // y=x reference line (perfectly transported chemistry)
  const yEqMin = Math.max(xMin, yMin), yEqMax = Math.min(xMax, yMax);
  const yEq = `<line x1="${xFor(yEqMin)}" y1="${yFor(yEqMin)}" x2="${xFor(yEqMax)}" y2="${yFor(yEqMax)}" stroke="#5b6470" stroke-width="1" stroke-dasharray="4,4" opacity="0.7"/>`;

  // dots: highlight a few named players so the chart connects to the story cards
  const NAMED = new Set(["Kylian Mbappé", "Achraf Hakimi", "Kai Havertz", "Álvaro Morata", "Robert Lewandowski"]);
  const dots = data
    .map((d) => {
      const cx = xFor(d.club_oi_per90), cy = yFor(d.wc22_oi_per90);
      const named = NAMED.has(d.player_name);
      const r = named ? 5 : 2.5;
      const fill = named ? "#ffb24a" : "rgba(106,163,255,0.55)";
      const stroke = named ? "#fff" : "none";
      const lbl = named
        ? `<text x="${cx + 7}" y="${cy + 3}" font-size="10" fill="#cdd6e0">${escapeHTML(d.player_name)}</text>`
        : "";
      const title = `<title>${escapeHTML(d.player_name || "")} — ${escapeHTML(prettyCompShort(d.club_competition))}: club ${d.club_oi_per90.toFixed(2)}, WC22 ${d.wc22_oi_per90.toFixed(2)}</title>`;
      return `<g><circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="1">${title}</circle>${lbl}</g>`;
    })
    .join("");

  // ticks
  const xTicks = [-1, 0, 1, 2, 3].filter((v) => v >= xMin && v <= xMax);
  const yTicks = [-1, 0, 1, 2, 3].filter((v) => v >= yMin && v <= yMax);
  const xT = xTicks.map((v) => `<text x="${xFor(v)}" y="${M.t + innerH + 14}" text-anchor="middle" font-size="10" fill="#8a96a3">${v}</text>`).join("");
  const yT = yTicks.map((v) => `<text x="${M.l - 6}" y="${yFor(v) + 3}" text-anchor="end" font-size="10" fill="#8a96a3">${v}</text>`).join("");

  root.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Club OI/90 vs WC22 OI/90">
      <rect x="${M.l}" y="${M.t}" width="${innerW}" height="${innerH}" fill="rgba(255,255,255,0.02)" stroke="#3a4350"/>
      ${xZero}${yZero}${yEq}
      ${dots}
      ${xT}${yT}
      <text x="${M.l + innerW / 2}" y="${H - 4}" text-anchor="middle" font-size="11" fill="#8a96a3">club OI/90 →</text>
      <text x="${M.l - 38}" y="${M.t + innerH / 2}" font-size="11" fill="#8a96a3" transform="rotate(-90, ${M.l - 38}, ${M.t + innerH / 2})">WC22 OI/90 →</text>
    </svg>`;

  const r = extras.club_vs_wc22_correlation?.pearson_r ?? 0;
  const rho = extras.club_vs_wc22_correlation?.spearman_rho ?? 0;
  const n = extras.club_vs_wc22_correlation?.n ?? data.length;
  const verdict = Math.abs(r) < 0.15
    ? `<strong>Near-zero correlation</strong> (Pearson r = ${r.toFixed(3)}, Spearman ρ = ${rho.toFixed(3)}, n = ${n} non-GK players). A player's club OI/90 essentially does not predict his WC22 OI/90. That is striking: it argues that most of the WC22 over/under-performance is <em>not</em> regression to the player's true mean. It's the partnerships — or the role, or the opponent — around him. The chemistry-friction story has room to be real, not just statistical noise.`
    : `Pearson r = ${r.toFixed(3)}, Spearman ρ = ${rho.toFixed(3)} (n = ${n}). A modest positive correlation — most of the WC22 result is the player, with the residual the variance the chemistry-friction story has to explain.`;
  if (summary) summary.innerHTML = verdict;
}

/* ---------------------------------- main ---------------------------------- */

const [form, crossContext, extras, teams] = await Promise.all([
  loadJSON("data/player_form.json"),
  loadJSON("data/cross_context.json"),
  loadJSON("data/club_vs_national_extras.json"),
  loadJSON("data/teams.json"),
]);

const teamFlag = new Map((teams || []).map((t) => [t.team_name, t.flag_code]));

renderFormLeaderboard(form, teamFlag);
renderStoryCards(crossContext);
renderStagesChart(extras);
renderMeanScatter(extras);
