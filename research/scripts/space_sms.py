"""SMS — Self-Made Space (a SPACE-NATIVE space metric).

WHAT IT MEASURES
----------------
For every ATTACKING OFF-BALL player on each kept frame, SMS is the amount of
controllable RECEIVING SPACE (m^2) that player holds — the patch of pitch the
player's pitch-control influence dominates, weighted by how decisively their
team controls it (engine ``player_space`` ``area_m2``, ``attacking_only``).
The ball-carrier (nearest attacker to the ball) and goalkeepers are excluded,
so SMS is purely OFF-BALL space: the space a player opens up for a pass to
arrive into, not the ground they happen to stand on with the ball at their feet.

The "SELF-MADE" framing isolates space a player generates by MOVEMENT and
POSITIONING rather than space that is simply there to be stood in. We compute a
STATIC baseline (the same frame with every player's velocity zeroed) and define

    sms_self_made = total_offball_area - static_baseline_area   (clamped >= 0)

so a player drifting into a developing gap, or sprinting to stretch a back line,
scores higher than one standing in a pocket the defence has already conceded.
We report BOTH the total off-ball area (``sms_total_area_m2``) and the movement
component (``sms_self_made_m2``); the headline metric is per-frame mean total
off-ball area held (a clean, interpretable m^2 number), with self-made as the
"how much of it did movement create" companion.

UNITS ARE SPACE-NATIVE (m^2). xT is NOT folded in here — that is the P-OBSO
bridge's job. SMS lives in square metres.

HONESTY
-------
  * Occlusion gate: a player's per-frame space claim is CREDITED to their
    leaderboard total only when that player is VISIBLE in that frame; ESTIMATED
    frames are tracked and the per-player / per-team ESTIMATED share is
    disclosed. Players who are mostly tracked-by-estimation carry a flag.
  * Tie-aware: per-player and per-team means carry a bootstrap 95% CI over their
    per-frame samples; the leaderboard exposes the CIs so overlapping values are
    not falsely ranked 1-2-3. A ``tie_group`` field clusters players whose CIs
    overlap with the leader.
  * N disclosed: every row carries n_frames; the run logs exactly which matches
    and how many frames were sampled.

THE SO-WHAT (xG receipt)
------------------------
Per team, SMS is a STYLE signal (how much off-ball receiving space the team's
attackers generate). We test whether it pays: aggregate each team's per-frame
mean SMS across sampled matches, then correlate with that team's REAL StatsBomb
2022 xG-for per 90 (Spearman rho + bootstrap 95% CI). Correlation, not
causation; unit is xG-for per 90; n = number of teams.

OUTPUTS
-------
  1. research/site/data/space_sms.json   — leaderboard (players + teams),
     tie-aware CIs, occlusion-gated, N + matches sampled, xG receipt.
  2. research/site/data/surfaces/sms.json — hero-play per-frame off-ball
     controllable-space surface (downsampled grid x frames) + section_spec.

RUN (bounded; this script self-bounds, but for safety launch backgrounded):
    cd /Users/nick/wc2026-tracking-transformer
    export PFF_ROOT="$HOME/pff_wc22_local"
    PYTHONPATH=src uv run python research/scripts/space_sms.py
"""
from __future__ import annotations

import glob
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
from pitch_control import (  # noqa: E402
    HALF_LEN,
    HALF_WID,
    make_grid,
    control_surface,
    player_space,
)

# --------------------------------------------------------------------------- #
# Sampling configuration (BOUNDED). Stride 15 over 30 Hz raw -> ~2 Hz.
# --------------------------------------------------------------------------- #
STRIDE = 15                       # ~2 Hz
GRID_NX, GRID_NY = 32, 22         # coarse control grid (cell ~3.3 x 3.1 m)
PERIODS = (1, 2)                  # regulation only; ET adds little + costs time

# Star-heavy + diverse sample (knockouts where Argentina/France/Croatia/Spain/
# Portugal/Morocco/Netherlands feature). All present in PFF tracking.
SAMPLE_MATCHES = [
    "10517",  # Argentina v France (FINAL) — Messi, Mbappe, Di Maria
    "10514",  # Argentina v Croatia (SF) — Messi, Modric, Alvarez
    "10513",  # England v France (QF) — Mbappe, Griezmann, Kane, Bellingham
    "10508",  # Morocco v Spain (R16) — Pedri, Gavi, Ziyech
    "10506",  # Japan v Croatia (R16) — Modric, Brozovic, Kovacic
    "10509",  # Portugal v Switzerland (R16) — Ronaldo, B.Fernandes, Ramos
    "10511",  # Netherlands v Argentina (QF) — Messi, Depay, Gakpo
    "10503",  # Argentina v Australia (R16) — hero clip lives here (Messi 35')
]

OUT_LEADERBOARD = _REPO / "research" / "site" / "data" / "space_sms.json"
OUT_SURFACE = _REPO / "research" / "site" / "data" / "surfaces" / "sms.json"
LOG_PATH = _HERE / "_space_sms_run.log"

# Hero play: Messi 35' vs Australia (match 10503, period 1, ~2055-2078 s) — the
# same window the engine demo + the clips index ("argentina-australia-messi")
# use. We render the OFF-BALL controllable-space surface over it so the heatmap
# tells the SMS story (where the receiving space is being opened), not the raw
# value-of-space story.
HERO_MATCH = "10503"
HERO_PERIOD = 1
HERO_START_S = 2055.0
HERO_END_S = 2078.0
HERO_OUT_GRID = (26, 40)          # (ny, nx) — small for fast client render

# StatsBomb 2022 receipts.
SB_MATCHES_PARQUET = _REPO / "research" / "data" / "statsbomb" / "matches_wc_2022_sb.parquet"
SB_EVENTS_DIR = _REPO / "research" / "data" / "raw_statsbomb" / "events"

RNG = np.random.default_rng(20260616)


def _log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Per-frame SMS for one match.
# --------------------------------------------------------------------------- #
def _ball_carrier_row(fr) -> int:
    """Row index of the attacking, non-GK player nearest the ball (carrier)."""
    px = fr.players[:, 0] * HALF_LEN
    py = fr.players[:, 1] * HALF_WID
    att = fr.players[:, 4] > 0
    gk = fr.players[:, 5] > 0.5
    cand = att & (~gk)
    if not cand.any():
        cand = att
    d = np.hypot(px - fr.ball_m[0], py - fr.ball_m[1])
    d = np.where(cand, d, np.inf)
    return int(np.argmin(d))


def _static_players(players: np.ndarray) -> np.ndarray:
    """Copy of the player array with all velocities zeroed (positional baseline)."""
    s = players.copy()
    s[:, 2] = 0.0
    s[:, 3] = 0.0
    return s


def accumulate_match(match_id: str, grid, acc_player, acc_team, team_names,
                     match_team_frames):
    """Stream one match; accumulate per-(team,jersey) and per-team SMS samples.

    acc_player[key] = {name, team, team_id, jersey, total: [..], self: [..],
                       vis: [..bool], est: int, vis_n: int}
      where total/self lists hold per-frame off-ball area (m^2) for VISIBLE
      frames only (the occlusion gate); est/vis_n count gate decisions.
    acc_team[team_id] = {name, total: [..per-frame TEAM mean off-ball area..]}
    match_team_frames[(match_id, team_id)] = [..per-frame team mean..] (for the
      per-match team xG receipt aggregation).
    """
    n = 0
    t0 = time.time()
    for fr in space_io.read_match(match_id, sampling_stride=STRIDE, periods=PERIODS):
        n += 1
        carrier = _ball_carrier_row(fr)

        ctrl = control_surface(fr.players, fr.ball_m, grid, include_gk=True)
        ps = player_space(ctrl, grid, attacking_only=True)
        # static baseline (movement removed) for the self-made component.
        ctrl_s = control_surface(_static_players(fr.players), fr.ball_m, grid,
                                 include_gk=True)
        ps_s = player_space(ctrl_s, grid, attacking_only=True)

        # Per-frame team off-ball area (sum over attacking off-ball outfielders).
        team_frame_total = defaultdict(float)
        for row_i, sp in ps.items():
            idn = fr.identities[row_i]
            if idn.is_gk or row_i == carrier:
                continue  # off-ball outfield attackers only
            area = float(sp["area_m2"])
            static_area = float(ps_s.get(row_i, {}).get("area_m2", 0.0))
            self_made = max(area - static_area, 0.0)

            key = (idn.team_id, idn.jersey)
            visible = idn.visibility == "VISIBLE"
            rec = acc_player.get(key)
            if rec is None:
                rec = {"name": idn.name, "team": idn.team, "team_id": idn.team_id,
                       "jersey": idn.jersey, "total": [], "self": [],
                       "est": 0, "vis_n": 0}
                acc_player[key] = rec
            if visible:
                rec["total"].append(area)
                rec["self"].append(self_made)
                rec["vis_n"] += 1
            else:
                rec["est"] += 1

            team_names[idn.team_id] = idn.team
            # Team total includes only VISIBLE claims (gate at team level too).
            if visible:
                team_frame_total[idn.team_id] += area

        for tid, tot in team_frame_total.items():
            acc_team[tid]["name"] = team_names.get(tid, tid)
            acc_team[tid]["total"].append(tot)
            match_team_frames[(match_id, tid)].append(tot)

        if n % 400 == 0:
            _log(f"    {match_id}: {n} frames (t={fr.timestamp_s:.0f}s) "
                 f"[{time.time()-t0:.1f}s]")
    _log(f"  {match_id}: DONE {n} frames in {time.time()-t0:.1f}s")
    return n


# --------------------------------------------------------------------------- #
# Bootstrap helpers (tie-aware CIs).
# --------------------------------------------------------------------------- #
def _boot_mean_ci(samples, n_boot=600, alpha=0.05):
    a = np.asarray(samples, dtype=np.float64)
    if a.size == 0:
        return 0.0, 0.0, 0.0
    if a.size == 1:
        v = float(a[0])
        return v, v, v
    idx = RNG.integers(0, a.size, size=(n_boot, a.size))
    means = a[idx].mean(axis=1)
    lo = float(np.percentile(means, 100 * alpha / 2))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return float(a.mean()), lo, hi


def _spearman(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    rx = np.argsort(np.argsort(x)); ry = np.argsort(np.argsort(y))
    rx = rx.astype(float); ry = ry.astype(float)
    if rx.std() == 0 or ry.std() == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def _spearman_boot_ci(x, y, n_boot=2000, alpha=0.05):
    x = np.asarray(x, float); y = np.asarray(y, float)
    n = len(x)
    rho = _spearman(x, y)
    if n < 4:
        return rho, rho, rho
    out = []
    for _ in range(n_boot):
        idx = RNG.integers(0, n, size=n)
        out.append(_spearman(x[idx], y[idx]))
    lo = float(np.percentile(out, 100 * alpha / 2))
    hi = float(np.percentile(out, 100 * (1 - alpha / 2)))
    return rho, lo, hi


# --------------------------------------------------------------------------- #
# StatsBomb 2022 team xG-for per 90 (the receipts).
# --------------------------------------------------------------------------- #
def statsbomb_team_xg_per90():
    """Return {team_name: {xg_for, minutes, xg_per90, matches}} from raw SB JSON.

    Aggregates shot.statsbomb_xg per team across all 64 WC2022 matches, and the
    minutes each team played (sum of match max-minute across periods 1-4, so ET
    counts). Per-90 = xg_for / (minutes / 90).
    """
    import pandas as pd

    mdf = pd.read_parquet(SB_MATCHES_PARQUET)
    wc_ids = [str(m) for m in mdf["match_id"].tolist()]

    xg_for = defaultdict(float)
    minutes = defaultdict(float)
    matches_played = defaultdict(int)
    n_files = 0
    for mid in wc_ids:
        fp = SB_EVENTS_DIR / f"{mid}.json"
        if not fp.exists():
            continue
        ev = json.load(open(fp))
        n_files += 1
        teams_in_match = set()
        # Determine match duration per team: last event minute per period summed.
        # Simpler + robust: total match minutes = max(minute)+1 across all events,
        # both teams played the same minutes (full match), so credit both.
        max_min = 0
        for e in ev:
            t = e.get("team", {}).get("name")
            if t:
                teams_in_match.add(t)
            m = e.get("minute")
            if isinstance(m, int) and m > max_min:
                max_min = m
            if e.get("type", {}).get("name") == "Shot":
                xg = e.get("shot", {}).get("statsbomb_xg")
                if xg is not None and t:
                    xg_for[t] += float(xg)
        match_minutes = float(max_min + 1)  # +1: minute index is 0-based-ish
        for t in teams_in_match:
            minutes[t] += match_minutes
            matches_played[t] += 1
    out = {}
    for t, xg in xg_for.items():
        mins = minutes.get(t, 0.0)
        per90 = (xg / (mins / 90.0)) if mins > 0 else 0.0
        out[t] = {"xg_for": round(xg, 3), "minutes": round(mins, 1),
                  "xg_per90": round(per90, 4), "matches": matches_played.get(t, 0)}
    _log(f"  StatsBomb: {n_files} WC2022 event files -> {len(out)} teams")
    return out


# --------------------------------------------------------------------------- #
# Hero-play surface (OFF-BALL controllable space), named-attribution.
# --------------------------------------------------------------------------- #
def _downsample(surface: np.ndarray, out_ny: int, out_nx: int) -> np.ndarray:
    ny, nx = surface.shape
    if (ny, nx) == (out_ny, out_nx):
        return surface
    ys = np.linspace(0, ny, out_ny + 1).astype(int)
    xs = np.linspace(0, nx, out_nx + 1).astype(int)
    out = np.zeros((out_ny, out_nx), dtype=np.float64)
    for i in range(out_ny):
        for j in range(out_nx):
            out[i, j] = surface[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean()
    return out


def export_hero_surface():
    """Per-frame OFF-BALL controllable-space surface over the Messi-35' window.

    The surface is the attacking team's pitch control restricted to cells OWNED
    (argmax-influence) by an OFF-BALL attacker (carrier + GKs masked out). That
    is the SMS-native field: the receiving space the off-ball attackers are
    actively holding, frame by frame. We also annotate the top off-ball
    space-holder per frame by NAME (space_io gives identity row-for-row).
    """
    # Compute on a FINE grid (>= output resolution so downsampling never hits an
    # empty block -> NaN). The leaderboard's coarse grid would UPSAMPLE here.
    cg = make_grid(nx=50, ny=34)
    out_ny, out_nx = HERO_OUT_GRID

    frames_out = []
    raw_maxes = []
    top_names = []
    n_seen = 0
    for fr in space_io.read_match(HERO_MATCH, sampling_stride=6,
                                  periods=(HERO_PERIOD,)):
        t_s = fr.timestamp_s
        if t_s < HERO_START_S or t_s > HERO_END_S:
            # Stop once we've passed the window (frames are time-ordered).
            if t_s > HERO_END_S:
                break
            continue
        n_seen += 1
        carrier = _ball_carrier_row(fr)
        ctrl = control_surface(fr.players, fr.ball_m, cg, include_gk=True)
        ps = player_space(ctrl, cg, attacking_only=True)

        # Build the off-ball ownership mask on the compute grid.
        infl = ctrl["player_influence"]            # (k, ny, nx)
        idx = ctrl["player_idx"]
        is_att = ctrl["player_is_attacking"]
        sub = is_att
        owner = np.argmax(infl[sub], axis=0)       # (ny, nx) over attackers
        sub_idx = idx[sub]
        attack_control = ctrl["attack_control"]

        offball_surf = np.zeros(cg.shape, dtype=np.float64)
        best_area = -1.0
        best_name = ""
        for k, orig_i in enumerate(sub_idx):
            idn = fr.identities[int(orig_i)]
            if idn.is_gk or int(orig_i) == carrier:
                continue
            cells = owner == k
            offball_surf += cells * attack_control  # off-ball receiving control
            a = float(ps.get(int(orig_i), {}).get("area_m2", 0.0))
            if a > best_area:
                best_area = a
                best_name = idn.name

        surf_ds = _downsample(offball_surf, out_ny, out_nx)
        rmax = float(surf_ds.max())
        raw_maxes.append(rmax)
        top_names.append(best_name)
        frames_out.append({
            "t_s": round(t_s, 2),
            "frame_num": int(fr.frame_num),
            "ball_xy": [round(float(fr.ball_m[0]), 2), round(float(fr.ball_m[1]), 2)],
            "in_possession_team": fr.in_possession_team,
            "top_offball": best_name,
            "surface_raw": surf_ds,
            "raw_max": round(rmax, 5),
        })

    gmax = max(raw_maxes) if raw_maxes else 1.0
    gmax = gmax if gmax > 0 else 1.0
    for fr in frames_out:
        s = fr.pop("surface_raw") / gmax
        fr["surface"] = [[round(float(v), 4) for v in row] for row in s]

    payload = {
        "metric": "sms",
        "title": "SMS — Self-Made Space: where Argentina's off-ball runners open the pitch",
        "description": ("Per-frame OFF-BALL controllable receiving space (attacking "
                        "pitch control owned by a player who is NOT the ball-carrier, "
                        "goalkeepers excluded), over the Messi 35' build-up vs Australia. "
                        "Bright cells are space an off-ball Argentine is actively holding "
                        "for a pass to arrive into — space-native (m^2 of control), not "
                        "xT-weighted."),
        "match_id": HERO_MATCH,
        "period": HERO_PERIOD,
        "start_s": HERO_START_S,
        "end_s": HERO_END_S,
        "hz": round(30.0 / 6, 2),
        "n_frames": len(frames_out),
        "grid": {"nx": out_nx, "ny": out_ny, "length_m": 105.0, "width_m": 68.0},
        "global_max": round(gmax, 5),
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "frames": frames_out,
    }
    OUT_SURFACE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_SURFACE, "w") as fh:
        json.dump(payload, fh)
    _log(f"  hero surface: {len(frames_out)} frames -> {OUT_SURFACE}")
    return payload


# --------------------------------------------------------------------------- #
# Main.
# --------------------------------------------------------------------------- #
def main():
    try:
        LOG_PATH.unlink()
    except OSError:
        pass
    t_all = time.time()
    _log("=" * 70)
    _log(f"SMS — Self-Made Space  | stride={STRIDE} (~2Hz) grid={GRID_NX}x{GRID_NY} "
         f"periods={PERIODS}")
    _log(f"sample matches ({len(SAMPLE_MATCHES)}): {SAMPLE_MATCHES}")
    _log("=" * 70)

    grid = make_grid(nx=GRID_NX, ny=GRID_NY)

    acc_player: dict = {}
    acc_team: dict = defaultdict(lambda: {"name": "", "total": []})
    team_names: dict = {}
    match_team_frames: dict = defaultdict(list)
    matches_done = []
    total_frames = 0

    for mid in SAMPLE_MATCHES:
        try:
            n = accumulate_match(mid, grid, acc_player, acc_team, team_names,
                                 match_team_frames)
            matches_done.append(mid)
            total_frames += n
        except Exception as e:  # keep going; disclose what we got
            _log(f"  !! {mid} FAILED: {type(e).__name__}: {e}")

    _log(f"\nACCUMULATION DONE: {total_frames} frames over {len(matches_done)} matches "
         f"[{time.time()-t_all:.1f}s]")

    # --- player leaderboard (occlusion-gated, tie-aware) ------------------- #
    MIN_VIS = 40  # require >= 40 VISIBLE off-ball frames to rank a player
    players_rows = []
    for key, rec in acc_player.items():
        vis_n = rec["vis_n"]
        if vis_n < MIN_VIS:
            continue
        mean_t, lo_t, hi_t = _boot_mean_ci(rec["total"])
        mean_s, lo_s, hi_s = _boot_mean_ci(rec["self"])
        est_share = rec["est"] / max(rec["est"] + vis_n, 1)
        players_rows.append({
            "name": rec["name"],
            "team": rec["team"],
            "team_id": rec["team_id"],
            "jersey": rec["jersey"],
            "sms_total_area_m2": round(mean_t, 2),
            "sms_total_ci": [round(lo_t, 2), round(hi_t, 2)],
            "sms_self_made_m2": round(mean_s, 2),
            "sms_self_made_ci": [round(lo_s, 2), round(hi_s, 2)],
            "n_frames_visible": vis_n,
            "n_frames_estimated": rec["est"],
            "estimated_share": round(est_share, 3),
            "occlusion_flag": est_share > 0.5,
        })
    players_rows.sort(key=lambda r: -r["sms_total_area_m2"])
    for i, r in enumerate(players_rows):
        r["rank"] = i + 1
    # tie groups: players whose total-CI overlaps the leader of their cluster.
    for r in players_rows:
        r["tie_group"] = None
    g = 0
    i = 0
    while i < len(players_rows):
        lead = players_rows[i]
        lead_lo = lead["sms_total_ci"][0]
        members = [lead]
        j = i + 1
        while j < len(players_rows):
            if players_rows[j]["sms_total_ci"][1] >= lead_lo:
                members.append(players_rows[j]); j += 1
            else:
                break
        if len(members) > 1:
            g += 1
            for mrow in members:
                mrow["tie_group"] = g
        i = j if j > i + 1 else i + 1

    # --- team leaderboard -------------------------------------------------- #
    teams_rows = []
    team_mean_for_receipt = {}
    for tid, rec in acc_team.items():
        if not rec["total"]:
            continue
        mean_t, lo_t, hi_t = _boot_mean_ci(rec["total"])
        teams_rows.append({
            "team": rec["name"],
            "team_id": tid,
            "sms_team_offball_area_m2": round(mean_t, 1),
            "ci": [round(lo_t, 1), round(hi_t, 1)],
            "n_frames": len(rec["total"]),
        })
        team_mean_for_receipt[rec["name"]] = mean_t
    teams_rows.sort(key=lambda r: -r["sms_team_offball_area_m2"])
    for i, r in enumerate(teams_rows):
        r["rank"] = i + 1

    # --- occlusion disclosure (global) ------------------------------------- #
    tot_vis = sum(r["vis_n"] for r in acc_player.values())
    tot_est = sum(r["est"] for r in acc_player.values())
    est_pct = 100.0 * tot_est / max(tot_vis + tot_est, 1)

    # --- THE SO-WHAT: SMS vs StatsBomb xG-for per 90 ----------------------- #
    _log("Computing StatsBomb xG receipt ...")
    sb = statsbomb_team_xg_per90()
    # Join PFF team names (== StatsBomb country names) to per-team mean SMS,
    # using the per-MATCH team means averaged within each team so a team that
    # appears in 2 sampled matches is not double-weighted by frame count.
    team_to_matchmeans = defaultdict(list)
    for (mid, tid), frames in match_team_frames.items():
        if frames:
            team_to_matchmeans[team_names.get(tid, tid)].append(float(np.mean(frames)))
    receipt_rows = []
    xs, ys = [], []
    for team, mmeans in team_to_matchmeans.items():
        if team not in sb:
            continue
        sms_team = float(np.mean(mmeans))
        xg90 = sb[team]["xg_per90"]
        receipt_rows.append({"team": team, "sms": round(sms_team, 1),
                             "xg_per90": xg90, "n_matches_sampled": len(mmeans)})
        xs.append(sms_team); ys.append(xg90)
    receipt_rows.sort(key=lambda r: -r["sms"])
    rho, rho_lo, rho_hi = _spearman_boot_ci(xs, ys) if len(xs) >= 4 else (0.0, 0.0, 0.0)
    n_teams = len(xs)
    if rho > 0.15:
        reading = (f"Teams whose attackers generate more off-ball receiving space "
                   f"tend to produce more xG (rho={rho:.2f}); correlation, not causation.")
    elif rho < -0.15:
        reading = (f"More off-ball space did NOT translate to more xG in this sample "
                   f"(rho={rho:.2f}); space-native volume is not the same as threat.")
    else:
        reading = (f"Off-ball space volume and xG-for are roughly uncorrelated here "
                   f"(rho={rho:.2f}); SMS is a style signal, not a threat proxy "
                   f"(that is the P-OBSO bridge's job).")

    xg_receipt = {
        "rho": round(rho, 3),
        "ci": f"[{rho_lo:.2f}, {rho_hi:.2f}] (bootstrap 95%)",
        "n": n_teams,
        "unit": "team mean off-ball controllable space (m^2) vs StatsBomb xG-for per 90",
        "reading": reading,
        "rows": receipt_rows,
    }

    # --- write leaderboard JSON ------------------------------------------- #
    meta = {
        "metric": "SMS",
        "metric_full": "Self-Made Space",
        "units": "m^2 (square metres of off-ball controllable receiving space)",
        "definition": ("Per attacking OFF-BALL outfield player, the controllable "
                       "receiving space they hold (pitch-control area, team-control "
                       "weighted), excluding the ball-carrier and goalkeepers. "
                       "sms_self_made_m2 = total - static(velocity-zeroed) baseline, "
                       "isolating space created by movement/positioning."),
        "space_native": True,
        "xt_weighted": False,
        "stride": STRIDE,
        "approx_hz": round(30.0 / STRIDE, 2),
        "grid": {"nx": GRID_NX, "ny": GRID_NY},
        "periods": list(PERIODS),
        "matches_sampled": matches_done,
        "n_matches_sampled": len(matches_done),
        "total_frames_sampled": total_frames,
        "min_visible_frames_to_rank": MIN_VIS,
        "occlusion": {
            "gate": "per-frame space credited only when the player is VISIBLE",
            "global_estimated_pct": round(est_pct, 1),
            "note": ("~40.9% of PFF positions are ESTIMATED (biased toward forwards/"
                     "wingers); gated claims use VISIBLE frames only and rows carry "
                     "estimated_share + occlusion_flag."),
        },
        "honesty": ("tie_group clusters players whose total-area bootstrap CIs overlap "
                    "the cluster leader — overlapping values are not falsely ranked."),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    payload = {
        "meta": meta,
        "players": players_rows,
        "teams": teams_rows,
        "xg_receipt": xg_receipt,
    }
    OUT_LEADERBOARD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_LEADERBOARD, "w") as fh:
        json.dump(payload, fh, indent=2)
    _log(f"leaderboard -> {OUT_LEADERBOARD}  "
         f"({len(players_rows)} players, {len(teams_rows)} teams)")

    # --- hero surface ------------------------------------------------------ #
    _log("Exporting hero-play surface (Messi 35') ...")
    export_hero_surface()

    # --- console summary --------------------------------------------------- #
    _log("\nTOP 10 PLAYERS by SMS (off-ball controllable space, m^2):")
    for r in players_rows[:10]:
        flag = " [OCCL]" if r["occlusion_flag"] else ""
        tg = f" tie#{r['tie_group']}" if r["tie_group"] else ""
        _log(f"  #{r['rank']:<2} {r['name']:<22} {r['team']:<14} "
             f"{r['sms_total_area_m2']:6.1f} m^2  CI{r['sms_total_ci']}  "
             f"self-made={r['sms_self_made_m2']:.1f}  n={r['n_frames_visible']}"
             f"{tg}{flag}")
    _log("\nTEAM SMS:")
    for r in teams_rows:
        _log(f"  #{r['rank']:<2} {r['team']:<14} {r['sms_team_offball_area_m2']:7.1f} m^2 "
             f"CI{r['ci']}  n={r['n_frames']}")
    _log(f"\nxG RECEIPT: rho={xg_receipt['rho']} {xg_receipt['ci']} n={xg_receipt['n']}")
    _log(f"  {xg_receipt['reading']}")
    _log(f"\nALL DONE in {time.time()-t_all:.1f}s")
    _log("EXIT_OK")


if __name__ == "__main__":
    main()
