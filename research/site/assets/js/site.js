/* Shared site logic: nav toggle, active link, fetch helpers. */

export function initNav() {
  const toggle = document.querySelector(".nav-toggle");
  const nav = document.querySelector(".site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      nav.classList.toggle("open");
    });
  }

  // mark active link by filename
  const here = (location.pathname.split("/").pop() || "index.html").toLowerCase();
  document.querySelectorAll(".site-nav a").forEach((a) => {
    const href = (a.getAttribute("href") || "").toLowerCase();
    if (href === here || (here === "" && href === "index.html")) {
      a.classList.add("active");
    }
  });
}

export async function loadJSON(path) {
  try {
    const resp = await fetch(path, { cache: "no-store" });
    if (!resp.ok) return null;
    return await resp.json();
  } catch (e) {
    console.warn(`Failed to load ${path}:`, e);
    return null;
  }
}

export function renderEmpty(container, label, hint) {
  container.innerHTML =
    `<div class="empty-state"><strong>${escapeHTML(label)}</strong>` +
    (hint ? `<span>${escapeHTML(hint)}</span>` : "") +
    `</div>`;
}

export function escapeHTML(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function fmtNum(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  if (typeof x !== "number") return String(x);
  if (Math.abs(x) >= 1000) return x.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return x.toFixed(digits);
}

export function fmtInt(x) {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return Number(x).toLocaleString("en-US");
}

/** Render a country flag IMG element from a flagcdn.com code. */
export function flagHTML(flagCode, { size = "small", alt = "" } = {}) {
  if (!flagCode) return "";
  const px = size === "lg" ? "32x24" : "16x12";
  const cls = size === "lg" ? "flag lg" : "flag";
  return `<img class="${cls}" src="https://flagcdn.com/${px}/${escapeHTML(flagCode)}.png" alt="${escapeHTML(alt)}" loading="lazy">`;
}

const ROLE_FROM_POS = {
  GK: "gk",
  LB: "def", LCB: "def", MCB: "def", CB: "def", RCB: "def", RB: "def",
  LWB: "def", RWB: "def",
  DM: "mid", CDM: "mid", LDM: "mid", RDM: "mid", CM: "mid", LCM: "mid", RCM: "mid",
  AM: "mid", CAM: "mid", LAM: "mid", RAM: "mid", LM: "mid", RM: "mid",
  LW: "fwd", RW: "fwd", LWF: "fwd", RWF: "fwd", SS: "mid",
  CF: "fwd", ST: "fwd", LF: "fwd", RF: "fwd",
};

/** Render a small position chip (e.g. <span class="pos-chip def">LCB</span>). */
export function posChip(pos) {
  if (!pos) return "";
  const role = ROLE_FROM_POS[String(pos).toUpperCase()] || "";
  return `<span class="pos-chip ${role}">${escapeHTML(pos)}</span>`;
}

/** Render player name with a trailing position chip. */
export function nameWithPos(name, pos) {
  return `${escapeHTML(name || "")}${posChip(pos)}`;
}

/* Lightweight sortable-table helper. Operates on plain JS data. */
export function makeSortableTable({ data, columns, container, rowKey, emptyLabel }) {
  let sortKey = columns.find((c) => c.defaultSort)?.key || columns[0].key;
  let sortDir = columns.find((c) => c.defaultSort)?.defaultDir || "desc";
  let filtered = data.slice();

  function compare(a, b, key) {
    const av = a[key], bv = b[key];
    if (av === bv) return 0;
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    if (typeof av === "number" && typeof bv === "number") return av - bv;
    return String(av).localeCompare(String(bv));
  }

  function applySort() {
    filtered.sort((a, b) => {
      const c = compare(a, b, sortKey);
      return sortDir === "asc" ? c : -c;
    });
  }

  function render() {
    applySort();
    if (filtered.length === 0) {
      renderEmpty(container, emptyLabel || "No rows match.", "");
      return;
    }

    const thead = columns
      .map((c) => {
        const ind = c.key === sortKey ? (sortDir === "asc" ? " ▲" : " ▼") : "";
        const cls = c.num ? "num" : "";
        return `<th class="${cls}" data-key="${escapeHTML(c.key)}">${escapeHTML(c.label)}<span class="sort-ind">${ind}</span></th>`;
      })
      .join("");

    const tbody = filtered
      .map((row) => {
        const cells = columns
          .map((c) => {
            const v = c.render ? c.render(row) : row[c.key];
            const label = escapeHTML(c.label);
            const cls = c.num ? "num" : "";
            const display = c.render ? v : (c.num ? fmtNum(v, c.digits ?? 2) : escapeHTML(v ?? ""));
            return `<td class="${cls}" data-label="${label}">${display}</td>`;
          })
          .join("");
        return `<tr>${cells}</tr>`;
      })
      .join("");

    container.innerHTML = `<div class="table-wrap"><table class="data-table"><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table></div>`;

    container.querySelectorAll("th[data-key]").forEach((th) => {
      th.addEventListener("click", () => {
        const k = th.getAttribute("data-key");
        if (k === sortKey) {
          sortDir = sortDir === "asc" ? "desc" : "asc";
        } else {
          sortKey = k;
          const col = columns.find((c) => c.key === k);
          sortDir = col?.defaultDir || (col?.num ? "desc" : "asc");
        }
        render();
      });
    });
  }

  return {
    setData(newData) {
      filtered = newData.slice();
      render();
    },
    filter(predicate) {
      filtered = data.filter(predicate);
      render();
    },
    render,
  };
}

// Auto-init on DOMContentLoaded
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initNav);
} else {
  initNav();
}
