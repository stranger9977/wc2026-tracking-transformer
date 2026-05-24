import { loadJSON, escapeHTML, fmtNum, fmtInt, renderEmpty } from "./site.js";

const listEl = document.getElementById("play-list");

const idx = await loadJSON("data/clips/index.json").catch(() => null);

if (!idx || !Array.isArray(idx) || idx.length === 0) {
  renderEmpty(listEl,
    "Clips not yet rendered.",
    "Run scripts/render_interactive_clip.py for each play you want to publish.");
} else {
  listEl.innerHTML = idx.map((c, i) => `
    <section class="card" id="clip-${escapeHTML(c.label)}">
      <h2 class="mt-0">${escapeHTML(c.title)}</h2>
      <p class="dim small">${escapeHTML(c.summary || "")}</p>
      <div class="clip-viewer">
        <img id="img-${escapeHTML(c.label)}" alt="${escapeHTML(c.title)}" loading="lazy" style="width:100%; border-radius:8px;">
        <div class="clip-controls">
          <button class="btn small" data-clip="${escapeHTML(c.label)}" data-action="prev">◀ prev</button>
          <button class="btn small" data-clip="${escapeHTML(c.label)}" data-action="play">▶ play</button>
          <button class="btn small" data-clip="${escapeHTML(c.label)}" data-action="next">next ▶</button>
          <input type="range" id="scrub-${escapeHTML(c.label)}" min="0" max="0" value="0" style="flex:1;">
        </div>
        <div id="meta-${escapeHTML(c.label)}" class="clip-meta small dim"></div>
      </div>
    </section>`).join("");

  for (const c of idx) {
    const detail = await loadJSON(`data/clips/${c.label}.json`).catch(() => null);
    if (!detail) continue;
    initClip(c, detail);
  }
}

function initClip(c, detail) {
  const img = document.getElementById(`img-${c.label}`);
  const scrub = document.getElementById(`scrub-${c.label}`);
  const meta = document.getElementById(`meta-${c.label}`);
  const n = detail.n_frames;
  if (!img || !scrub) return;
  scrub.max = String(n - 1);
  let idx = 0;
  let playTimer = null;

  function setFrame(i) {
    idx = Math.max(0, Math.min(n - 1, i));
    scrub.value = String(idx);
    img.src = detail.image_pattern.replace("{idx:03d}", String(idx).padStart(3, "0"));
    const f = detail.frames[idx];
    const top = (f.top_attended || []).map(t => `slot ${t.slot} (${fmtNum(t.attention, 3)})`).join("  •  ");
    meta.innerHTML = `
      <strong>Frame ${idx + 1}/${n}</strong> &nbsp;•&nbsp;
      P(score, next&nbsp;10&nbsp;s) <span class="chip green tabular">${fmtNum(f.p_score, 3)}</span> &nbsp;
      P(concede, next&nbsp;10&nbsp;s) <span class="chip red tabular">${fmtNum(f.p_concede, 3)}</span> &nbsp;
      Frame-VAEP (Δ&nbsp;P) <span class="chip tabular">${fmtNum(f.vaep, 3)}</span>
      <span class="muted small">(unitless probability)</span><br>
      Top attended players (ball→player attention weight): ${escapeHTML(top || "—")}`;
  }
  setFrame(0);

  scrub.addEventListener("input", (e) => setFrame(Number(e.target.value)));

  document.querySelectorAll(`[data-clip="${c.label}"]`).forEach((btn) => {
    btn.addEventListener("click", () => {
      const a = btn.dataset.action;
      if (a === "prev") setFrame(idx - 1);
      else if (a === "next") setFrame(idx + 1);
      else if (a === "play") {
        if (playTimer) { clearInterval(playTimer); playTimer = null; btn.textContent = "▶ play"; }
        else {
          btn.textContent = "⏸ pause";
          playTimer = setInterval(() => {
            if (idx + 1 >= n) { clearInterval(playTimer); playTimer = null; btn.textContent = "▶ play"; return; }
            setFrame(idx + 1);
          }, 200);
        }
      }
    });
  });
}
