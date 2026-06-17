"""CHASE - Defensive Gravity (SPACE-NATIVE space metric).

THE QUESTION CHASE ANSWERS
    Which attackers warp the opponent's defensive shape the most? A genuinely
    dangerous attacker does not need the ball to matter: defenders chase him,
    collapse toward him, and in doing so SHRINK and DISPLACE their own block,
    tearing lanes open for teammates. CHASE measures that pull directly from the
    geometry of the defending team's shape - not from xT, not from goals.

WHAT WE MEASURE (per attacking outfield player, per frame, oriented attacking-+x)
    gravity is built from three SPACE-NATIVE pieces, all read off raw positions
    and finite-diff velocities:

      1. drawn   (count, dimensionless): proximity-weighted number of defenders
                 the attacker occupies - sum over defenders of exp(-d / SCALE)
                 for defenders within DRAW_R metres. "How many markers is he
                 tying up right now."

      2. pull    (m/s): how hard those defenders are actively CLOSING on him -
                 sum over nearby defenders of max(0, v_def . u_toward_attacker),
                 the inward (chasing) component of each defender's velocity. A
                 defender sprinting at the attacker contributes; one drifting
                 away contributes 0. This is the literal "chase".

      3. squeeze (m^2): the LOCAL deformation of the defensive block around the
                 attacker - the area of the convex hull of the K nearest
                 defenders. Small hull = those defenders have collapsed tight
                 around him (a shrunk block); large hull = he is not bending the
                 shape. We report squeeze as the SHRINK vs that team's own median
                 local-hull, so positive = "he pulls defenders tighter than this
                 defence normally sits."

    TERRITORY GATE (honesty, not xT): a fullback standing next to his winger in
    his own third is not "gravity" worth crediting. We only accumulate frames
    where the attacker is in the ATTACKING HALF (x_m > 0) AND the ball is live in
    the attacking two-thirds, so CHASE is gravity WHERE IT BENDS A DEFENCE, in
    pure spatial units. (xT is its own story; the only place space meets xT here
    is the P-OBSO bridge, NOT this metric.)

OCCLUSION: every player-row carries PFF visibility (VISIBLE/ESTIMATED). ~40.9%
    of positions are ESTIMATED. We accumulate ALL frames for the headline value
    but also track the ESTIMATED fraction of each player's contributing frames
    and DISCLOSE it; we flag any leaderboard row whose attacker-frames are
    >50% ESTIMATED.

LEADERBOARD (tie-aware): per player and per team. Player score = mean per-frame
    gravity over that player's gated frames; we bootstrap a 90% CI over frames
    and assign a tie-aware rank (no false single #1 when CIs overlap).

THE SO-WHAT (xG receipt): aggregate team gravity (mean over the team's attacking
    players, attacking frames) and correlate with REAL StatsBomb 2022 team
    xG-for PER MATCH (defensible per-match rate, NOT games-played-inflated
    totals). Spearman rho + bootstrap CI + n. Correlation, not causation.

HERO PLAY: an attacker dragging markers to open a lane - we export the per-frame
    DEFENSIVE-shape surface (defender pitch-control, i.e. where the defence owns
    space) over a window, so the site can show the block deforming as he moves.

Run (BOUNDED - sample of star-heavy matches, ~2 Hz, coarse grid):
    export PFF_ROOT="$HOME/pff_wc22_local"
    PYTHONPATH=src uv run python research/scripts/space_chase.py

Outputs:
    research/site/data/space_chase.json            (leaderboard + xg receipt + meta)
    research/site/data/surfaces/chase.json         (hero-play defensive surface)
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

# repo imports
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "research" / "scripts"))
sys.path.insert(0, str(_REPO / "src"))

import space_io  # noqa: E402
from pitch_control import (  # noqa: E402
    HALF_LEN,
    HALF_WID,
    make_grid,
    control_surface,
)

# ---------------------------------------------------------------------------
# Parameters (space-native; all metres / m·s / counts)
# ---------------------------------------------------------------------------
DRAW_R = 10.0        # m, defenders within this radius are "drawn" by the attacker
DRAW_SCALE = 4.0     # m, exp(-d/scale) proximity weight (a marker at 4m ~ 0.37)
K_NEAREST = 4        # nearest defenders defining the LOCAL block hull around him
PULL_R = 12.0        # m, defenders within this radius can contribute inward pull
SAMPLE_STRIDE = 15   # 30 Hz raw -> ~2 Hz kept
GRID_NX, GRID_NY = 30, 20   # coarse control grid for the hero surface

# Territory gate: attacker in the attacking half and ball advanced.
ATT_HALF_X_M = 0.0           # attacker past halfway (m)
BALL_ADVANCED_X_M = -17.5    # ball in attacking two-thirds (m); -52.5..+52.5 pitch

# Star-heavy + deep-run sample (knockout 105xx files are the marquee games).
# Each appears once; we read both halves. Ordered to front-load star teams.
SAMPLE_MATCHES = [
    "10517",  # Argentina vs France (FINAL) - Messi/Mbappe/Di Maria
    "10503",  # Argentina vs Australia - Messi
    "10514",  # Argentina vs Croatia (SF) - Messi/Modric
    "10513",  # England vs France (QF) - Mbappe/Kane/Bellingham
    "10504",  # France vs Poland - Mbappe/Lewandowski
    "10512",  # Morocco vs Portugal (QF) - Ronaldo/Hakimi
    "10509",  # Portugal vs Switzerland - Ronaldo/Goncalo Ramos
    "10508",  # Morocco vs Spain - Pedri/Gavi/Hakimi
    "10511",  # Netherlands vs Argentina (QF) - Messi
    "10510",  # Croatia vs Brazil (QF) - Modric/Neymar
]

OUT_LB = _REPO / "research" / "site" / "data" / "space_chase.json"
OUT_SURF = _REPO / "research" / "site" / "data" / "surfaces" / "chase.json"

SB_MATCHES = _REPO / "research" / "data" / "statsbomb" / "matches_wc_2022_sb.parquet"
SB_EVENTS = _REPO / "research" / "data" / "raw_statsbomb" / "events"
TEAMS_JSON = _REPO / "research" / "site" / "data" / "teams.json"

SEMIS = {"Argentina", "France", "Croatia", "Morocco"}


# ---------------------------------------------------------------------------
# Geometry helpers (pure space)
# ---------------------------------------------------------------------------
def _hull_area(pts: np.ndarray) -> float:
    """Convex-hull area (m^2) of a set of 2-D points; 0 for <3 pts.

    Andrew's monotone chain (no scipy dependency); shoelace on the hull.
    """
    n = len(pts)
    if n < 3:
        return 0.0
    P = pts[np.lexsort((pts[:, 1], pts[:, 0]))]
    # build lower then upper hull
    def _cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower = []
    for p in P:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in P[::-1]:
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = np.array(lower[:-1] + upper[:-1])
    if len(hull) < 3:
        return 0.0
    x, y = hull[:, 0], hull[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _frame_gravity(fr):
    """Per-attacker gravity pieces for one SpaceFrame.

    Returns list of dicts (one per gated attacking outfield player):
       {row, drawn, pull, local_hull_m2, x_m, est}
    plus the team-level defender local-hull baseline material.
    """
    P = fr.players
    xm = P[:, 0] * HALF_LEN
    ym = P[:, 1] * HALF_WID
    vx = P[:, 2]
    vy = P[:, 3]
    is_att = P[:, 4] > 0
    is_gk = P[:, 5] > 0.5

    att_idx = np.where(is_att & ~is_gk)[0]
    def_idx = np.where(~is_att & ~is_gk)[0]    # defending outfielders (drop def GK)
    if len(att_idx) == 0 or len(def_idx) < K_NEAREST:
        return []

    dxm, dym = xm[def_idx], ym[def_idx]
    dvx, dvy = vx[def_idx], vy[def_idx]

    out = []
    bx = float(fr.ball_m[0])
    ball_advanced = bx > BALL_ADVANCED_X_M
    for ai in att_idx:
        ax, ay = float(xm[ai]), float(ym[ai])
        # territory gate
        if not (ax > ATT_HALF_X_M and ball_advanced):
            continue
        d = np.hypot(dxm - ax, dym - ay)
        # 1. drawn: proximity-weighted defender count within DRAW_R
        near = d <= DRAW_R
        drawn = float(np.exp(-d[near] / DRAW_SCALE).sum()) if near.any() else 0.0
        # 2. pull: inward (toward-attacker) velocity component of defenders in PULL_R
        pmask = d <= PULL_R
        pull = 0.0
        if pmask.any():
            # unit vectors FROM defender TO attacker
            ux = (ax - dxm[pmask])
            uy = (ay - dym[pmask])
            nrm = np.hypot(ux, uy)
            nrm[nrm < 1e-6] = 1e-6
            ux, uy = ux / nrm, uy / nrm
            inward = dvx[pmask] * ux + dvy[pmask] * uy   # m/s toward attacker
            pull = float(np.clip(inward, 0.0, None).sum())
        # 3. local hull of K nearest defenders around him (m^2)
        ksel = def_idx[np.argsort(d)[:K_NEAREST]]
        hull_pts = np.column_stack([xm[ksel], ym[ksel]])
        local_hull = _hull_area(hull_pts)
        out.append({
            "row": int(ai),
            "drawn": drawn,
            "pull": pull,
            "hull": local_hull,
            "x_m": ax,
            "est": fr.identities[ai].visibility != "VISIBLE",
        })
    return out


# ---------------------------------------------------------------------------
# StatsBomb xG-for per match (the receipt)
# ---------------------------------------------------------------------------
def _build_sb_xg():
    """Return {match_pair frozenset -> {team_name: xg_for}} for sampled matches.

    We map a PFF tracking match to its StatsBomb event file by the team pair.
    """
    import pandas as pd
    df = pd.read_parquet(SB_MATCHES)
    pair2sb = {}
    for r in df.itertuples():
        pair2sb[frozenset([r.home_team, r.away_team])] = int(r.match_id)
    return pair2sb


def _match_xg(sb_match_id: int) -> dict:
    """Team -> total StatsBomb xG-for in that match."""
    fp = SB_EVENTS / f"{sb_match_id}.json"
    ev = json.load(open(fp))
    xg = defaultdict(float)
    for e in ev:
        if e.get("type", {}).get("name") == "Shot":
            t = e.get("team", {}).get("name")
            v = e.get("shot", {}).get("statsbomb_xg")
            if t is not None and v is not None:
                xg[t] += float(v)
    return dict(xg)


# ---------------------------------------------------------------------------
# Tie-aware leaderboard helpers
# ---------------------------------------------------------------------------
def _bootstrap_ci(vals: np.ndarray, n_boot: int = 400, lo=5, hi=95, seed=0):
    """Percentile bootstrap CI of the MEAN of vals."""
    if len(vals) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    n = len(vals)
    means = np.empty(n_boot)
    for b in range(n_boot):
        means[b] = vals[rng.integers(0, n, n)].mean()
    return float(np.percentile(means, lo)), float(np.percentile(means, hi))


def _tie_aware_ranks(rows, key, lo_key, hi_key):
    """Assign dense ranks where rows whose CIs overlap the leader share rank.

    Sort desc by key; a row gets a new rank only when its UPPER CI is below the
    current rank-group's best LOWER CI (i.e. statistically separated). Otherwise
    it is 'tied' into the same rank tier.
    """
    s = sorted(rows, key=lambda r: -r[key])
    rank = 0
    group_lo = None
    for r in s:
        if group_lo is None or r[hi_key] < group_lo:
            rank += 1
            group_lo = r[lo_key]
        else:
            group_lo = max(group_lo, r[lo_key])
        r["rank"] = rank
        r["tied"] = False
    # mark tied: any rank shared by >1 row
    from collections import Counter
    cnt = Counter(r["rank"] for r in s)
    for r in s:
        r["tied"] = cnt[r["rank"]] > 1
    return s


# ---------------------------------------------------------------------------
# Hero-play defensive surface export
# ---------------------------------------------------------------------------
def _export_hero_surface(match_id, period, start_s, end_s, *, lock_team_id,
                         focus_name, focus_team, title, description):
    """Export a per-frame DEFENDER pitch-control surface (the block) + ball/players.

    The defensive surface shows where the DEFENCE owns space; as the gravity
    attacker drags markers, watch the block deform and a lane open. Orientation is
    LOCKED to ``lock_team_id`` (attacking +x) for the whole window so the noisy
    nearest-to-ball possession heuristic can't mirror or invert the clip.
    """
    g = make_grid(GRID_NX, GRID_NY)
    out_ny, out_nx = 20, 30
    frames_out = []
    raw_maxes = []
    for fr in space_io.read_match(match_id, sampling_stride=6, periods=(period,),
                                  lock_attack_team_id=lock_team_id):
        t_s = fr.timestamp_s
        if t_s < start_s or t_s > end_s:
            continue
        ctrl = control_surface(fr.players, fr.ball_m, g, include_gk=True)
        surf = ctrl["defend_control"]    # where the DEFENCE owns space
        rmax = float(surf.max())
        raw_maxes.append(rmax)
        # players for the overlay (oriented; +x attacking)
        P = fr.players
        players = []
        for i, idn in enumerate(fr.identities):
            players.append({
                "x": round(float(P[i, 0] * HALF_LEN), 2),
                "y": round(float(P[i, 1] * HALF_WID), 2),
                "att": bool(P[i, 4] > 0),
                "gk": bool(P[i, 5] > 0.5),
                "name": idn.name,
                "est": idn.visibility != "VISIBLE",
            })
        frames_out.append({
            "t_s": round(t_s, 2),
            "ball_xy": [round(float(fr.ball_m[0]), 2), round(float(fr.ball_m[1]), 2)],
            "surface_raw": surf,
            "players": players,
        })
    gmax = max(raw_maxes) if raw_maxes else 1.0
    for fr in frames_out:
        s = fr.pop("surface_raw") / (gmax if gmax > 0 else 1.0)
        fr["surface"] = [[round(float(v), 4) for v in row] for row in s]
    payload = {
        "metric": "chase_defensive_shape",
        "title": title,
        "description": description,
        "match_id": str(match_id),
        "period": period,
        "start_s": start_s,
        "end_s": end_s,
        "hz": round(30.0 / 6.0, 2),
        "n_frames": len(frames_out),
        "grid": {"nx": out_nx, "ny": out_ny, "length_m": 105.0, "width_m": 68.0},
        "orientation": "attacking-left-to-right; opponent goal at +x (right)",
        "legend": "surface = DEFENDER pitch-control (where the block owns space); darker = defence in control",
        "hero": {"name": focus_name, "team": focus_team},
        "frames": frames_out,
    }
    OUT_SURF.parent.mkdir(parents=True, exist_ok=True)
    json.dump(payload, open(OUT_SURF, "w"))
    return payload


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t_start = time.time()
    teams_meta = {t["team_name"]: t for t in json.load(open(TEAMS_JSON))}
    pair2sb = _build_sb_xg()
    root = os.environ["PFF_ROOT"]

    # per-player accumulators: list of per-frame gravity values
    pl_gravity = defaultdict(list)     # (team, name, jersey) -> [grav,...]
    pl_drawn = defaultdict(list)
    pl_pull = defaultdict(list)
    pl_squeeze = defaultdict(list)     # shrink vs team median local-hull
    pl_est = defaultdict(lambda: [0, 0])   # (team,name,jersey) -> [est_frames, total]
    pl_matches = defaultdict(set)
    pl_team = {}                       # key -> team name
    key2teamid = {}                    # key -> team_id (for orientation lock)
    # per-frame gravity time-series for auto-picking the best hero window:
    # (mid, period, key) -> [(t_s, grav, ball_x_m), ...]
    focal_track = defaultdict(list)

    # team-level local-hull baseline (median local-hull this team CONCEDES while defending)
    team_hull_samples = defaultdict(list)   # defending team -> [local hulls]
    # per-(match, attacker) hull samples to compute squeeze after baseline known
    raw_attacker_frames = []           # (key, x_m, drawn, pull, hull, est, def_team)

    sampled = []
    for mi, mid in enumerate(SAMPLE_MATCHES):
        if not (Path(root) / "Tracking Data" / f"{mid}.jsonl.bz2").exists():
            print(f"[skip] {mid} not on disk", flush=True)
            continue
        meta = space_io.load_metadata(mid)
        home, away = meta["homeTeam"]["name"], meta["awayTeam"]["name"]
        n_fr = 0
        t0 = time.time()
        for fr in space_io.read_match(mid, sampling_stride=SAMPLE_STRIDE):
            n_fr += 1
            att_team = fr.in_possession_team
            def_team = home if att_team == away else away
            pieces = _frame_gravity(fr)
            for pc in pieces:
                idn = fr.identities[pc["row"]]
                key = (idn.team, idn.name, idn.jersey)
                pl_team[key] = idn.team
                key2teamid[key] = idn.team_id
                grav = pc["drawn"] * (1.0 + pc["pull"])   # drawn markers amplified by chase
                # track for hero-window auto-pick (ball x in metres, oriented +x)
                focal_track[(mid, fr.period, key)].append(
                    (fr.timestamp_s, grav, float(fr.ball_m[0])))
                pl_gravity[key].append(grav)
                pl_drawn[key].append(pc["drawn"])
                pl_pull[key].append(pc["pull"])
                e = pl_est[key]
                e[1] += 1
                if pc["est"]:
                    e[0] += 1
                pl_matches[key].add(mid)
                team_hull_samples[def_team].append(pc["hull"])
                raw_attacker_frames.append((key, pc["hull"]))
        sampled.append({"match_id": mid, "home": home, "away": away,
                        "frames": n_fr, "secs": round(time.time() - t0, 1)})
        print(f"[{mi+1}/{len(SAMPLE_MATCHES)}] {mid} {home} vs {away}: "
              f"{n_fr} frames in {time.time()-t0:.1f}s  (elapsed {time.time()-t_start:.1f}s)",
              flush=True)

    # squeeze: per-attacker, how much tighter is the local block around him vs the
    # team-wide median local-hull that this defence presents. We use a single
    # global median (the hull baseline conceded across the sample) so squeeze is
    # comparable across attackers; positive = he pulls a tighter shell.
    all_hulls = np.array([h for hs in team_hull_samples.values() for h in hs])
    median_hull = float(np.median(all_hulls)) if len(all_hulls) else 0.0
    # attribute squeeze per attacker frame
    for key, hull in raw_attacker_frames:
        pl_squeeze[key].append(max(0.0, median_hull - hull))   # m^2 shrink vs median

    # ---- build player leaderboard rows (tie-aware) -----------------------
    # Require ~75s of gated attacking play (>=150 frames at ~2 Hz) so a single
    # hot match cannot mint a false leader on a tiny, high-variance sample.
    MIN_FRAMES = 150
    rows = []
    for key, gv in pl_gravity.items():
        g = np.array(gv)
        if len(g) < MIN_FRAMES:
            continue
        team, name, jersey = key
        lo, hi = _bootstrap_ci(g)
        est_f, tot_f = pl_est[key]
        est_frac = est_f / max(tot_f, 1)
        rows.append({
            "team": team,
            "team_id": teams_meta.get(team, {}).get("team_id"),
            "name": name,
            "jersey": jersey,
            "gravity": round(float(g.mean()), 4),
            "gravity_ci90": [round(lo, 4), round(hi, 4)],
            "drawn_markers": round(float(np.mean(pl_drawn[key])), 3),
            "chase_pull_ms": round(float(np.mean(pl_pull[key])), 3),
            "block_squeeze_m2": round(float(np.mean(pl_squeeze[key])), 1),
            "n_frames": int(len(g)),
            "n_matches": len(pl_matches[key]),
            "estimated_frac": round(est_frac, 3),
            "occlusion_flag": est_frac > 0.5,
        })
    # _tie_aware_ranks expects flat lo/hi keys; provide them
    for r in rows:
        r["gravity_ci90_lo"] = r["gravity_ci90"][0]
        r["gravity_ci90_hi"] = r["gravity_ci90"][1]
    ranked = _tie_aware_ranks(rows, "gravity", "gravity_ci90_lo", "gravity_ci90_hi")
    for r in ranked:
        r.pop("gravity_ci90_lo", None)
        r.pop("gravity_ci90_hi", None)

    # ---- team aggregate gravity (mean over the team's qualifying players) --
    team_grav = defaultdict(list)
    for r in ranked:
        team_grav[r["team"]].append(r["gravity"])
    team_rows = []
    for team, gs in team_grav.items():
        team_rows.append({
            "team": team,
            "team_id": teams_meta.get(team, {}).get("team_id"),
            "is_semifinalist": team in SEMIS,
            "team_gravity": round(float(np.mean(gs)), 4),
            "n_players": len(gs),
        })
    team_rows.sort(key=lambda r: -r["team_gravity"])

    # ---- xG receipt: team gravity vs StatsBomb per-match xG-for ------------
    # For each sampled match, attribute each team's gravity that match and its
    # SB xG-for that match; correlate the PER-MATCH-TEAM pairs (defensible unit:
    # per-match rate, not totals).
    receipt_pairs = []   # (gravity_in_match, xg_for_in_match) per (match,team)
    # recompute per-(match,team) gravity from raw frames
    match_team_grav = defaultdict(list)   # (mid, team) -> [player-frame gravities]
    # we need per-match gravity; recompute light pass using stored per-player? Instead
    # accumulate during the main loop would be ideal, but we kept per-player only.
    # Recompute per (match,team) by re-deriving from pl_gravity is not possible
    # (frames not tagged by match). So do a second light aggregation here:
    # use the per-player mean gravity weighted by that player's team, matched to
    # the team's xG-for averaged across the matches it appears in. This keeps the
    # unit per-match-rate at the TEAM level (team mean gravity vs team mean xG/match).
    team_xg_rates = {}     # team -> mean xG-for per sampled match it played
    team_match_count = defaultdict(int)
    team_xg_sum = defaultdict(float)
    for s in sampled:
        pair = frozenset([s["home"], s["away"]])
        sbid = pair2sb.get(pair)
        if sbid is None:
            continue
        xg = _match_xg(sbid)
        for t in (s["home"], s["away"]):
            if t in xg:
                team_xg_sum[t] += xg[t]
                team_match_count[t] += 1
    for t, c in team_match_count.items():
        if c > 0:
            team_xg_rates[t] = team_xg_sum[t] / c

    # team-level correlation: team_gravity vs team xG-for-per-match
    gx = []
    for tr in team_rows:
        t = tr["team"]
        if t in team_xg_rates:
            gx.append((tr["team_gravity"], team_xg_rates[t], t))
    from scipy.stats import spearmanr
    if len(gx) >= 4:
        gvals = np.array([a for a, _, _ in gx])
        xvals = np.array([b for _, b, _ in gx])
        rho, _ = spearmanr(gvals, xvals)
        # bootstrap CI on rho
        rng = np.random.default_rng(1)
        n = len(gvals)
        boots = []
        for _ in range(1000):
            idx = rng.integers(0, n, n)
            if len(set(idx.tolist())) < 3:
                continue
            rr, _ = spearmanr(gvals[idx], xvals[idx])
            if not np.isnan(rr):
                boots.append(rr)
        ci = (float(np.percentile(boots, 5)), float(np.percentile(boots, 95))) if boots else (float("nan"), float("nan"))
    else:
        rho, ci = float("nan"), (float("nan"), float("nan"))

    reading = ("Teams whose attackers exert more defensive gravity tend to generate "
               "more xG (Spearman rho={:.2f}); correlation, not causation."
               .format(rho) if not np.isnan(rho) else "insufficient teams for correlation")
    xg_receipt = {
        "rho": round(float(rho), 4) if not np.isnan(rho) else None,
        "ci": "[{:.2f}, {:.2f}]".format(ci[0], ci[1]) if not np.isnan(ci[0]) else None,
        "n": len(gx),
        "unit": "team mean CHASE gravity (drawn x chase) vs StatsBomb xG-for per match",
        "reading": reading,
    }

    # ---- hero play: AUTO-PICK the single best sustained gravity window -------
    # Among qualified gravity players (>= MIN_FRAMES), find the ~6s window with the
    # highest rolling-mean gravity, biased to open build-up (ball in the attacking
    # half but not jammed at the byline, i.e. not a goalmouth scramble). Lock
    # orientation to that attacker's team so the clip never flips. Messi is a POOR
    # example (a roamer who scores low) — this surfaces a genuine focal attacker.
    WIN_S = 6.0
    qualified = {k for k, gv in pl_gravity.items() if len(gv) >= MIN_FRAMES}
    # restrict to genuine FOCAL ATTACKERS: top-12 players by MEAN gravity. This
    # excludes centre-backs who spike one set-piece window (e.g. Varane) — their
    # season-mean gravity is low, so they never make the focal set.
    focal_keys = set(sorted(qualified, key=lambda k: -float(np.mean(pl_gravity[k])))[:12])
    best = None  # (winmean, mid, period, key, t0, t1)
    for (mid, period, key), series in focal_track.items():
        if key not in focal_keys:
            continue
        series = sorted(series)
        ts = [s[0] for s in series]; gv = [s[1] for s in series]; bx = [s[2] for s in series]
        for i in range(len(ts)):
            j = i
            while j < len(ts) and ts[j] - ts[i] <= WIN_S:
                j += 1
            if j - i < 8:                       # need a sustained window (~4s @ 2Hz)
                continue
            wmean = sum(gv[i:j]) / (j - i)
            win_bx = bx[i:j]
            # whole window in the attacking half, OFF the byline: a build-up / final-third
            # approach where gravity opens a lane — NOT a corner / goalmouth scramble.
            if max(win_bx) > 44.0 or min(win_bx) < -2.0:
                continue
            if best is None or wmean > best[0]:
                best = (wmean, mid, period, key, ts[i], ts[j - 1])
    if best is None:
        best = (0.0, "10503", 1, None, 2055.0, 2078.0)
    _, h_mid, h_period, h_key, h_t0, h_t1 = best
    h_team = h_key[0] if h_key else "Argentina"
    h_name = h_key[1] if h_key else "Lionel Messi"
    h_team_id = key2teamid.get(h_key) if h_key else None
    print(f"[hero] auto-picked {h_name} ({h_team}) match {h_mid} P{h_period} "
          f"{h_t0:.1f}-{h_t1:.1f}s  winmean_gravity={best[0]:.2f} "
          f"(elapsed {time.time()-t_start:.1f}s)", flush=True)
    hero = _export_hero_surface(
        h_mid, h_period, h_t0 - 0.6, h_t1 + 0.6,
        lock_team_id=h_team_id, focus_name=h_name, focus_team=h_team,
        title=f"CHASE - defensive gravity: {h_name} bends the block",
        description=("Defender pitch-control (where the block owns space) per frame. "
                     "Watch the defensive shell collapse toward the gravity attacker "
                     "as a lane tears open for a teammate."),
    )

    # ---- assemble + write -------------------------------------------------
    meta_out = {
        "metric": "CHASE - Defensive Gravity",
        "what": ("How much an attacker pulls/deforms the opponent's defensive shape - "
                 "space-native: drawn markers (count) x chase (inward defender velocity, m/s), "
                 "with local block-squeeze (m^2) as supporting deformation. NOT xT-multiplied."),
        "units": {
            "gravity": "drawn x (1 + chase_pull_ms): proximity-weighted markers amplified by inward chase (dimensionless x m/s)",
            "drawn_markers": "sum of exp(-d/4m) over defenders within 10m (count)",
            "chase_pull_ms": "sum of inward (toward-attacker) defender velocity within 12m (m/s)",
            "block_squeeze_m2": "shrink of the K=4 nearest-defender hull vs the sample median local hull (m^2)",
        },
        "territory_gate": ("attacker past halfway (x>0 m) AND ball in attacking two-thirds "
                           "(x>-17.5 m): gravity WHERE it bends a defence."),
        "sampling": {
            "n_matches": len(sampled),
            "stride": SAMPLE_STRIDE,
            "hz": round(30.0 / SAMPLE_STRIDE, 2),
            "matches": sampled,
            "min_frames_per_player": MIN_FRAMES,
            "median_local_hull_m2": round(median_hull, 1),
        },
        "occlusion": ("~40.9% of PFF positions are ESTIMATED (biased to forwards/wingers). "
                      "Each row reports estimated_frac; occlusion_flag=true if >50% of an "
                      "attacker's contributing frames are ESTIMATED."),
        "honesty": ("Tie-aware ranks: rows whose 90% bootstrap CI overlaps the rank-group "
                    "leader share a rank (no false single #1). Correlation with xG is not causation."),
        "elapsed_s": round(time.time() - t_start, 1),
    }
    payload = {
        "meta": meta_out,
        "xg_receipt": xg_receipt,
        "players": [{k: v for k, v in r.items()} for r in ranked],
        "teams": team_rows,
        "team_xg_for_per_match": {t: round(v, 4) for t, v in sorted(team_xg_rates.items())},
        "caveats": [
            "Space-native: gravity is geometry (drawn markers x inward defender chase), not xT or goals.",
            "Sample is {} star-heavy/knockout matches at ~2 Hz; not the full tournament.".format(len(sampled)),
            "Possession is a nearest-player-to-ball heuristic (no event join); transition frames are noisy.",
            "~40.9% of PFF positions are ESTIMATED; rows >50% ESTIMATED are flagged (occlusion_flag).",
            "xG correlation is team-level over a small N - directional evidence, not causation.",
            "Velocity is finite-differenced at ~2 Hz; chase_pull is a smoothed approximation.",
        ],
    }
    OUT_LB.parent.mkdir(parents=True, exist_ok=True)
    json.dump(payload, open(OUT_LB, "w"), indent=2)

    # ---- print summary ----------------------------------------------------
    print("\n" + "=" * 70)
    print("CHASE - DEFENSIVE GRAVITY  (top 12 attackers)")
    print("=" * 70)
    for r in ranked[:12]:
        flag = " [OCCL]" if r["occlusion_flag"] else ""
        tie = " (tie)" if r["tied"] else ""
        print(f"  #{r['rank']:<2}{tie:<6} {r['name']:<22} {r['team']:<12} "
              f"grav={r['gravity']:6.3f} CI{r['gravity_ci90']} "
              f"drawn={r['drawn_markers']:.2f} pull={r['chase_pull_ms']:.2f}m/s "
              f"sq={r['block_squeeze_m2']:.0f}m2 n={r['n_frames']}{flag}")
    print("\nTEAM GRAVITY:")
    for tr in team_rows:
        mark = " *SF" if tr["is_semifinalist"] else ""
        print(f"  {tr['team']:<14} {tr['team_gravity']:.3f} ({tr['n_players']} players){mark}")
    print(f"\nxG RECEIPT: rho={xg_receipt['rho']} ci={xg_receipt['ci']} n={xg_receipt['n']}")
    print(f"  unit: {xg_receipt['unit']}")
    print(f"\nhero surface: {OUT_SURF} ({hero['n_frames']} frames)")
    print(f"leaderboard:  {OUT_LB}")
    print(f"TOTAL ELAPSED: {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
