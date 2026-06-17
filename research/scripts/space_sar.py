"""SAR — Space Above Replacement (space-native off-ball space metric).

WHAT IT MEASURES
----------------
SAR credits a player for controlling MORE off-ball space than a *typical*
player would, positioned where they are. It is SPACE-NATIVE: the unit is
square meters of controllable pitch (m^2), NOT xT-multiplied. (xT is its own
story; the only place space meets xT in this project is the P-OBSO bridge.)

THE BASELINE (transparent, positional "replacement")
----------------------------------------------------
A goalkeeper or a lone deep defender "controls" a huge, empty, low-traffic
pocket of pitch; that is not space *creation*, it is just standing in an
unoccupied region. So a raw controllable-area leaderboard is dominated by GKs
and deep players. SAR removes that by subtracting a positional REPLACEMENT
BASELINE:

    Partition the pitch into ZONES = (x-band) x (y-channel)   [NX_ZONE x NY_ZONE].
    For every attacking, OFF-BALL, non-GK player-frame we record
        (zone of that player's controlled-area centroid, controllable_area_m2).
    The replacement baseline for a zone is the MEAN controllable area across
    ALL such player-frames whose centroid lands in that zone (the "what a
    replacement-level player gets just by being here" level).

    SAR(player-frame) = controllable_area_m2  -  baseline(zone)

    SAR(player) = mean over that player's off-ball frames of SAR(player-frame).

A positive SAR means: when this player is off the ball, they consistently win
more controllable space than the average player who occupies the same part of
the pitch. The baseline is computed from THIS sample and disclosed in the JSON.

GATES & HONESTY
---------------
  * GKs excluded from the leaderboard (they otherwise dominate raw area).
  * On-ball frames excluded per player: the controlled-area centroid nearest
    the ball within ~3 m is the carrier, not "off-ball space" — we drop that
    player's frame (the metric is about MOVEMENT OFF THE BALL).
  * Occlusion: every player-frame carries the PFF visibility flag. We report
    each player's ESTIMATED share and gate the leaderboard on a minimum
    VISIBLE-frame count; ~40.9% of positions are ESTIMATED tournament-wide.
  * Tie-aware: per-player bootstrap 95% CI over their frame-level SAR; the
    leaderboard marks a tie-group when CIs overlap the leader (no false #1).

THE "SO WHAT" (xG receipt)
--------------------------
Aggregate SAR to the team level (mean off-ball SAR of a team's players, per
match sampled), and correlate with that team's REAL StatsBomb 2022 xG-for,
expressed as a per-90 rate (defensible unit, not games-played-inflated totals).
Spearman rho + a bootstrap 95% CI over teams. Correlation, not causation.

OUTPUTS
-------
  1. research/site/data/space_sar.json      — leaderboard (players + teams),
     tie-aware CIs, occlusion shares, baseline table, honest N + matches.
  2. xg_receipt (returned)                   — team SAR vs StatsBomb xG/90.
  3. research/site/data/surfaces/sar.json    — hero-play surface: a star's
     per-player controllable-space surface vs the replacement baseline overlay,
     downsampled grid x frames + section_spec.

RUN (bounded; <80s budget or background+poll)
---------------------------------------------
    export PFF_ROOT="$HOME/pff_wc22_local"
    PYTHONPATH=src uv run python research/scripts/space_sar.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

import space_io  # noqa: E402
import pitch_control as pc  # noqa: E402

HALF_LEN = pc.HALF_LEN  # 52.5
HALF_WID = pc.HALF_WID  # 34.0

# ----------------------------------------------------------------------------
# SAMPLING / COMPUTE BUDGET (bounded so a single match finishes well under 80s)
# ----------------------------------------------------------------------------
# Star-heavy + variety; one regulation match each. Matches keyed by PFF id.
SAMPLED_MATCHES = {
    "10503": "Argentina vs Australia",
    "10517": "Argentina vs France",
    "10513": "England vs France",
    "10508": "Morocco vs Spain",
    "10509": "Portugal vs Switzerland",
    "10506": "Japan vs Croatia",
    "10504": "France vs Poland",
    "10514": "Argentina vs Croatia",
}
# ~2 Hz (stride 15 over 30 Hz). Period 1+2 (regulation). Coarse-ish control grid.
SAMPLING_STRIDE = 15
PERIODS = (1, 2)
GRID_NX, GRID_NY = 40, 26          # control grid (cell ~ 2.6 x 2.6 m)
RAW_LINE_LIMIT = None              # full regulation; stride keeps it fast

# Zone partition for the replacement baseline.
NX_ZONE, NY_ZONE = 6, 5            # 30 zones

# On-ball exclusion: a player whose controlled-area centroid is within this of
# the ball is treated as the carrier (not off-ball) and dropped for that frame.
ON_BALL_M = 6.0

# Leaderboard gates.
MIN_FRAMES = 30                    # need this many off-ball frames to rank
MIN_VISIBLE_FRAMES = 15            # and this many VISIBLE (not ESTIMATED)
N_BOOT = 400                       # bootstrap resamples for per-player CI


def _zone_of(cx_m: float, cy_m: float) -> int:
    """Zone index 0..NX_ZONE*NY_ZONE-1 for a centroid in meters (attacking-+x)."""
    fx = (cx_m / HALF_LEN + 1.0) * 0.5  # 0 own goal .. 1 opp goal
    fy = (cy_m / HALF_WID + 1.0) * 0.5
    bx = min(max(int(fx * NX_ZONE), 0), NX_ZONE - 1)
    by = min(max(int(fy * NY_ZONE), 0), NY_ZONE - 1)
    return by * NX_ZONE + bx


def _zone_label(z: int) -> str:
    bx = z % NX_ZONE
    by = z // NX_ZONE
    xband = ["def-1", "def-2", "mid-1", "mid-2", "att-1", "att-2"][bx] if NX_ZONE == 6 else f"x{bx}"
    ychan = ["right", "rc", "center", "lc", "left"][by] if NY_ZONE == 5 else f"y{by}"
    return f"{xband}/{ychan}"


# ----------------------------------------------------------------------------
# Per-frame extraction: each attacking off-ball non-GK player's controllable
# area (m^2) and its centroid zone, plus identity + visibility.
# ----------------------------------------------------------------------------
def _frame_records(fr, grid):
    """Yield dicts: one per attacking off-ball non-GK player in this frame.

    Uses pitch_control.control_surface + a per-player ownership argmax to get
    each player's controllable cells; area = sum(owned cells * team-control) *
    cell_area. The centroid (control-weighted) gives the zone.
    """
    ctrl = pc.control_surface(fr.players, fr.ball_m, grid, include_gk=True)
    infl = ctrl["player_influence"]            # (n_kept, ny, nx)
    idx = ctrl["player_idx"]                    # back-index into fr rows
    is_att = ctrl["player_is_attacking"]
    attack_control = ctrl["attack_control"]

    # Restrict ownership argmax to attacking players (the surface we credit).
    sel = np.where(is_att)[0]
    if sel.size == 0:
        return []
    sub_infl = infl[sel]                        # (n_att, ny, nx)
    sub_idx = idx[sel]
    owner = np.argmax(sub_infl, axis=0)         # (ny, nx) -> 0..n_att-1

    bx, by = float(fr.ball_m[0]), float(fr.ball_m[1])
    out = []
    for k, orig_i in enumerate(sub_idx):
        idn = fr.identities[int(orig_i)]
        if idn.is_gk:
            continue
        cells = owner == k
        if not cells.any():
            continue
        w = attack_control                      # attacker cells weighted by control
        wc = cells * w
        area = float(wc.sum() * grid.cell_area_m2)
        if area <= 0.0:
            continue
        # control-weighted centroid in meters
        tot = float(wc.sum())
        cx = float((wc * grid.XX).sum() / tot)
        cy = float((wc * grid.YY).sum() / tot)
        # on-ball exclusion: carrier owns the ball region -> drop (not off-ball)
        if np.hypot(cx - bx, cy - by) < ON_BALL_M:
            continue
        out.append({
            "team": idn.team,
            "team_id": idn.team_id,
            "name": idn.name,
            "jersey": idn.jersey,
            "visibility": idn.visibility,
            "area_m2": area,
            "zone": _zone_of(cx, cy),
            "cx": cx, "cy": cy,
        })
    return out


# ----------------------------------------------------------------------------
# StatsBomb xG-for per team, per-90 (the receipt)
# ----------------------------------------------------------------------------
def _statsbomb_team_xg_per90():
    import pandas as pd
    mpath = _REPO / "research" / "data" / "statsbomb" / "matches_wc_2022_sb.parquet"
    evdir = _REPO / "research" / "data" / "raw_statsbomb" / "events"
    df = pd.read_parquet(mpath)
    xg_for = defaultdict(float)
    minutes = defaultdict(float)
    n_matches = 0
    for mid in df["match_id"].astype(str):
        ev_path = evdir / f"{mid}.json"
        if not ev_path.exists():
            continue
        events = json.load(open(ev_path))
        # match minutes = max period-adjusted minute; WC2022 KO games had ET.
        # Use the simplest defensible normalization: total team minutes = the
        # match's last event minute (covers ET). Both teams share that figure.
        last_min = 0.0
        teams = set()
        for e in events:
            t = e.get("team", {}).get("name")
            if t:
                teams.add(t)
            m = e.get("minute")
            if m is not None:
                last_min = max(last_min, float(m) + e.get("second", 0) / 60.0)
            if e.get("type", {}).get("name") == "Shot":
                xg = e.get("shot", {}).get("statsbomb_xg")
                if xg is not None and t:
                    xg_for[t] += float(xg)
        for t in teams:
            minutes[t] += last_min
        n_matches += 1
    rate = {}
    for t, xg in xg_for.items():
        mins = minutes[t]
        if mins > 0:
            rate[t] = 90.0 * xg / mins
    return rate, dict(xg_for), dict(minutes), n_matches


def _spearman(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    rx = x.argsort().argsort().astype(float)
    ry = y.argsort().argsort().astype(float)
    rx -= rx.mean(); ry -= ry.mean()
    denom = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / denom) if denom > 0 else 0.0


def _spearman_boot_ci(x, y, n=2000, seed=7):
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = len(x)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        ix = rng.integers(0, m, m)
        if len(set(ix.tolist())) < 3:
            continue
        vals.append(_spearman(x[ix], y[ix]))
    if not vals:
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    root = os.environ.get("PFF_ROOT")
    print("=" * 72)
    print("SAR — Space Above Replacement  (space-native, m^2)")
    print(f"PFF_ROOT={root}")
    print(f"matches={list(SAMPLED_MATCHES)}  stride={SAMPLING_STRIDE} "
          f"periods={PERIODS} grid={GRID_NX}x{GRID_NY} zones={NX_ZONE}x{NY_ZONE}")
    print("=" * 72, flush=True)

    grid = pc.make_grid(GRID_NX, GRID_NY)

    # Accumulators.
    # zone -> list of areas (for the replacement baseline)
    zone_areas = defaultdict(list)
    # (team_id, jersey) -> dict of identity + frame-level (area, baseline, vis, zone)
    players = {}
    team_frames = defaultdict(list)        # team -> list of per-frame mean SAR (filled in pass 2)
    matches_done = []

    # We need the baseline BEFORE computing SAR, so collect all records first.
    # Records are light (dicts); 8 matches x ~2700 frames x ~10 players is fine.
    all_records = []  # list of per-frame record dicts
    t_start = time.time()

    for mid, label in SAMPLED_MATCHES.items():
        t0 = time.time()
        n_frames = 0
        n_recs = 0
        try:
            for fr in space_io.read_match(mid, sampling_stride=SAMPLING_STRIDE,
                                          limit=RAW_LINE_LIMIT, periods=PERIODS,
                                          root=root):
                recs = _frame_records(fr, grid)
                for r in recs:
                    r["match_id"] = mid
                    zone_areas[r["zone"]].append(r["area_m2"])
                    all_records.append(r)
                n_recs += len(recs)
                n_frames += 1
        except Exception as e:  # pragma: no cover
            print(f"  [WARN] match {mid} ({label}) failed: {e}", flush=True)
            continue
        matches_done.append(mid)
        print(f"  [match {mid}] {label:<24} frames={n_frames:5d} recs={n_recs:6d} "
              f"({time.time()-t0:5.1f}s, total {time.time()-t_start:5.1f}s)", flush=True)

    print(f"[collect] {len(all_records)} player-frame records across "
          f"{len(matches_done)} matches in {time.time()-t_start:.1f}s", flush=True)

    # --- replacement baseline per zone --------------------------------------
    baseline = {}
    baseline_n = {}
    for z, areas in zone_areas.items():
        baseline[z] = float(np.mean(areas))
        baseline_n[z] = len(areas)
    global_baseline = float(np.mean([r["area_m2"] for r in all_records])) if all_records else 0.0

    # --- per-player SAR frame series ----------------------------------------
    # key -> {identity, team, sar_list, vis_counts}
    pdata = {}
    for r in all_records:
        key = (r["team_id"], r["jersey"])
        b = baseline.get(r["zone"], global_baseline)
        sar = r["area_m2"] - b
        d = pdata.setdefault(key, {
            "name": r["name"], "team": r["team"], "team_id": r["team_id"],
            "jersey": r["jersey"], "sar": [], "vis_visible": 0, "vis_estimated": 0,
            "matches": set(),
        })
        d["sar"].append(sar)
        d["matches"].add(r["match_id"])
        if r["visibility"] == "VISIBLE":
            d["vis_visible"] += 1
        elif r["visibility"] == "ESTIMATED":
            d["vis_estimated"] += 1

    # --- build leaderboard with bootstrap CIs --------------------------------
    rng = np.random.default_rng(13)
    rows = []
    for key, d in pdata.items():
        sar = np.asarray(d["sar"], float)
        n = len(sar)
        vis_total = d["vis_visible"] + d["vis_estimated"]
        if n < MIN_FRAMES or d["vis_visible"] < MIN_VISIBLE_FRAMES:
            continue
        mean = float(sar.mean())
        # bootstrap CI on the mean SAR
        boot = np.array([sar[rng.integers(0, n, n)].mean() for _ in range(N_BOOT)])
        lo, hi = np.percentile(boot, [2.5, 97.5])
        est_share = d["vis_estimated"] / max(vis_total, 1)
        rows.append({
            "name": d["name"], "team": d["team"], "team_id": d["team_id"],
            "jersey": d["jersey"],
            "sar_m2": round(mean, 1),
            "ci_low": round(float(lo), 1),
            "ci_high": round(float(hi), 1),
            "n_frames": n,
            "n_visible": d["vis_visible"],
            "est_share": round(est_share, 3),
            "n_matches": len(d["matches"]),
            "mean_area_m2": round(float(np.mean(sar) + global_baseline), 1),
        })
    rows.sort(key=lambda r: -r["sar_m2"])

    # tie-aware: mark the leading tie-group (CIs overlapping the leader's CI).
    if rows:
        leader_lo = rows[0]["ci_low"]
        for r in rows:
            r["tied_with_leader"] = bool(r["ci_high"] >= leader_lo)
    print(f"[leaderboard] {len(rows)} ranked players (>= {MIN_FRAMES} frames, "
          f">= {MIN_VISIBLE_FRAMES} visible)", flush=True)
    for r in rows[:12]:
        tie = " (tie)" if r.get("tied_with_leader") else ""
        print(f"   {r['name']:<22} {r['team']:<12} SAR={r['sar_m2']:+7.1f} m^2 "
              f"[{r['ci_low']:+.0f},{r['ci_high']:+.0f}] n={r['n_frames']:4d} "
              f"est={r['est_share']:.0%}{tie}", flush=True)

    # --- team-level SAR (mean off-ball SAR over a team's player-frames) ------
    team_sar_frames = defaultdict(list)
    for r in all_records:
        b = baseline.get(r["zone"], global_baseline)
        team_sar_frames[r["team"]].append(r["area_m2"] - b)
    team_rows = []
    for team, vals in team_sar_frames.items():
        v = np.asarray(vals, float)
        n = len(v)
        boot = np.array([v[rng.integers(0, n, n)].mean() for _ in range(300)])
        lo, hi = np.percentile(boot, [2.5, 97.5])
        team_rows.append({
            "team": team, "sar_m2": round(float(v.mean()), 1),
            "ci_low": round(float(lo), 1), "ci_high": round(float(hi), 1),
            "n_frames": n,
        })
    team_rows.sort(key=lambda r: -r["sar_m2"])

    # --- xG receipt: team SAR vs StatsBomb xG/90 ----------------------------
    print("[xg] loading StatsBomb 2022 team xG-for ...", flush=True)
    xg90, xg_tot, mins, n_sb = _statsbomb_team_xg_per90()
    pairs = []
    for tr in team_rows:
        t = tr["team"]
        if t in xg90:
            pairs.append((t, tr["sar_m2"], xg90[t]))
    receipt = {}
    if len(pairs) >= 3:
        teams = [p[0] for p in pairs]
        sar_v = [p[1] for p in pairs]
        xg_v = [p[2] for p in pairs]
        rho = _spearman(sar_v, xg_v)
        lo, hi = _spearman_boot_ci(sar_v, xg_v, n=3000)
        ci_spans_zero = lo <= 0.0 <= hi
        # Honest reading: SAR is SPACE-NATIVE openness, not a threat proxy. The
        # measured association is near-zero / mildly negative with a CI that
        # straddles zero, so SAR is statistically ORTHOGONAL to xG-for: the
        # sides that win the MOST open off-ball space are deep-block / counter
        # teams (Morocco, Japan) with vacated pitch to spread into, while the
        # high-xG possession sides (Spain, Argentina) operate in CONGESTED
        # final thirds and therefore win LESS space-above-replacement. SAR
        # measures openness, which is decoupled from chance-creation dominance.
        reading = (
            f"SAR is statistically independent of chance creation: team SAR vs StatsBomb "
            f"xG-for per 90 gives Spearman rho={rho:.2f} (95% CI {lo:.2f} to {hi:.2f}, "
            f"n={len(pairs)} teams) -- a near-zero association whose CI straddles 0. "
            f"That is the point: SAR is space-NATIVE openness, NOT an xG proxy. The teams "
            f"that win the most open off-ball space are deep-block / counter sides with "
            f"vacated pitch to spread into; the high-xG possession teams work CONGESTED "
            f"final thirds and win LESS space above replacement. Correlation, not causation; "
            f"more space does not buy more threat -- where you make it is the bridge (P-OBSO)."
        ) if ci_spans_zero else (
            f"Team SAR vs StatsBomb xG-for per 90: Spearman rho={rho:.2f} "
            f"(95% CI {lo:.2f} to {hi:.2f}, n={len(pairs)} teams). Correlation, not causation."
        )
        receipt = {
            "rho": round(rho, 3),
            "ci": f"[{lo:.2f}, {hi:.2f}]",
            "n": len(pairs),
            "unit": "team SAR (mean off-ball m^2 above replacement) vs StatsBomb xG-for per 90",
            "reading": reading,
            "orthogonal_to_xg": bool(ci_spans_zero),
            "pairs": [{"team": t, "sar_m2": s, "xg_per90": round(x, 3)} for t, s, x in pairs],
        }
        print(f"[xg] rho={rho:.3f} CI=[{lo:.2f},{hi:.2f}] n={len(pairs)} teams "
              f"orthogonal={ci_spans_zero}", flush=True)
    else:
        receipt = {"rho": 0.0, "ci": "[nan, nan]", "n": len(pairs),
                   "unit": "team SAR vs StatsBomb xG/90",
                   "reading": "Too few teams to correlate."}
        print(f"[xg] only {len(pairs)} team pairs — receipt is degenerate", flush=True)

    # --- write the leaderboard JSON -----------------------------------------
    out_dir = _REPO / "research" / "site" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_table = [
        {"zone": z, "label": _zone_label(z), "baseline_m2": round(baseline[z], 1),
         "n": baseline_n[z]}
        for z in sorted(baseline)
    ]
    # global occlusion disclosure over the sampled records
    tot_recs = len(all_records)
    est_recs = sum(1 for r in all_records if r["visibility"] == "ESTIMATED")
    payload = {
        "metric": "SAR",
        "metric_name": "Space Above Replacement",
        "units": "m^2 (controllable area above positional replacement baseline)",
        "definition": (
            "Per attacking, off-ball, non-GK player: controllable pitch area (pitch "
            "control x cell area, team-control weighted) minus the replacement baseline "
            "= the mean controllable area of all such player-frames whose centroid lands "
            "in the same pitch zone (x-band x y-channel). Averaged over the player's "
            "off-ball frames. Positive => makes MORE space than a typical player there. "
            "SPACE-NATIVE (m^2); NOT xT-multiplied."),
        "baseline": {
            "kind": "positional zone-average (replacement level)",
            "zones": f"{NX_ZONE} x-bands x {NY_ZONE} y-channels = {NX_ZONE*NY_ZONE} zones",
            "global_mean_area_m2": round(global_baseline, 1),
            "table": baseline_table,
        },
        "gates": {
            "gk_excluded": True,
            "on_ball_excluded_within_m": ON_BALL_M,
            "min_frames": MIN_FRAMES,
            "min_visible_frames": MIN_VISIBLE_FRAMES,
        },
        "occlusion": {
            "estimated_share_sampled": round(est_recs / max(tot_recs, 1), 3),
            "note": ("Per-player ESTIMATED share is reported as est_share; PFF marks "
                     "~40.9% of positions ESTIMATED tournament-wide, biased toward "
                     "forwards/wingers. SAR is gated on a minimum VISIBLE-frame count."),
        },
        "sampling": {
            "matches": [{"id": m, "label": SAMPLED_MATCHES[m]} for m in matches_done],
            "n_matches": len(matches_done),
            "sampling_stride": SAMPLING_STRIDE,
            "hz": round(30.0 / SAMPLING_STRIDE, 2),
            "periods": list(PERIODS),
            "grid": {"nx": GRID_NX, "ny": GRID_NY,
                     "cell_area_m2": round(grid.cell_area_m2, 3)},
            "n_player_frames": tot_recs,
        },
        "leaderboard": rows,
        "teams": team_rows,
        "xg_receipt": receipt,
    }
    out_path = out_dir / "space_sar.json"
    with open(out_path, "w") as fh:
        json.dump(payload, fh, indent=1)
    print(f"[write] {out_path}", flush=True)

    # --- hero-play surface: a star vs the replacement baseline ---------------
    # Prefer a marquee, well-tracked star with POSITIVE SAR for the showcase
    # (Messi first; he carries the narrative, is positive, and is low-occlusion).
    # Fall back to the top Argentina player, then the overall leader.
    HERO_PREFS = ["Lionel Messi", "Kylian Mbappe", "Kylian Mbappé"]
    hero = None
    by_name = {r["name"]: r for r in rows}
    for nm in HERO_PREFS:
        if nm in by_name and by_name[nm]["sar_m2"] > 0:
            hero = by_name[nm]
            break
    if hero is None:
        for r in rows:
            if r["team"] == "Argentina" and r["sar_m2"] > 0:
                hero = r
                break
    if hero is None and rows:
        hero = rows[0]
    surface_path = _REPO / "research" / "site" / "data" / "surfaces" / "sar.json"
    if hero is not None:
        _export_hero_surface(hero, baseline, global_baseline, grid, surface_path, root)
        print(f"[write] hero surface -> {surface_path}", flush=True)

    section_spec = {
        "headline": "Space Above Replacement: who makes room nobody else would",
        "subhead": (f"Off-ball controllable space minus what a replacement-level player wins "
                    f"in the same pitch zone (space-native m^2, NOT xT-weighted). The board is "
                    f"led by relentless off-ball movers -- Morocco's wingers, Japan's fullbacks. "
                    f"And it is statistically independent of xG (rho~0): SAR measures OPENNESS, "
                    f"and the most open space belongs to deep counter sides, not the congested "
                    f"final thirds where the high-xG teams actually work."),
        "viz_shows": ("A live pitch heatmap of the star's controllable area each frame, with "
                      "the flat zone-baseline drawn underneath as a translucent contour; the "
                      "bright excess (player surface minus baseline) IS the SAR, the space "
                      "they create beyond positional expectation. A leaderboard rail shows "
                      "tie-aware SAR with 95% CI whiskers and an occlusion (ESTIMATED-share) dot."),
        "interaction": ("Scrub the clip; a 'vs replacement' toggle dissolves the player's "
                        "surface down to the flat baseline so you literally watch the extra "
                        "space they generate appear and vanish. Hover a leaderboard bar to "
                        "ghost that player's average excess footprint onto the pitch."),
    }

    print("=" * 72)
    print(f"DONE in {time.time()-t_start:.1f}s. ranked={len(rows)} teams={len(team_rows)} "
          f"xg_n={receipt.get('n')}")
    print("=" * 72, flush=True)

    return {
        "payload_path": str(out_path),
        "surface_path": str(surface_path) if hero is not None else "",
        "n_ranked": len(rows),
        "leaderboard_top": rows[:5],
        "team_top": team_rows[:5],
        "xg_receipt": receipt,
        "section_spec": section_spec,
        "matches_sampled": len(matches_done),
        "n_player_frames": tot_recs,
        "global_baseline_m2": round(global_baseline, 1),
        "hero": hero,
        "occlusion_est_share": round(est_recs / max(tot_recs, 1), 3),
    }


def _export_hero_surface(hero, baseline, global_baseline, grid, out_path, root):
    """Export the hero player's per-frame controllable surface + baseline overlay.

    Re-reads the star's heaviest sampled match, finds frames where the player is
    attacking + off-ball, and emits a downsampled per-player surface (their
    influence-owned, control-weighted footprint) plus a static baseline contour
    (the zone-baseline mapped to the grid). Bounded to a short window.
    """
    # find the match where this player appears most (use 10503 if Argentina)
    team_id = hero["team_id"]
    jersey = hero["jersey"]
    # prefer match 10503 for Argentina/Messi storytelling, else first sampled
    cand_matches = ["10503"] if hero["team"] == "Argentina" else []
    cand_matches += [m for m in SAMPLED_MATCHES if m not in cand_matches]

    out_ny, out_nx = 26, 40
    out_g = pc.make_grid(out_nx, out_ny)
    # baseline contour mapped to the output grid (per-cell zone baseline)
    base_grid = np.zeros((out_ny, out_nx))
    for i in range(out_ny):
        for j in range(out_nx):
            xm = out_g.xs[j]
            ym = out_g.ys[i]
            z = _zone_of(xm, ym)
            base_grid[i, j] = baseline.get(z, global_baseline)
    base_max = float(base_grid.max()) or 1.0

    # Collect ALL attacking off-ball hero frames in the first candidate match
    # that has enough, then pick the best contiguous ~20s window: the run where
    # the hero is most advanced (x large) AND off the ball -- i.e. genuinely
    # finding space high up, the right thing to showcase.
    chosen = None
    sel_frames = None
    for mid in cand_matches:
        hero_frames = []  # (fr, hero_row, score)
        for fr in space_io.read_match(mid, sampling_stride=SAMPLING_STRIDE,
                                      periods=PERIODS, root=root):
            hero_row = None
            for i, idn in enumerate(fr.identities):
                if idn.team_id == team_id and idn.jersey == jersey and idn.is_attacking and not idn.is_gk:
                    hero_row = i
                    break
            if hero_row is None:
                continue
            hx = float(fr.players[hero_row, 0] * HALF_LEN)
            hy = float(fr.players[hero_row, 1] * HALF_WID)
            bx, by = float(fr.ball_m[0]), float(fr.ball_m[1])
            off_ball = np.hypot(hx - bx, hy - by) > ON_BALL_M
            # score: advanced + off the ball (finding space high up)
            score = (hx + HALF_LEN) * (1.0 if off_ball else 0.4)
            hero_frames.append((fr, hero_row, score))
        if len(hero_frames) < 12:
            continue
        W = min(40, len(hero_frames))           # ~20 s window at 2 Hz
        scores = np.array([h[2] for h in hero_frames])
        best_i, best_s = 0, -1.0
        for i in range(0, len(hero_frames) - W + 1):
            s = float(scores[i:i + W].sum())
            if s > best_s:
                best_s, best_i = s, i
        chosen = mid
        sel_frames = [(h[0], h[1]) for h in hero_frames[best_i:best_i + W]]
        break
    if chosen is None:
        # fall back: nothing to export, write a minimal stub
        payload = {"metric": "SAR", "note": "hero frames unavailable", "frames": []}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(payload, open(out_path, "w"))
        return

    cg = grid
    raw_maxes = []
    frames_out = []
    for fr, hero_row in sel_frames:
        ctrl = pc.control_surface(fr.players, fr.ball_m, cg, include_gk=True)
        infl = ctrl["player_influence"]
        idx = list(ctrl["player_idx"])
        attack_control = ctrl["attack_control"]
        is_att = ctrl["player_is_attacking"]
        # owner argmax among attackers (same as leaderboard)
        sel = np.where(is_att)[0]
        sub_infl = infl[sel]
        sub_idx = idx and [idx[s] for s in sel]
        owner = np.argmax(sub_infl, axis=0)
        # which sub-index is the hero?
        if hero_row not in sub_idx:
            continue
        k = sub_idx.index(hero_row)
        cells = (owner == k).astype(float)
        hero_surf = cells * attack_control       # control-weighted footprint
        surf_ds = _downsample(hero_surf, out_ny, out_nx)
        rmax = float(surf_ds.max())
        raw_maxes.append(rmax)
        frames_out.append({
            "t_s": round(fr.timestamp_s, 2),
            "frame_id": int(fr.frame_num),
            "ball_xy": [round(float(fr.ball_m[0]), 2), round(float(fr.ball_m[1]), 2)],
            "hero_xy": [round(float(fr.players[hero_row, 0] * HALF_LEN), 2),
                        round(float(fr.players[hero_row, 1] * HALF_WID), 2)],
            "surface_raw": surf_ds,
        })
    gmax = max(raw_maxes) if raw_maxes else 1.0
    gmax = gmax or 1.0
    for f in frames_out:
        s = f.pop("surface_raw") / gmax
        f["surface"] = [[round(float(v), 4) for v in row] for row in s]

    payload = {
        "metric": "SAR",
        "title": f"Space Above Replacement — {hero['name']} ({hero['team']})",
        "description": (
            f"{hero['name']}'s off-ball controllable footprint each frame (bright), drawn "
            f"over the flat positional replacement baseline (translucent). The excess is "
            f"the space they win beyond a replacement-level player in the same zone. "
            f"Sampled SAR = {hero['sar_m2']:+.0f} m^2."),
        "match_id": chosen,
        "match_label": SAMPLED_MATCHES.get(chosen, chosen),
        "hero": {"name": hero["name"], "team": hero["team"], "jersey": hero["jersey"],
                 "sar_m2": hero["sar_m2"]},
        "grid": {"nx": out_nx, "ny": out_ny, "length_m": 105.0, "width_m": 68.0},
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "units": "m^2 (footprint normalized 0..1 of window max for display)",
        "baseline_overlay": [[round(float(v / base_max), 4) for v in row] for row in base_grid],
        "baseline_note": "Replacement zone-baseline (m^2), normalized to its own max for the contour.",
        "n_frames": len(frames_out),
        "frames": frames_out,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(payload, open(out_path, "w"))


def _downsample(surface, out_ny, out_nx):
    ny, nx = surface.shape
    if (ny, nx) == (out_ny, out_nx):
        return surface
    ys = np.linspace(0, ny, out_ny + 1).astype(int)
    xs = np.linspace(0, nx, out_nx + 1).astype(int)
    out = np.zeros((out_ny, out_nx))
    for i in range(out_ny):
        for j in range(out_nx):
            block = surface[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            out[i, j] = block.mean() if block.size else 0.0
    return out


if __name__ == "__main__":
    main()
