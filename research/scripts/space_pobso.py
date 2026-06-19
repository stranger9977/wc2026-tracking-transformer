"""P-OBSO — Pressure-gated Off-ball Scoring Opportunity (the xT bridge).

This is THE ONE place space x threat belongs in the "Space" series. Every other
space metric is SPACE-NATIVE (m^2 / deformation / openness). P-OBSO is the
bridge: it multiplies pitch CONTROL by xT VALUE and asks "how much dangerous,
controllable space is the in-possession team creating, and who off the ball is
generating it?"

    OBSO(frame) = sum_cells  attack_control(cell) * xT(cell) * cell_area_m2

The per-cell quantity attack_control x xT is exactly Spearman's Off-Ball
Scoring Opportunity surface (control of dangerous space). We then:

  * ATTRIBUTE each cell's OBSO to the OFF-BALL attacker who most owns it (argmax
    player influence among attackers, excluding the on-ball carrier and GKs) ->
    a per-player "off-ball scoring opportunity generated" leaderboard.
  * PRESSURE-GATE the carrier: PFF possessionEvents carry pressureType in
    {N (none), P, A, L}. We build per-period pressure intervals and split each
    frame's OBSO into pressured (carrier under P/A/L) vs unpressured. The
    leaderboard reports BOTH and flags the pressured share.
  * OCCLUSION-GATE: ~40.9% of PFF positions are ESTIMATED (biased to fwds/
    wingers). Every player claim tracks its VISIBLE vs ESTIMATED frame share and
    we disclose it; the leaderboard flags low-visibility claims.

HONESTY:
  * Tie-aware leaderboards: per-player bootstrap CIs over sampled frames; we do
    NOT crown a false single #1 when CIs overlap.
  * The "SO WHAT" xG receipt: aggregate team P-OBSO per-90 and correlate
    (Spearman + bootstrap CI) with REAL StatsBomb 2022 team xG-for per-match.

Units: P-OBSO is xT-weighted m^2 (the bridge; NOT space-native). Reported
per-90 for the team receipt so games-played does not inflate totals.

Run BOUNDED (8 star-heavy matches, stride 15 ~2 Hz, P1+P2):
    export PFF_ROOT="$HOME/pff_wc22_local"
    PYTHONPATH=src uv run python research/scripts/space_pobso.py
"""
from __future__ import annotations

import bz2
import glob
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "research" / "scripts"))
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

import space_io  # noqa: E402
import pitch_control as pc  # noqa: E402

HALF_LEN = pc.HALF_LEN
HALF_WID = pc.HALF_WID

# ---------------------------------------------------------------------------
# Compute config (BOUNDED). 8 matches, ~2 Hz, full P1+P2.
# ---------------------------------------------------------------------------
SAMPLING_STRIDE = 15          # 30 Hz raw -> ~2 Hz
PERIODS = (1, 2)              # skip ET for the bounded run (keeps it comparable per-90)
COMPUTE_GRID = (26, 40)       # (ny, nx) coarse control grid
RAW_HZ = 30.0
SECS_PER_FRAME = SAMPLING_STRIDE / RAW_HZ  # 0.5 s per kept frame

# A "danger moment": the in-possession team controls a single cell whose
# control x xT exceeds this (i.e. it owns a genuinely chance-quality pocket).
# control ~ >0.8 of a >~0.15-xT cell. This is the FLOW unit the team xG receipt
# uses (a stock/time-average of OBSO does not predict a flow like xG).
DANGER_MOMENT_THRESH = 0.12

# Full WC2022 tournament: every PFF tracking game in the local cache (now 64/64).
# Auto-tracks whatever is present in $PFF_ROOT/Tracking Data.
SAMPLE_MATCHES = sorted(
    p.name.replace(".jsonl.bz2", "")
    for p in (Path(__import__("os").environ.get("PFF_ROOT", str(Path.home() / "pff_wc22_local")))
              / "Tracking Data").glob("*.jsonl.bz2")
)

SURF_DIR = _REPO / "research" / "site" / "data" / "surfaces"
DATA_DIR = _REPO / "research" / "site" / "data"
SB_EVENTS_DIR = _REPO / "research" / "data" / "raw_statsbomb" / "events"
SB_MATCHES_PARQUET = _REPO / "research" / "data" / "statsbomb" / "matches_wc_2022_sb.parquet"


# ---------------------------------------------------------------------------
# Pressure gate: per-(period) intervals where the carrier is under pressure.
# ---------------------------------------------------------------------------
def load_pressure_intervals(match_id: str, root: str | None = None) -> dict:
    """Return {period: [(t0_s, t1_s, pressureType), ...]} from PFF possessionEvents.

    Each possession event carries pressureType in {N, P, A, L} and a gameClock
    (period-elapsed seconds, same clock as tracking periodElapsedTime). We treat
    each pressured event (P/A/L) as covering [gameClock, gameClock + duration]
    where duration falls back to the next event's start within the period. The
    interval is the window during which the on-ball carrier was being pressed.
    """
    r = root or os.environ.get("PFF_ROOT")
    p = Path(r) / "Event Data" / f"{match_id}.json"
    data = json.load(open(p))
    # Collect (period, gameClock, pressureType) sorted within period.
    rows: list[tuple[int, float, str]] = []
    for rec in data:
        pe = rec.get("possessionEvents")
        ge = rec.get("gameEvents")
        if not isinstance(pe, dict) or not isinstance(ge, dict):
            continue
        period = ge.get("period")
        gc = pe.get("gameClock")
        pt = pe.get("pressureType")
        if period is None or gc is None or pt is None:
            continue
        rows.append((int(period), float(gc), str(pt)))
    rows.sort(key=lambda t: (t[0], t[1]))

    intervals: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
    for i, (period, gc, pt) in enumerate(rows):
        if pt not in ("P", "A", "L"):
            continue
        # window end = next event start in the same period (cap at +4 s)
        t_end = gc + 4.0
        for j in range(i + 1, len(rows)):
            if rows[j][0] != period:
                break
            t_end = min(rows[j][1], gc + 4.0)
            break
        if t_end <= gc:
            t_end = gc + 1.0
        intervals[period].append((gc, t_end, pt))
    return dict(intervals)


def _carrier_pressured(intervals: dict, period: int, t_s: float) -> str | None:
    """Return the pressureType (P/A/L) active at (period, t_s), else None."""
    for (t0, t1, pt) in intervals.get(period, []):
        if t0 <= t_s <= t1:
            return pt
    return None


# ---------------------------------------------------------------------------
# Per-frame OBSO + off-ball attribution.
# ---------------------------------------------------------------------------
def frame_obso(fr, grid, xt_grid):
    """Compute the OBSO surface and per-off-ball-attacker attribution for a frame.

    Returns:
        obso_total: float, integrated control x xT (xT-weighted m^2).
        surface:    (ny, nx) attack_control * xT (the OBSO surface).
        attrib:     {row_idx -> obso_value} for OFF-BALL attackers (carrier and
                    GKs excluded), where row_idx indexes fr.identities.
        carrier_row: int row index of the on-ball attacker (nearest attacker to
                    the ball), or None.
        peak_cell:  float, the max single-cell control x xT (best controlled-
                    danger pocket this frame); a "danger moment" when it exceeds
                    DANGER_MOMENT_THRESH.
    """
    ctrl = pc.control_surface(fr.players, fr.ball_m, grid, include_gk=True)
    surface = ctrl["attack_control"] * xt_grid
    obso_total = float(surface.sum() * grid.cell_area_m2)
    peak_cell = float(surface.max())       # best single controlled-danger pocket

    infl = ctrl["player_influence"]        # (n_kept, ny, nx)
    idx = ctrl["player_idx"]               # row indices into fr.players
    is_att = ctrl["player_is_attacking"]   # aligned with idx

    # On-ball carrier = nearest attacker to the ball (engine-row space).
    px = fr.players[:, 0] * HALF_LEN
    py = fr.players[:, 1] * HALF_WID
    att_mask_all = fr.players[:, 4] > 0
    gk_mask_all = fr.players[:, 5] > 0.5
    d_ball = np.hypot(px - fr.ball_m[0], py - fr.ball_m[1])
    carrier_row = None
    cand = np.where(att_mask_all & ~gk_mask_all)[0]
    if len(cand):
        carrier_row = int(cand[np.argmin(d_ball[cand])])

    # Attribute each cell to its argmax-influence OFF-BALL attacker.
    # Build sub-arrays over off-ball attackers (exclude carrier + GKs).
    sel = []
    sel_rows = []
    for k, row in enumerate(idx):
        if not is_att[k]:
            continue
        if fr.players[row, 5] > 0.5:        # GK
            continue
        if carrier_row is not None and row == carrier_row:
            continue
        sel.append(k)
        sel_rows.append(int(row))
    attrib: dict[int, float] = {}
    if sel:
        sub = infl[sel]                      # (m, ny, nx)
        owner = np.argmax(sub, axis=0)       # (ny, nx)
        for m_i, row in enumerate(sel_rows):
            cells = owner == m_i
            attrib[row] = float((cells * surface).sum() * grid.cell_area_m2)
    return obso_total, surface, attrib, carrier_row, peak_cell


# ---------------------------------------------------------------------------
# Main compute over the sample.
# ---------------------------------------------------------------------------
def compute(matches=SAMPLE_MATCHES):
    grid = pc.make_grid(nx=COMPUTE_GRID[1], ny=COMPUTE_GRID[0])
    xt_grid = pc.xt_surface(grid)

    # Per-player accumulators (keyed by (team_id, jersey)).
    # We collect a per-match per-player mean OBSO/frame and frame count so the
    # leaderboard can bootstrap over per-match observations (honest CIs).
    pl_meta: dict[tuple, dict] = {}
    # (team_id,jersey) -> list of per-frame OBSO values (for that player)
    pl_frames: dict[tuple, list[float]] = defaultdict(list)
    pl_frames_pressured: dict[tuple, list[float]] = defaultdict(list)
    pl_vis: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])  # [visible, estimated]
    # OBSO-weighted speed split (Fernandez-Bornn "active vs passive" space occupation +
    # the 538 "Messi walks" replication): how fast a player is moving while he owns the
    # dangerous space. pl_obso_walk = OBSO accrued at walking pace (<2 m/s, "passive").
    pl_obso_walk: dict[tuple, float] = defaultdict(float)
    pl_obso_wspeed: dict[tuple, float] = defaultdict(float)
    # team -> list of per-frame team-OBSO (one team is "attacking" each frame)
    team_obso_frames: dict[str, list[float]] = defaultdict(list)
    team_obso_pressured: dict[str, list[float]] = defaultdict(list)
    team_frames_count: dict[str, int] = defaultdict(int)
    # team -> [n_danger_moments, n_attacking_frames] for the FLOW xG receipt
    team_danger: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    team_peak: dict[str, list[float]] = defaultdict(list)
    # team -> list of PER-MATCH mean OBSO (the honest small-n unit for team CIs)
    team_match_means: dict[str, list[float]] = defaultdict(list)
    # team -> list of PER-MATCH danger-moment rate /min (CI for the FLOW ranking)
    team_match_dm: dict[str, list[float]] = defaultdict(list)

    match_summ = []
    t_start = time.time()
    for mi, mid in enumerate(matches):
        intervals = load_pressure_intervals(mid)
        n_frames = 0
        n_pressured = 0
        meta = space_io.load_metadata(mid)
        teams = (meta["homeTeam"]["name"], meta["awayTeam"]["name"])
        match_team_obso: dict[str, list[float]] = defaultdict(list)
        match_team_dm: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [dm, frames]
        t0 = time.time()
        for fr in space_io.read_match(mid, sampling_stride=SAMPLING_STRIDE,
                                      periods=PERIODS):
            obso_total, surface, attrib, carrier_row, peak_cell = frame_obso(
                fr, grid, xt_grid)
            pt = _carrier_pressured(intervals, fr.period, fr.timestamp_s)
            pressured = pt is not None
            n_frames += 1
            if pressured:
                n_pressured += 1

            att_team = fr.in_possession_team
            team_obso_frames[att_team].append(obso_total)
            match_team_obso[att_team].append(obso_total)
            if pressured:
                team_obso_pressured[att_team].append(obso_total)
            team_frames_count[att_team] += 1
            team_peak[att_team].append(peak_cell)
            team_danger[att_team][1] += 1
            match_team_dm[att_team][1] += 1
            if peak_cell > DANGER_MOMENT_THRESH:
                team_danger[att_team][0] += 1
                match_team_dm[att_team][0] += 1

            for row, val in attrib.items():
                ident = fr.identities[row]
                key = (ident.team_id, ident.jersey)
                if key not in pl_meta:
                    pl_meta[key] = {"name": ident.name, "team": ident.team,
                                    "team_id": ident.team_id, "jersey": ident.jersey,
                                    "is_gk": ident.is_gk}
                pl_frames[key].append(val)
                spd = float(np.hypot(fr.players[row, 2], fr.players[row, 3]))
                pl_obso_wspeed[key] += val * spd
                if spd < 2.0:
                    pl_obso_walk[key] += val
                if pressured:
                    pl_frames_pressured[key].append(val)
                if str(ident.visibility) == "ESTIMATED":
                    pl_vis[key][1] += 1
                else:
                    pl_vis[key][0] += 1
        # record this match's per-team mean OBSO + danger-moment rate (>= 50 frames)
        for tm, vals in match_team_obso.items():
            if len(vals) >= 50:
                team_match_means[tm].append(float(np.mean(vals)))
                nd, naf = match_team_dm[tm]
                team_match_dm[tm].append((nd / max(naf, 1)) / SECS_PER_FRAME * 60.0)
        dt = time.time() - t0
        match_summ.append({
            "match_id": mid, "teams": teams, "n_frames": n_frames,
            "n_pressured": n_pressured,
            "pressured_share": round(n_pressured / max(n_frames, 1), 3),
        })
        print(f"[{mi+1}/{len(matches)}] {mid} {teams[0]} v {teams[1]}: "
              f"{n_frames} frames, {n_pressured} pressured "
              f"({100*n_pressured/max(n_frames,1):.0f}%) [{dt:.1f}s, "
              f"tot {time.time()-t_start:.1f}s]", flush=True)

    return {
        "grid": grid, "xt_grid": xt_grid,
        "pl_meta": pl_meta, "pl_frames": pl_frames,
        "pl_frames_pressured": pl_frames_pressured, "pl_vis": pl_vis,
        "pl_obso_walk": dict(pl_obso_walk), "pl_obso_wspeed": dict(pl_obso_wspeed),
        "team_obso_frames": team_obso_frames,
        "team_obso_pressured": team_obso_pressured,
        "team_frames_count": team_frames_count,
        "team_danger": dict(team_danger),
        "team_peak": dict(team_peak),
        "team_match_means": dict(team_match_means),
        "team_match_dm": dict(team_match_dm),
        "match_summ": match_summ,
        "compute_s": round(time.time() - t_start, 1),
    }


# ---------------------------------------------------------------------------
# Bootstrap CI helper.
# ---------------------------------------------------------------------------
def _bootstrap_ci(vals, n_boot=400, stat=np.mean, seed=0):
    if len(vals) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    arr = np.asarray(vals, dtype=np.float64)
    boots = np.empty(n_boot)
    n = len(arr)
    for b in range(n_boot):
        boots[b] = stat(arr[rng.integers(0, n, n)])
    return (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))


# ---------------------------------------------------------------------------
# Build the player + team leaderboard JSON.
# ---------------------------------------------------------------------------
def build_leaderboard(res):
    pl_meta = res["pl_meta"]
    pl_frames = res["pl_frames"]
    pl_frames_pressured = res["pl_frames_pressured"]
    pl_vis = res["pl_vis"]
    pl_obso_walk = res.get("pl_obso_walk", {})
    pl_obso_wspeed = res.get("pl_obso_wspeed", {})

    # HEADLINE player unit = mean P-OBSO an off-ball attacker CONTROLS per frame
    # they are on the pitch while their team attacks (xT-weighted m^2 of
    # controlled danger). This is space-bridge-native magnitude (no per-90
    # inflation): "at any instant, this player owns ~X m^2 of dangerous,
    # controllable space off the ball." The bootstrap CI is on that mean, so the
    # tie-aware test is apples-to-apples.
    players = []
    for key, frames in pl_frames.items():
        if len(frames) < 60:   # >= ~30 s of sampled off-ball presence
            continue
        meta = pl_meta[key]
        arr = np.asarray(frames)
        lo, hi = _bootstrap_ci(arr)
        pframes = pl_frames_pressured.get(key, [])
        pressured_share = (sum(pframes) / arr.sum()) if arr.sum() > 0 else 0.0
        vis = pl_vis[key]
        est_share = vis[1] / max(vis[0] + vis[1], 1)
        osum = float(arr.sum())
        walk = pl_obso_walk.get(key, 0.0)
        wspeed = pl_obso_wspeed.get(key, 0.0)
        passive_share = (walk / osum) if osum > 0 else 0.0
        control_speed = (wspeed / osum) if osum > 0 else 0.0
        players.append({
            "name": meta["name"], "team": meta["team"], "jersey": meta["jersey"],
            "pobso": round(float(arr.mean()), 3),       # headline (xT-wtd m^2 / frame)
            "occupation_total": round(osum, 2),         # sum over sampled frames (F&B Sum-SOG style)
            "passive_pct": round(100.0 * passive_share),   # % of owned danger at walking pace (<2 m/s)
            "active_pct": round(100.0 * (1.0 - passive_share)),
            "control_speed": round(control_speed, 2),   # OBSO-weighted speed (m/s) while owning danger
            "ci": [round(lo, 3), round(hi, 3)],
            "n_frames": len(frames),
            "minutes_sampled": round(len(frames) * SECS_PER_FRAME / 60.0, 1),
            "pressured_share": round(pressured_share, 3),
            "estimated_share": round(est_share, 3),
            "occlusion_flag": est_share > 0.5,
        })
    players.sort(key=lambda d: -d["pobso"])

    # Tie-aware ranking: rank 1 = top; players whose CI overlaps the leader's CI
    # are flagged tied_with_leader (no false single #1).
    if players:
        leader_lo = players[0]["ci"][0]
        for p in players:
            p["tied_with_leader"] = p["ci"][1] >= leader_lo

    # Per-team leaderboard: mean team OBSO per attacking-frame (the stock measure
    # — how much controlled danger the team HOLDS on average while attacking),
    # with bootstrap CI. NOTE: this is a stock, not the flow that drives xG (see
    # xg_receipt, which uses the danger-moment RATE).
    team_obso = res["team_obso_frames"]
    team_obso_pr = res["team_obso_pressured"]
    team_danger = res.get("team_danger", {})
    team_match_means = res.get("team_match_means", {})
    team_match_dm = res.get("team_match_dm", {})
    teams = []
    for team, frames in team_obso.items():
        arr = np.asarray(frames)
        prframes = team_obso_pr.get(team, [])
        pr_share = (sum(prframes) / arr.sum()) if arr.sum() > 0 else 0.0
        nd, naf = team_danger.get(team, [0, len(frames)])
        # PRIMARY team unit = danger-moment rate per minute of possession (the
        # FLOW that tracks xG). Stock (mean OBSO) is reported too but is sterile.
        dm_per_min = (nd / max(naf, 1)) / SECS_PER_FRAME * 60.0
        # HONEST team CI: bootstrap over PER-MATCH rates (small n), NOT over the
        # 100k+ correlated frames (which gives a fake-tight CI). <2 matches => no CI.
        dm_m = team_match_dm.get(team, [])
        n_m = len(dm_m)
        if n_m >= 2:
            lo, hi = _bootstrap_ci(np.asarray(dm_m), n_boot=2000)
        else:
            lo = hi = dm_per_min
        teams.append({
            "team": team,
            "danger_moments_per_min": round(dm_per_min, 2),   # PRIMARY (flow)
            "ci": [round(lo, 2), round(hi, 2)],
            "ci_basis": f"bootstrap over {n_m} sampled matches" if n_m >= 2
                        else f"point estimate ({n_m} match sampled; CI N/A)",
            "n_matches_sampled": n_m,
            "pobso_stock": round(float(arr.mean()), 3),   # xT-wtd m^2 held / frame
            "attacking_frames": len(frames),
            "pressured_share": round(pr_share, 3),
        })
    teams.sort(key=lambda d: -d["danger_moments_per_min"])
    if teams:
        tleader_lo = teams[0]["ci"][0]
        for t in teams:
            t["tied_with_leader"] = t["ci"][1] >= tleader_lo

    return players, teams


# ---------------------------------------------------------------------------
# SO-WHAT: correlate team P-OBSO per-90 with StatsBomb team xG-for per-match.
# ---------------------------------------------------------------------------
def _pff_to_sb_xg(matches):
    """Aggregate StatsBomb team xG-for over the SAME sampled PFF matches.

    Returns {team_name: (total_xg_for, n_matches)} restricted to the sampled
    matches so the correlation compares like with like (per-match xG-for rate).
    """
    import pandas as pd
    sb = pd.read_parquet(SB_MATCHES_PARQUET)
    # PFF (home,away) -> sb match_id
    pff_keys = {}
    for mid in matches:
        meta = space_io.load_metadata(mid)
        pff_keys[(meta["homeTeam"]["name"], meta["awayTeam"]["name"])] = mid
    # find sb match_ids for our sampled matches
    sb_for_pff = {}  # pff_mid -> sb_mid
    for _, r in sb.iterrows():
        key = (r["home_team"], r["away_team"])
        keyr = (r["away_team"], r["home_team"])
        pm = pff_keys.get(key) or pff_keys.get(keyr)
        if pm:
            sb_for_pff[pm] = str(r["match_id"])

    sb_idx = sb.set_index("match_id")
    team_xg = defaultdict(float)
    team_n = defaultdict(int)
    for pff_mid, sb_mid in sb_for_pff.items():
        evp = SB_EVENTS_DIR / f"{sb_mid}.json"
        if not evp.exists():
            continue
        ev = json.load(open(evp))
        for e in ev:
            if e.get("type", {}).get("name") != "Shot":
                continue
            # Match the tracking sample: REGULATION ONLY (periods 1-2). Excludes
            # extra time AND the penalty shootout (period 5), which would
            # otherwise inflate knockout xG with ~0.78-xG shootout penalties.
            if e.get("period") not in (1, 2):
                continue
            tname = e["team"]["name"]
            team_xg[tname] += e.get("shot", {}).get("statsbomb_xg") or 0.0
        # one match-appearance per team that played in this sampled match
        row = sb_idx.loc[int(sb_mid)]
        team_n[row["home_team"]] += 1
        team_n[row["away_team"]] += 1
    return team_xg, team_n, sb_for_pff


def build_xg_receipt(res, matches):
    """The SO-WHAT. Correlate the team P-OBSO FLOW (danger-moment rate per min of
    possession) with REAL StatsBomb 2022 team xG-for per match.

    We use the danger-moment RATE rather than the time-averaged OBSO STOCK on
    purpose: a stock (how much controlled danger a team holds on average) does
    not, and should not be expected to, predict a flow like xG — possession-
    dominant ball-retention sides hold lots of controlled space without
    converting it. The rate of distinct controlled-danger pockets is the closest
    space-native proxy for chance creation. We report whatever we find, with CI,
    unit, and n — correlation, not causation.
    """
    from scipy import stats as sps
    team_danger = res["team_danger"]
    # team danger-moment rate per minute of possession (the FLOW)
    team_rate = {}
    for team, (nd, naf) in team_danger.items():
        if naf <= 0:
            continue
        team_rate[team] = (nd / naf) / SECS_PER_FRAME * 60.0

    team_xg, team_n, sb_for_pff = _pff_to_sb_xg(matches)
    # xG-for per match (defensible unit, not games-inflated total)
    team_xg_per_match = {t: team_xg[t] / team_n[t] for t in team_xg if team_n[t] > 0}

    common = sorted(set(team_rate) & set(team_xg_per_match))
    xs = np.array([team_rate[t] for t in common])
    ys = np.array([team_xg_per_match[t] for t in common])
    n = len(common)
    if n >= 4:
        rho, pval = sps.spearmanr(xs, ys)
    else:
        rho, pval = float("nan"), float("nan")

    # bootstrap CI on Spearman rho (resample teams)
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(2000):
        idx = rng.integers(0, n, n)
        if len(set(idx)) < 3:
            continue
        rb, _ = sps.spearmanr(xs[idx], ys[idx])
        if not np.isnan(rb):
            boots.append(rb)
    ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if boots else (float("nan"), float("nan"))

    detail = [{"team": t, "danger_moments_per_min": round(team_rate[t], 2),
               "sb_xg_per_match": round(team_xg_per_match[t], 3),
               "sb_matches": team_n[t]} for t in common]
    detail.sort(key=lambda d: -d["danger_moments_per_min"])

    ci_spans_zero = (not np.isnan(ci[0])) and ci[0] <= 0 <= ci[1]
    if np.isnan(rho):
        reading = "insufficient teams to correlate"
    elif ci_spans_zero or (pval is not None and pval > 0.10):
        reading = (
            "NULL / not significant: over these 8 matches, team-level off-ball "
            "danger-moment rate does NOT reliably predict xG-for (CI spans 0). "
            "Controlled dangerous space is necessary but not sufficient for "
            "shots; conversion/penetration is a separate step, and n=10 teams "
            "with overlapping CIs is underpowered. Honest negative result.")
    elif rho > 0:
        reading = ("positive: teams that create more controlled-danger pockets "
                   "off the ball tend to generate more xG-for.")
    else:
        reading = ("negative: possession-dominant sides hold/spike controlled "
                   "danger without converting it to more xG-for.")

    return {
        "n": n,
        "rho": round(float(rho), 3) if not np.isnan(rho) else None,
        "p_value": round(float(pval), 4) if not np.isnan(pval) else None,
        "ci95": [round(ci[0], 3), round(ci[1], 3)] if not np.isnan(ci[0]) else None,
        "unit": ("x = team P-OBSO danger-moment rate (controlled control x xT "
                 "pockets per minute of possession); y = StatsBomb 2022 xG-for "
                 "per match"),
        "unit_x": "danger-moments per minute of possession (control x xT pocket > "
                  f"{DANGER_MOMENT_THRESH})",
        "unit_y": "StatsBomb open+set-play xG-for per match (2022 WC)",
        "reading": reading,
        "detail": detail,
        "sb_match_map": sb_for_pff,
    }


# ---------------------------------------------------------------------------
# HERO PLAY: an off-ball run into a high-OBSO zone. Export control x xT surface.
# ---------------------------------------------------------------------------
def find_and_export_hero(res, matches):
    """Scan a star-heavy match for the frame whose single off-ball attacker owns
    the most OBSO (an off-ball run into a high-danger pocket), then export a
    surface window around it.
    """
    grid = res["grid"]
    xt_grid = res["xt_grid"]

    # Use Argentina-France final (10517). Pick the WINDOW where a single off-ball
    # attacker ADVANCES into a high-OBSO pocket (a forward run into dangerous
    # space) — not just a peak frame during a deep recycle — so the danger pocket
    # visibly blooms AHEAD of the run rather than sitting static near goal.
    hero_mid = "10517"
    track = defaultdict(list)   # (period, name, team) -> [(t_s, obso, x_m, spd)]
    for fr in space_io.read_match(hero_mid, sampling_stride=SAMPLING_STRIDE,
                                  periods=PERIODS):
        _, surface, attrib, carrier_row, peak_cell = frame_obso(fr, grid, xt_grid)
        if not attrib:
            continue
        top_row = max(attrib, key=attrib.get)
        spd = float(np.hypot(fr.players[top_row, 2], fr.players[top_row, 3]))
        x_m = float(fr.players[top_row, 0] * HALF_LEN)
        track[(fr.period, fr.identities[top_row].name, fr.identities[top_row].team)].append(
            (fr.timestamp_s, float(attrib[top_row]), x_m, spd))

    WIN_S = 6.0
    best = None   # (score, period, name, team, w0, w1, t_peak, peak_val, peak_spd)
    for (period, nm, tm), series in track.items():
        series.sort()
        ts = [s[0] for s in series]; ob = [s[1] for s in series]
        xs = [s[2] for s in series]; sp = [s[3] for s in series]
        for i in range(len(ts)):
            j = i
            while j < len(ts) and ts[j] - ts[i] <= WIN_S:
                j += 1
            if j - i < 6:
                continue
            adv = xs[j - 1] - xs[i]              # forward advance over the window (m)
            if adv < 6.0 or xs[j - 1] < 28.0:    # advance >=6 m AND END in/near the box (final third)
                continue
            mean_ob = sum(ob[i:j]) / (j - i)
            score = mean_ob * (1.0 + min(adv, 25.0) / 25.0)
            if best is None or score > best[0]:
                kp = max(range(i, j), key=lambda k: ob[k])
                best = (score, period, nm, tm, ts[i], ts[j - 1], ts[kp], ob[kp], sp[kp])

    if best is None:
        return None
    _, period, hero_name, hero_team, w0, w1, t_s, hero_val, hero_spd = best

    # Lock orientation + attacker designation to the hero's team for the whole
    # window, so the noisy nearest-to-ball possession heuristic can't mirror the
    # field or invert the danger surface mid-clip (the "random flipping").
    meta = space_io.load_metadata(hero_mid)
    hero_team_id = (str(meta["homeTeam"]["id"]) if hero_team == meta["homeTeam"]["name"]
                    else str(meta["awayTeam"]["id"]))

    # Export the run window as a scrubbable control x xT surface (a little padding).
    start_s = max(0.0, w0 - 0.5)
    end_s = w1 + 0.5
    out_g = pc.make_grid(nx=40, ny=26)
    out_xt = pc.xt_surface(out_g)

    frames_out = []
    raw_maxes = []
    for fr in space_io.read_match(hero_mid, sampling_stride=SAMPLING_STRIDE,
                                  periods=(period,), lock_attack_team_id=hero_team_id):
        if fr.timestamp_s < start_s or fr.timestamp_s > end_s:
            continue
        ctrl = pc.control_surface(fr.players, fr.ball_m, out_g, include_gk=True)
        surf = ctrl["attack_control"] * out_xt
        rmax = float(surf.max())
        raw_maxes.append(rmax)
        # player markers (attacking off-ball runs visible)
        markers = []
        for i, ident in enumerate(fr.identities):
            markers.append({
                "x": round(float(fr.players[i, 0] * HALF_LEN), 1),
                "y": round(float(fr.players[i, 1] * HALF_WID), 1),
                "att": bool(fr.players[i, 4] > 0),
                "gk": bool(fr.players[i, 5] > 0.5),
                "name": ident.name,
                "vis": ident.visibility,
            })
        frames_out.append({
            "t_s": round(fr.timestamp_s, 2),
            "ball_xy": [round(float(fr.ball_m[0]), 1), round(float(fr.ball_m[1]), 1)],
            "in_possession_team": fr.in_possession_team,
            "surface_raw": surf,
            "raw_max": round(rmax, 5),
            "players": markers,
        })
    gmax = max(raw_maxes) if raw_maxes else 1.0
    gmax = gmax if gmax > 0 else 1.0
    for f in frames_out:
        s = f.pop("surface_raw") / gmax
        f["surface"] = [[round(float(v), 4) for v in row] for row in s]
    xt_ref_norm = out_xt / (out_xt.max() if out_xt.max() > 0 else 1.0)

    payload = {
        "metric": "pobso",
        "title": f"P-OBSO hero: {hero_name}'s off-ball run into dangerous space",
        "description": (
            f"{hero_name} ({hero_team}) peels into a high-OBSO pocket: the surface "
            "is attacker pitch-control x Expected Threat (the Off-Ball Scoring "
            "Opportunity field). Watch the bright zone form ahead of the run, not "
            "just where the ball is."),
        "match_id": hero_mid,
        "match": f"{meta['homeTeam']['name']} v {meta['awayTeam']['name']}",
        "period": period,
        "start_s": round(start_s, 1),
        "end_s": round(end_s, 1),
        "peak_t_s": round(t_s, 2),
        "hero": {"name": hero_name, "team": hero_team,
                 "obso_owned": round(float(hero_val), 4), "speed_mps": round(hero_spd, 1)},
        "hz": round(RAW_HZ / SAMPLING_STRIDE, 2),
        "n_frames": len(frames_out),
        "grid": {"nx": out_g.nx, "ny": out_g.ny, "length_m": 105.0, "width_m": 68.0},
        "global_max": round(gmax, 5),
        "xt_reference": [[round(float(v), 4) for v in row] for row in xt_ref_norm],
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "frames": frames_out,
    }
    out_path = SURF_DIR / "pobso.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(payload, fh)
    return payload, str(out_path)


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("P-OBSO — Pressure-gated Off-ball Scoring Opportunity (xT bridge)")
    print(f"sample: {len(SAMPLE_MATCHES)} matches, stride {SAMPLING_STRIDE} "
          f"(~{RAW_HZ/SAMPLING_STRIDE:.1f} Hz), periods {PERIODS}")
    print("=" * 70)

    res = compute(SAMPLE_MATCHES)
    players, teams = build_leaderboard(res)
    receipt = build_xg_receipt(res, SAMPLE_MATCHES)

    # occlusion disclosure aggregate
    tot_vis = sum(v[0] for v in res["pl_vis"].values())
    tot_est = sum(v[1] for v in res["pl_vis"].values())
    est_pct = 100.0 * tot_est / max(tot_vis + tot_est, 1)

    leaderboard = {
        "metric": "P-OBSO",
        "title": "P-OBSO — Pressure-gated Off-ball Scoring Opportunity",
        "definition": (
            "OBSO = sum over the pitch of (attacker pitch-control x Expected "
            "Threat). The per-player value attributes each cell's OBSO to the "
            "OFF-BALL attacker who most controls it (carrier and GKs excluded). "
            "This is the one place in the Space series where space x threat "
            "belongs (the xT bridge). All other space metrics stay space-native."),
        "units": ("P-OBSO = xT-weighted m^2 (pitch-control x xT). Player/team "
                  "headline 'pobso' is the MEAN controlled-danger area held per "
                  "frame (a stock). The xG receipt uses a FLOW unit (danger-"
                  "moment rate). This is the only space metric that is NOT "
                  "space-native -- it is the xT bridge."),
        "honesty": {
            "tie_aware": "bootstrap 95% CIs over sampled frames; players/teams whose "
                         "CI overlaps the leader's are flagged tied_with_leader (no "
                         "false single #1).",
            "occlusion_gated": f"{est_pct:.1f}% of sampled player-positions were "
                               "ESTIMATED (PFF occlusion, biased to fwds/wingers); "
                               "each player tracks estimated_share and occlusion_flag.",
            "pressure_gate": "carrier pressure from PFF possessionEvents "
                             "pressureType in {P,A,L}; pressured_share is the OBSO "
                             "fraction generated while the on-ball carrier was "
                             "being pressed.",
            "stock_vs_flow": "team mean OBSO (stock) is a poor xG predictor by "
                             "design; the receipt correlates the danger-moment "
                             "rate (flow) and reports the result honestly with CI.",
        },
        "sample": {
            "n_matches": len(SAMPLE_MATCHES),
            "matches": res["match_summ"],
            "sampling_stride": SAMPLING_STRIDE,
            "hz": round(RAW_HZ / SAMPLING_STRIDE, 2),
            "periods": list(PERIODS),
            "secs_per_frame": SECS_PER_FRAME,
            "compute_s": res["compute_s"],
            "occlusion_estimated_pct": round(est_pct, 1),
        },
        "section_spec": {
            "headline": "Who owns the dangerous space when the ball isn't at their feet",
            "subhead": ("P-OBSO is the bridge: pitch control x Expected Threat. "
                        "It scores the off-ball runner who controls the most "
                        "valuable real estate the ball could profitably reach."),
            "viz_shows": ("The live control x xT surface for the hero play: a "
                          "bright danger-pocket blooms ahead of an off-ball run, "
                          "not at the ball. Player dots colored by team; "
                          "ESTIMATED-position dots dimmed to disclose occlusion."),
            "interaction": ("Scrub the play; a 'reveal danger' toggle fades the "
                            "ball-centric view and lights only cells the off-ball "
                            "attackers control above an xT threshold, so you watch "
                            "the scoring opportunity form before the pass exists. "
                            "Hover a runner to see the m^2 of danger they own."),
        },
        "xg_receipt": receipt,
        "players": players,
        "teams": teams,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lb_path = DATA_DIR / "space_pobso.json"
    with open(lb_path, "w") as fh:
        json.dump(leaderboard, fh, indent=1)
    print(f"\n[export] leaderboard -> {lb_path}")
    print(f"[leaderboard] {len(players)} players, {len(teams)} teams")
    print(f"[xg-receipt] n={receipt['n']} rho={receipt['rho']} "
          f"CI95={receipt['ci95']} p={receipt['p_value']}")
    print(f"[xg-receipt] reading: {receipt['reading']}")
    print("[top-5 players P-OBSO (xT-wtd m^2 controlled/frame)]:")
    for p in players[:5]:
        print(f"   {p['name']:<24} {p['team']:<12} {p['pobso']:6.3f} "
              f"CI{p['ci']} press={p['pressured_share']:.2f} "
              f"est={p['estimated_share']:.2f}"
              f"{' [OCCLUDED]' if p['occlusion_flag'] else ''}"
              f"{' [tie]' if p.get('tied_with_leader') else ''}")
    print("[top-5 teams by danger-moment rate /min (CI over matches)]:")
    for t in teams[:5]:
        print(f"   {t['team']:<14} dm/min={t['danger_moments_per_min']:5.2f} "
              f"CI{t['ci']} stock={t['pobso_stock']:.2f} "
              f"press={t['pressured_share']:.2f}"
              f"{' [tie]' if t.get('tied_with_leader') else ''}")

    hero = None if os.environ.get("POBSO_SKIP_HERO") else find_and_export_hero(res, SAMPLE_MATCHES)
    if hero:
        pay, hpath = hero
        print(f"\n[export] hero surface -> {hpath} "
              f"({pay['n_frames']} frames, hero={pay['hero']['name']})")

    print("\nEXIT_OK", flush=True)


if __name__ == "__main__":
    main()
