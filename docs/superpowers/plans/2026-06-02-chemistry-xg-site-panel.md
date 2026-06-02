# Chemistry → Expected Goals Site Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a paired offense/defense added-variable scatter panel to `chemistry-wins.html` that grounds the chemistry finding in expected goals over/under expected.

**Architecture:** A Python build script (with pure, unit-tested helpers in `research/src/xg/site_data.py`) productionizes the Layer-1 residual computation and emits `research/site/data/chemistry_xg.json`. The front end adds a continuous-axis scatter renderer (`renderXgScatter`) modeled on the existing `renderTcdScatter`, drawing two added-variable plots above the existing TCD-vs-finish scatter. Additive only.

**Tech Stack:** Python 3.12 (pandas, numpy, scikit-learn — already deps), vanilla ES module SVG (no charting lib), static site.

**Key statistical decision (locked):** Both axes are **residualized on the same controls** (FIFA overall + mean_caps + games + opponent-FIFA) — an added-variable plot — so the visible trend equals the annotated partial-r. Defense panel orients y as **xG prevented over expected** = −(xGA residual) so "up = good" on both panels. Validated numbers: n=29, defense partial r = **+0.38** (≡ −0.38 vs xGA; 90% CI [+0.08, +0.64]), offense partial r = **+0.16**.

---

### Task 1: Build-script helpers (`research/src/xg/site_data.py`)

**Files:**
- Create: `research/src/xg/site_data.py`
- Test: `research/tests/test_xg_site_data.py`

- [ ] **Step 1: Write the failing test**

```python
# research/tests/test_xg_site_data.py
import numpy as np
import pandas as pd
from xg.site_data import residualize, build_team_xg_table


def test_residualize_removes_linear_control():
    # y = 2*c + noise-free; residual on [c] must be ~0
    frame = pd.DataFrame({"c": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]})
    r = residualize(frame, "y", ["c"])
    assert np.allclose(r.to_numpy(), 0.0, atol=1e-9)
    assert list(r.index) == [0, 1, 2, 3]


def test_residualize_drops_rows_missing_control_or_col():
    frame = pd.DataFrame({"c": [1.0, np.nan, 3.0], "y": [1.0, 2.0, np.nan]})
    r = residualize(frame, "y", ["c"])
    assert list(r.index) == [0]  # rows 1 (missing c) and 2 (missing y) dropped


def test_build_team_xg_table_shapes(tmp_path):
    # two teams, one game each direction -> opponent FIFA is the other team's
    pq = tmp_path / "tm.parquet"
    pd.DataFrame({
        "game_id": [1, 1], "team_id": ["A", "B"], "team_name": ["Aland", "Bland"],
        "sb_xg_for": [1.5, 0.5], "sb_xg_against": [0.5, 1.5],
        "goals_for": [1, 0], "goals_against": [0, 1],
        "model_xg_for_peak": [0.1, 0.1], "model_xg_against_peak": [0.1, 0.1],
        "model_xg_for_sum": [0.1, 0.1], "model_xg_against_sum": [0.1, 0.1],
        "model_xg_for_integral": [0.1, 0.1], "model_xg_against_integral": [0.1, 0.1],
    }).to_parquet(pq)
    cj = tmp_path / "chem.json"
    cj.write_text(pd.DataFrame({
        "team_id": ["A", "B"], "team_name": ["Aland", "Bland"],
        "overall": [80, 70], "mean_caps": [40, 30],
        "n_strong_def": [10, 4], "mean_aw_joi90_all": [0.3, 0.2], "stage_int": [8, 2],
    }).to_json(orient="records"))
    t = build_team_xg_table(str(pq), str(cj))
    assert set(t["team_id"]) == {"A", "B"}
    a = t.set_index("team_id").loc["A"]
    assert a["games"] == 1 and abs(a["xga_pm"] - 0.5) < 1e-9
    assert a["opp_fifa"] == 70 and bool(a["is_semifinalist"]) is True
    assert bool(t.set_index("team_id").loc["B"]["is_semifinalist"]) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd research && PYTHONPATH=src uv run pytest tests/test_xg_site_data.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'xg.site_data'`

- [ ] **Step 3: Write minimal implementation**

```python
# research/src/xg/site_data.py
"""Assemble the per-team xG-vs-chemistry table and residualize for the site panel."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

CONTROLS = ["overall", "mean_caps", "games", "opp_fifa"]


def residualize(frame: pd.DataFrame, col: str, controls: list[str]) -> pd.Series:
    """OLS residual of `col` on `controls`, over rows where all are present.

    Returns a Series indexed by the surviving rows of `frame`.
    """
    sub = frame.dropna(subset=[col, *controls])
    X = sub[list(controls)].to_numpy(dtype=float)
    y = sub[col].to_numpy(dtype=float)
    pred = LinearRegression().fit(X, y).predict(X)
    return pd.Series(y - pred, index=sub.index)


def build_team_xg_table(parquet_path: str, chem_json_path: str) -> pd.DataFrame:
    """One row per team: games, per-match xG-for/against, opponent FIFA, chemistry, stage."""
    df = pd.read_parquet(parquet_path)
    df["team_id"] = df["team_id"].astype(str)

    chem = pd.DataFrame(json.loads(Path(chem_json_path).read_text()))
    chem["team_id"] = chem["team_id"].astype(str)
    for c in ["overall", "mean_caps", "n_strong_def", "mean_aw_joi90_all", "stage_int"]:
        chem[c] = pd.to_numeric(chem.get(c), errors="coerce")

    fifa = chem.set_index("team_id")["overall"].to_dict()
    opp: dict[str, list] = {}
    for _, g in df.groupby("game_id"):
        ids = list(g["team_id"])
        if len(ids) == 2:
            opp.setdefault(ids[0], []).append(fifa.get(ids[1]))
            opp.setdefault(ids[1], []).append(fifa.get(ids[0]))
    opp_fifa = {t: (np.nanmean(v) if len(v) else np.nan) for t, v in opp.items()}

    team = (
        df.groupby(["team_id", "team_name"])
        .agg(games=("game_id", "nunique"),
             xg_for=("sb_xg_for", "sum"),
             xg_against=("sb_xg_against", "sum"))
        .reset_index()
    )
    team["xg_for_pm"] = team["xg_for"] / team["games"]
    team["xga_pm"] = team["xg_against"] / team["games"]
    team["opp_fifa"] = team["team_id"].map(opp_fifa)
    team = team.merge(
        chem[["team_id", "overall", "mean_caps", "n_strong_def", "mean_aw_joi90_all", "stage_int"]],
        on="team_id", how="left",
    )
    team["is_semifinalist"] = team["stage_int"] >= 6
    return team
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd research && PYTHONPATH=src uv run pytest tests/test_xg_site_data.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd /Users/nick/wc2026-tracking-transformer
git add research/src/xg/site_data.py research/tests/test_xg_site_data.py
git commit -m "xg: site-data helpers (residualize + team xG table)"
git branch --show-current   # must print spec/xg-grounding
```

---

### Task 2: Build script → `chemistry_xg.json`

**Files:**
- Create: `research/scripts/build_chemistry_xg_site_data.py`
- Output: `research/site/data/chemistry_xg.json`

- [ ] **Step 1: Write the build script**

```python
# research/scripts/build_chemistry_xg_site_data.py
"""Build research/site/data/chemistry_xg.json — paired offense/defense added-variable
points + partial-r + bootstrap CIs grounding chemistry in expected goals over/under expected.

    PYTHONPATH=src uv run python research/scripts/build_chemistry_xg_site_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))

from xg.site_data import CONTROLS, build_team_xg_table, residualize  # noqa: E402

PARQUET = REPO / "research/data/xg_grounding_team_match.parquet"
CHEM = REPO / "research/site/data/team_chemistry_vs_paper.json"
OUT = REPO / "research/site/data/chemistry_xg.json"


def added_variable(team, chem_col, outcome_col, *, flip_outcome):
    """Residualize chem and outcome on CONTROLS; return (r, ci90, points-DataFrame)."""
    sub = team.dropna(subset=[chem_col, outcome_col, *CONTROLS]).copy()
    rx = residualize(sub, chem_col, CONTROLS)
    ry = residualize(sub, outcome_col, CONTROLS)
    if flip_outcome:
        ry = -ry
    rxv, ryv = rx.to_numpy(), ry.to_numpy()
    r = float(np.corrcoef(rxv, ryv)[0, 1])
    rng = np.random.default_rng(0)
    n = len(rxv)
    boots = [np.corrcoef(rxv[s], ryv[s])[0, 1]
             for s in (rng.integers(0, n, n) for _ in range(2000))]
    lo, hi = (float(v) for v in np.percentile(boots, [5, 95]))
    sub = sub.assign(_chem_adj=rxv, _out_adj=ryv)
    return r, [lo, hi], sub


def main() -> None:
    team = build_team_xg_table(str(PARQUET), str(CHEM))
    r_def, ci_def, dsub = added_variable(team, "n_strong_def", "xga_pm", flip_outcome=True)
    r_off, ci_off, osub = added_variable(team, "mean_aw_joi90_all", "xg_for_pm", flip_outcome=False)

    by_id = {}
    for _, row in dsub.iterrows():
        by_id[row["team_id"]] = {
            "team_id": row["team_id"], "team_name": row["team_name"],
            "is_semifinalist": bool(row["is_semifinalist"]),
            "def_chem_adj": round(float(row["_chem_adj"]), 4),
            "xg_prevented_over_expected": round(float(row["_out_adj"]), 4),
        }
    for _, row in osub.iterrows():
        by_id.setdefault(row["team_id"], {"team_id": row["team_id"],
                         "team_name": row["team_name"],
                         "is_semifinalist": bool(row["is_semifinalist"])})
        by_id[row["team_id"]]["off_chem_adj"] = round(float(row["_chem_adj"]), 4)
        by_id[row["team_id"]]["xg_added_over_expected"] = round(float(row["_out_adj"]), 4)

    payload = {
        "meta": {
            "n_teams": int(len(by_id)),
            "controls": "FIFA-23 Overall + mean caps + games played + opponent FIFA",
            "defense": {"partial_r": round(r_def, 3), "ci90": [round(ci_def[0], 3), round(ci_def[1], 3)]},
            "offense": {"partial_r": round(r_off, 3), "ci90": [round(ci_off[0], 3), round(ci_off[1], 3)]},
        },
        "teams": sorted(by_id.values(), key=lambda t: t["team_name"]),
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT}  n={payload['meta']['n_teams']}  "
          f"def r={r_def:+.3f} {ci_def}  off r={r_off:+.3f} {ci_off}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the build script**

Run: `cd /Users/nick/wc2026-tracking-transformer && PYTHONPATH=src uv run python research/scripts/build_chemistry_xg_site_data.py`
Expected: `wrote .../chemistry_xg.json  n=29  def r=+0.381 [0.08..., 0.64...]  off r=+0.156 [...]`
(n must be 29; def r must round to +0.38; if either differs, STOP — the data or controls drifted.)

- [ ] **Step 3: Sanity-check the JSON**

Run: `PYTHONPATH=src uv run python -c "import json; d=json.load(open('research/site/data/chemistry_xg.json')); print(d['meta']); semis=[t['team_name'] for t in d['teams'] if t['is_semifinalist']]; print('semis:', sorted(semis))"`
Expected: `meta` shows n_teams 29, defense partial_r 0.381; semis == `['Argentina', 'Croatia', 'France', 'Morocco']`.

- [ ] **Step 4: Commit**

```bash
git add research/scripts/build_chemistry_xg_site_data.py research/site/data/chemistry_xg.json
git commit -m "xg: build chemistry_xg.json (added-variable offense/defense points + CIs)"
git branch --show-current   # must print spec/xg-grounding
```

---

### Task 3: Front-end renderer (`chemistry-wins.js`)

**Files:**
- Modify: `research/site/assets/js/chemistry-wins.js` (add after `renderTcdScatter`, ~line 114)

- [ ] **Step 1: Add the panel loader + continuous-axis scatter renderer**

Insert immediately after the closing `}` of `renderTcdScatter` (line 114), before the `/* team network renderers */` block:

```javascript
/* ---------------- chemistry → expected-goals panel (added-variable) ---------------- */

const xgPanelEl = document.getElementById("chem-xg-panel");
if (xgPanelEl) {
  loadJSON("data/chemistry_xg.json").then((xg) => renderChemistryXgPanel(xg)).catch(() => {});
}

function renderChemistryXgPanel(xg) {
  const defRows = xg.teams.filter((t) => t.def_chem_adj != null && t.xg_prevented_over_expected != null);
  const offRows = xg.teams.filter((t) => t.off_chem_adj != null && t.xg_added_over_expected != null);
  const defEl = document.getElementById("chem-xg-def");
  const offEl = document.getElementById("chem-xg-off");
  if (defEl) renderXgScatter(defEl, defRows, {
    xKey: "def_chem_adj", yKey: "xg_prevented_over_expected",
    xLabel: "Defensive chemistry (talent & schedule adjusted) →",
    yTop: "prevents more than expected", yBot: "concedes more than expected",
    r: xg.meta.defense.partial_r, ci: xg.meta.defense.ci90, n: xg.meta.n_teams,
    blurb: "More strong defensive partnerships → fewer expected goals conceded than talent predicts.",
  });
  if (offEl) renderXgScatter(offEl, offRows, {
    xKey: "off_chem_adj", yKey: "xg_added_over_expected",
    xLabel: "Offensive chemistry (talent & schedule adjusted) →",
    yTop: "creates more than expected", yBot: "creates less than expected",
    r: xg.meta.offense.partial_r, ci: xg.meta.offense.ci90, n: xg.meta.n_teams,
    blurb: "Stronger attacking partnerships trend toward more expected goals — entangled with talent.",
  });
}

function renderXgScatter(mountEl, rows, opt) {
  const W = 540, H = 440;
  const padL = 58, padR = 26, padT = 20, padB = 64;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const xs = rows.map((r) => r[opt.xKey]), ys = rows.map((r) => r[opt.yKey]);
  const xpad = (Math.max(...xs) - Math.min(...xs)) * 0.12 || 1;
  const ypad = (Math.max(...ys) - Math.min(...ys)) * 0.12 || 1;
  const xmin = Math.min(...xs) - xpad, xmax = Math.max(...xs) + xpad;
  const ymin = Math.min(...ys) - ypad, ymax = Math.max(...ys) + ypad;
  const sx = (x) => padL + ((x - xmin) / (xmax - xmin)) * innerW;
  const sy = (y) => padT + innerH - ((y - ymin) / (ymax - ymin)) * innerH;

  // zero reference lines (both axes are residuals → 0 = "exactly as expected")
  const zeroX = (xmin < 0 && xmax > 0) ? `<line x1="${sx(0).toFixed(1)}" y1="${padT}" x2="${sx(0).toFixed(1)}" y2="${padT + innerH}" stroke="currentColor" stroke-width="0.5" opacity="0.18" stroke-dasharray="3 3"/>` : "";
  const zeroY = (ymin < 0 && ymax > 0) ? `<line x1="${padL}" y1="${sy(0).toFixed(1)}" x2="${W - padR}" y2="${sy(0).toFixed(1)}" stroke="currentColor" stroke-width="0.5" opacity="0.18" stroke-dasharray="3 3"/>` : "";

  // least-squares trend line over the residual cloud
  const n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; }
  const slope = sxx ? sxy / sxx : 0, intc = my - slope * mx;
  const trend = `<line x1="${sx(xmin).toFixed(1)}" y1="${sy(intc + slope * xmin).toFixed(1)}" x2="${sx(xmax).toFixed(1)}" y2="${sy(intc + slope * xmax).toFixed(1)}" stroke="#d4a23a" stroke-width="2" opacity="0.85"/>`;

  const dots = rows.map((r) => {
    const cx = sx(r[opt.xKey]), cy = sy(r[opt.yKey]);
    const ring = r.is_semifinalist ? `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="8" fill="none" stroke="#d4a23a" stroke-width="2"/>` : "";
    const fill = r.is_semifinalist ? "#d4a23a" : "#6b7280";
    return `${ring}<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5" fill="${fill}" stroke="var(--bg, #0b1220)" stroke-width="1.1"/>`;
  }).join("");

  // label only the semifinalists (keep the small panels readable)
  const labels = rows.filter((r) => r.is_semifinalist).map((r) => {
    const cx = sx(r[opt.xKey]), cy = sy(r[opt.yKey]);
    const anchor = cx > padL + innerW * 0.6 ? "end" : "start";
    const dx = anchor === "start" ? 8 : -8;
    return `<text x="${(cx + dx).toFixed(1)}" y="${(cy - 7).toFixed(1)}" font-size="11" font-weight="700" fill="currentColor" opacity="0.92" text-anchor="${anchor}">${escapeHTML(r.team_name)}</text>`;
  }).join("");

  const yTopLbl = `<text x="${padL - 8}" y="${padT + 10}" font-size="10.5" fill="currentColor" opacity="0.55" text-anchor="end">${opt.yTop} ↑</text>`;
  const yBotLbl = `<text x="${padL - 8}" y="${padT + innerH - 2}" font-size="10.5" fill="currentColor" opacity="0.55" text-anchor="end">↓ ${opt.yBot}</text>`;
  const xLbl = `<text x="${(padL + innerW / 2).toFixed(0)}" y="${H - padB + 40}" font-size="11.5" fill="currentColor" opacity="0.6" text-anchor="middle">${opt.xLabel}</text>`;
  const rTxt = (opt.r >= 0 ? "+" : "") + opt.r.toFixed(2);

  mountEl.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="fifa-scatter-svg" role="img" aria-label="${escapeHTML(opt.xLabel)} added-variable scatter">
      ${zeroX}${zeroY}${trend}${dots}${labels}${yTopLbl}${yBotLbl}${xLbl}
    </svg>
    <div class="scatter-legend small muted">
      <span class="muted">${escapeHTML(opt.blurb)}</span>
      <span class="muted">Partial r = <strong>${rTxt}</strong> &nbsp;(90% CI ${opt.ci[0].toFixed(2)} to ${opt.ci[1].toFixed(2)}, n = ${opt.n}); both axes adjusted for talent, caps, games &amp; opponent strength.</span>
    </div>`;
}
```

- [ ] **Step 2: Bump the cache-bust tag**

In `research/site/chemistry-wins.html` line 1103, change the script src query string:

```html
<script type="module" src="assets/js/chemistry-wins.js?v=xg-panel"></script>
```

- [ ] **Step 3: Verify the JS parses (no syntax errors)**

Run: `node --check research/site/assets/js/chemistry-wins.js`
Expected: no output (exit 0). (If `node` errors on the `import`, ignore import resolution — `--check` only parses syntax; a clean exit means valid syntax.)

- [ ] **Step 4: Commit**

```bash
git add research/site/assets/js/chemistry-wins.js research/site/chemistry-wins.html
git commit -m "chemistry-wins: render chemistry→xG added-variable panel; bump cache-bust"
git branch --show-current   # must print spec/xg-grounding
```

---

### Task 4: HTML host markup (`chemistry-wins.html`)

**Files:**
- Modify: `research/site/chemistry-wins.html:55-57` (insert panel above TCD scatter; caption the TCD scatter as legacy)

- [ ] **Step 1: Insert the paired-panel sub-section and re-caption the TCD scatter**

Replace lines 55-57 (the TCD `<h3>`, its `<p>`, and the `<div id="chem-vs-result-scatter">`) with the new panel first, then the captioned TCD scatter:

```html
      <h3 class="mt-2">Chemistry, grounded in expected goals</h3>
      <p class="dim small">Each dot = one WC22 team (n = 29). These are <strong>added-variable plots</strong>:
        both axes are adjusted for talent (FIFA-23 Overall + caps), games played, and opponent strength —
        so the trend you see <em>is</em> the effect of chemistry after talent and schedule are removed.
        Up = better than expected; right = more chemistry than talent predicts. Gold ring = semifinalist.</p>
      <div id="chem-xg-panel" class="xg-panel-grid">
        <figure class="xg-panel-cell">
          <figcaption class="small"><strong>Defensive chemistry → expected goals prevented</strong></figcaption>
          <div id="chem-xg-def" class="fifa-scatter"></div>
        </figure>
        <figure class="xg-panel-cell">
          <figcaption class="small"><strong>Offensive chemistry → expected goals added</strong></figcaption>
          <div id="chem-xg-off" class="fifa-scatter"></div>
        </figure>
      </div>

      <h3 class="mt-2">TCD vs tournament finish &nbsp;<span class="dim small">(ρ = +0.704, n = 31, p &lt; 0.001)</span></h3>
      <p class="dim small">Older, talent-confounded view: X = raw TCD, Y = stage reached (Group &rarr; Winner).
        Predictive, but talent and chemistry are entangled here — the xG panels above isolate chemistry's
        share. Gold ring = WC22 semifinalist.</p>
      <div id="chem-vs-result-scatter" class="fifa-scatter"></div>
```

- [ ] **Step 2: Add minimal grid CSS for the paired panel**

In the same file, find the `<style>` block (search for `.fifa-scatter` or the first `<style>`); append inside it:

```css
.xg-panel-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.4rem; margin: 0.6rem 0 1.6rem; }
.xg-panel-cell { margin: 0; }
.xg-panel-cell figcaption { margin-bottom: 0.4rem; opacity: 0.85; }
@media (max-width: 760px) { .xg-panel-grid { grid-template-columns: 1fr; } }
```

If `chemistry-wins.html` has no inline `<style>` block, instead add the rules to the shared stylesheet it links (search the `<head>` for `<link rel="stylesheet"`); append there.

- [ ] **Step 3: Verify the page loads with the panel**

Run: `cd /Users/nick/wc2026-tracking-transformer/research/site && python3 -m http.server 8745 >/dev/null 2>&1 &` then `sleep 1 && curl -s "http://localhost:8745/chemistry-wins.html" | grep -c "chem-xg-panel"`
Expected: `1` (the panel div is present). Then kill the server: `kill %1 2>/dev/null` (or `pkill -f "http.server 8745"`).

- [ ] **Step 4: Eyeball in a browser**

Open `http://localhost:8745/chemistry-wins.html` (restart the server if killed). Confirm: two side-by-side scatters appear above the TCD scatter; gold-ringed semifinalists sit upper-right in the defense panel; trend lines slope up; legends show "Partial r = +0.38" (defense) and "+0.16" (offense); the TCD scatter still renders below with its "older, talent-confounded view" caption.

- [ ] **Step 5: Commit**

```bash
git add research/site/chemistry-wins.html
git commit -m "chemistry-wins: paired chemistry→xG panel above TCD scatter; legacy caption"
git branch --show-current   # must print spec/xg-grounding
```

---

### Task 5: Final review

- [ ] **Step 1: Run the xg test suite + confirm no regressions**

Run: `cd /Users/nick/wc2026-tracking-transformer/research && PYTHONPATH=src uv run pytest tests/test_xg_site_data.py tests/test_xg_grounding.py -q`
Expected: all pass.

- [ ] **Step 2: Confirm the live site data was untouched (additive only)**

Run: `cd /Users/nick/wc2026-tracking-transformer && git status --porcelain research/site/data/team_chemistry_vs_paper.json`
Expected: empty output (the shared 4-page JSON was NOT modified — we only added `chemistry_xg.json`).

- [ ] **Step 3: Final diff review**

Run: `git log --oneline -5 && git diff --stat HEAD~4`
Confirm only the intended files changed (site_data.py, test, build script, chemistry_xg.json, chemistry-wins.js, chemistry-wins.html) and nothing under other site pages.

---

## Self-Review

**Spec coverage:** paired panel (Task 3/4) ✓; added-variable both-axes residual decision (Task 2/3) ✓; clean titles, no hedge labels (Task 4 figcaptions) ✓; additive above TCD with legacy caption (Task 4) ✓; build script + tested helpers (Task 1/2) ✓; cache-bust bump (Task 3) ✓; don't touch other pages / shared JSON (Task 5 guard) ✓.

**Placeholder scan:** all code blocks are complete; expected numeric outputs (n=29, r=+0.38) are real (validated inline). No TBDs.

**Type consistency:** JSON keys (`def_chem_adj`, `xg_prevented_over_expected`, `off_chem_adj`, `xg_added_over_expected`, `is_semifinalist`, `meta.defense.partial_r/ci90`, `meta.offense.*`, `meta.n_teams`) match between Task 2 (writer) and Task 3 (reader). Function names `residualize`/`build_team_xg_table`/`added_variable`/`renderXgScatter`/`renderChemistryXgPanel` consistent across tasks.
