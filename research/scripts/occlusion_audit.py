#!/usr/bin/env python3
"""
OCCLUSION / VISIBILITY AUDIT for PFF FC World Cup 2022 event-snapshot tracking.

PFF FC tracking is derived from BROADCAST video, so a large fraction of player
(x,y) positions at the event instant are NOT directly observed -- they are
ESTIMATED (imputed) by PFF when the player is off-camera/occluded. PFF exposes
this per player-row inside each event snapshot. THIS SCRIPT FINDS THAT FIELD,
QUANTIFIES THE ESTIMATED FRACTION, AND EXPOSES A REUSABLE GATE.

THE FIELD (verified against the raw JSON, all 64 matches)
---------------------------------------------------------
Each player row inside an event's "homePlayers"/"awayPlayers" list carries:
    "visibility": one of {"VISIBLE", "ESTIMATED"}   <-- the gate field
    "confidence": one of {"HIGH", "MEDIUM", "LOW"}   <-- a secondary signal
A row's position is directly tracked iff visibility == "VISIBLE".
A row is imputed/occluded iff   visibility == "ESTIMATED".
Both keys are present on 100% of player rows in all 64 event files (no missing
keys), so the gate never has to guess. The ball entries also carry "visibility"
but this audit is about PLAYER positions (the off-ball-metric substrate), so the
headline numbers are over player rows only; ball visibility is reported
separately as context.

THE GATE (importable helper)
----------------------------
    from occlusion_audit import is_estimated, is_visible, VISIBILITY_FIELD, ESTIMATED_VALUE
    if is_estimated(player_snapshot):   # skip / down-weight this player-row
        ...
Other scripts gate an EVENT by requiring the player rows they depend on (e.g.
the receiver, or all off-ball attackers) to be VISIBLE.

ON-BALL vs OFF-BALL
-------------------
The single on-ball player per event = gameEvents.playerId (the actor of the
game event), falling back to the possession-event actor id (passer/carrier/
shooter/...). Verified on match 10502: gameEvents.playerId and the possession
actor agree on 1336 events, disagree on 2, and gameEvents.playerId covers 800
more events that have no possession actor -- so gameEvents.playerId-first is the
robust choice. Everyone else in the 22-row snapshot is off-ball.

ATTACKING vs DEFENDING side
---------------------------
The team in possession = the side (home/away) the on-ball player belongs to.
Its 11 rows are "attacking"; the opponent's 11 rows are "defending". Events with
no resolvable on-ball player are excluded from the attack/defend split (but still
counted in the overall / on-ball / off-ball-by-team breakdowns where possible).

CONDITIONAL MISSINGNESS (the load-bearing robustness fact)
----------------------------------------------------------
The gate is NOT missing-at-random along THREE compounding axes:
  1. DISTANCE-FROM-BALL: occlusion degrades MONOTONICALLY -- ~6-15% ESTIMATED
     within 10 m of the ball, rising to ~99% beyond 60 m.
  2. LATERAL |y|: central play (|y|<8 m) is more occluded than wide play.
  3. POSITION GROUP: at the SAME distance-from-ball, forwards (CF) and especially
     goalkeepers (GK) are far less visible than midfielders (CM). e.g. within the
     30-40 m bin the VISIBLE-keep rate is 0.55 for CM, 0.37 for CF, 0.07 for GK.
So a VISIBLE-only gate systematically RETAINS near-ball central midfielders and
DROPS far-from-ball forwards, wide runners and keepers -- exactly the off-ball
attacking roles a Space metric most wants to rank.

CRITICAL (this round's fix): the position bias is PARTLY ORTHOGONAL to distance.
Distance-stratifying the leaderboard does NOT remove it -- forwards and keepers
stay under-sampled relative to midfielders WITHIN every distance bin. Therefore
"report results per distance-from-ball stratum" is NOT a sufficient cure on its
own. The "gate_bias" block now reports the VISIBLE-keep rate (a) per distance
bin, (b) per |y| stratum, (c) per positionGroupType, (d) per (position x
distance) cell, AND (e) per individual player (with surviving-N and the
cross-player keep-rate dispersion), over all 64 matches, for the attacking-
off-ball population (the exact rows a Space leaderboard ranks). The only SAFE
downstream guidance is remedy (b): report the per-player / per-position gate
keep-rate ACTUALLY achieved per leaderboard row and flag positions/players whose
post-gate surviving sample is small or whose keep-rate is low as UNDER-SAMPLED;
optionally drop players below a minimum surviving-N.

positionGroupType comes straight off each event player row (jerseyNum,
confidence, visibility, x, y, speed, playerId, positionGroupType) -- 100%
populated across all 64 matches and verified to agree with the Rosters files
(0 disagreements on match 10502), so no string<->int roster join is needed.

Stdlib only: json, glob, os, collections, math. No external deps.

Run (from repo root):
    PYTHONPATH=src uv run python research/scripts/occlusion_audit.py
Writes:
    research/data/occlusion_audit.json
"""
import json
import glob
import os
import math
import statistics
import collections

# ---------------------------------------------------------------------------
# Paths -- mirror the EDA templates' loader (PFF event snapshots).
# ---------------------------------------------------------------------------
PFF_ROOT = os.environ.get(
    "PFF_ROOT", "/Users/nick/pff_wc22_local"
)
EVENT_DIR = os.path.join(PFF_ROOT, "Event Data")
META_DIR = os.path.join(PFF_ROOT, "Metadata")

OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "occlusion_audit.json",
)

# ---------------------------------------------------------------------------
# THE GATE -- documented constants + helpers other scripts import.
# ---------------------------------------------------------------------------
VISIBILITY_FIELD = "visibility"      # per-player-row key in homePlayers/awayPlayers
VISIBLE_VALUE = "VISIBLE"            # position is directly tracked
ESTIMATED_VALUE = "ESTIMATED"        # position is imputed / occluded
CONFIDENCE_FIELD = "confidence"      # secondary signal: HIGH / MEDIUM / LOW


def is_estimated(player_snapshot):
    """True iff this player row's (x,y) is imputed/occluded (visibility==ESTIMATED).

    `player_snapshot` is one dict from an event's homePlayers/awayPlayers list.
    Returns False for VISIBLE rows. If the field is somehow absent (never seen in
    the 64-match WC22 corpus) we treat it as NOT estimated and let callers decide;
    pair with `has_visibility_field` if you want to hard-gate on presence.
    """
    return player_snapshot.get(VISIBILITY_FIELD) == ESTIMATED_VALUE


def is_visible(player_snapshot):
    """True iff this player row's (x,y) is directly tracked (visibility==VISIBLE)."""
    return player_snapshot.get(VISIBILITY_FIELD) == VISIBLE_VALUE


def has_visibility_field(player_snapshot):
    """True iff the row carries the visibility key at all (for strict gating)."""
    return VISIBILITY_FIELD in player_snapshot


# ---------------------------------------------------------------------------
# Conditional-missingness binning.
# ---------------------------------------------------------------------------
# Distance-from-ball bins (metres). Occlusion rises monotonically across these.
_DIST_BINS = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60),
              (60, float("inf"))]
_DIST_LABELS = ["0-10m", "10-20m", "20-30m", "30-40m", "40-50m", "50-60m",
                "60m+"]
# Lateral |y| bins (metres). Pitch y in [-34, 34]; central play is more occluded.
_ABSY_BINS = [(0, 8), (8, 16), (16, 24), (24, float("inf"))]
_ABSY_LABELS = ["|y|0-8m_central", "|y|8-16m", "|y|16-24m", "|y|24m+_wide"]

# Position-group axis (the third gate-bias axis added this round). The raw PFF
# positionGroupType field (off each event player row, 100% populated, agrees with
# Rosters) has 16 fine-grained values; this map collapses them into broad roles so
# the residual-after-distance bias is legible. The fine-grained value is ALSO
# reported per positionGroupType so nothing is hidden by the collapse.
POSITION_FIELD = "positionGroupType"          # per-player-row key (and in Rosters)
_POS_GROUP_MAP = {
    "GK": "GK",
    "RCB": "CB", "LCB": "CB", "MCB": "CB",
    "RB": "FB", "LB": "FB", "RWB": "FB", "LWB": "FB",
    "DM": "DM",
    "CM": "CM", "RM": "CM", "LM": "CM", "AM": "CM",
    "RW": "W", "LW": "W",
    "CF": "CF",
}
# Distance cells reported per position (coarser than the 7 distance bins so the
# (position x distance) cross-tab stays small + the per-cell N stays rankable).
_POSDIST_BINS = [(0, 20), (20, 30), (30, 40), (40, float("inf"))]
_POSDIST_LABELS = ["0-20m", "20-30m", "30-40m", "40m+"]
# Minimum surviving-N (after the VISIBLE gate) below which a downstream leaderboard
# row should be dropped or flagged as too thin to rank. Documented, not enforced.
MIN_SURVIVING_N = 100


def position_group(player_snapshot):
    """Broad role for a player row's positionGroupType (None if absent/unknown)."""
    g = player_snapshot.get(POSITION_FIELD)
    return _POS_GROUP_MAP.get(g, g)


def _bin_index(value, bins):
    """Index of the half-open [lo,hi) bin containing value (last bin catches all)."""
    for i, (lo, hi) in enumerate(bins):
        if lo <= value < hi:
            return i
    return len(bins) - 1


def ball_xy(ev):
    """Resolve the ball (x,y) for an event, or None if unavailable.

    The ball entry is a list of position dicts; we take the first with both
    coordinates. ~5% of events carry no resolvable ball position (e.g. dead-ball
    / off-screen) and are skipped by distance-conditioned binning.
    """
    b = ev.get("ball")
    if isinstance(b, list):
        for e in b:
            if e.get("x") is not None and e.get("y") is not None:
                return e["x"], e["y"]
        return None
    if isinstance(b, dict) and b.get("x") is not None and b.get("y") is not None:
        return b["x"], b["y"]
    return None


# ---------------------------------------------------------------------------
# On-ball player identification.
# ---------------------------------------------------------------------------
# Possession-event actor fields, in priority order, as a fallback for the rare
# events where gameEvents.playerId is absent.
_ACTOR_FIELDS = [
    "passerPlayerId", "crosserPlayerId", "shooterPlayerId", "clearerPlayerId",
    "carrierPlayerId", "ballCarrierPlayerId", "dribblerPlayerId", "touchPlayerId",
    "rebounderPlayerId", "keeperPlayerId",
]


def on_ball_player_id(ev):
    """Return the on-ball player id for an event, or None if unresolvable."""
    ge = ev.get("gameEvents") or {}
    pid = ge.get("playerId")
    if pid:
        return pid
    pe = ev.get("possessionEvents") or {}
    if isinstance(pe, dict):
        for f in _ACTOR_FIELDS:
            if pe.get(f):
                return pe[f]
    return None


# ---------------------------------------------------------------------------
# Accumulator helpers.
# ---------------------------------------------------------------------------
def _frac_est(counter):
    """(estimated_fraction, total_rows) from a Counter over visibility values."""
    n = counter.get(VISIBLE_VALUE, 0) + counter.get(ESTIMATED_VALUE, 0)
    other = sum(v for k, v in counter.items()
                if k not in (VISIBLE_VALUE, ESTIMATED_VALUE))
    n_all = n + other
    if n_all == 0:
        return None, 0
    return counter.get(ESTIMATED_VALUE, 0) / n_all, n_all


def _block(counter):
    """Serialisable breakdown block for a visibility Counter."""
    est_frac, n = _frac_est(counter)
    return {
        "rows": n,
        "visible": counter.get(VISIBLE_VALUE, 0),
        "estimated": counter.get(ESTIMATED_VALUE, 0),
        "estimated_frac": round(est_frac, 4) if est_frac is not None else None,
        "visible_frac": round(1 - est_frac, 4) if est_frac is not None else None,
    }


def _binned_rows(counters, labels, edges):
    """Serialise a list of visibility Counters (one per bin) into rows.

    Each row reports the bin label, its [lo,hi) edges, row count, ESTIMATED
    fraction, and the VISIBLE-KEEP RATE -- i.e. the fraction of rows in that bin
    a VISIBLE-only gate would retain (== visible_frac). For an off-ball
    population this is exactly how many runners survive the gate at that range.
    """
    rows = []
    for i, c in enumerate(counters):
        blk = _block(c)
        lo, hi = edges[i]
        rows.append({
            "bin": labels[i],
            "lo": lo,
            "hi": None if hi == float("inf") else hi,
            "rows": blk["rows"],
            "estimated_frac": blk["estimated_frac"],
            "visible_keep_rate": blk["visible_frac"],  # rows a VISIBLE gate retains
        })
    return rows


def _is_monotone_nondecreasing(rows, key="estimated_frac"):
    """True iff the per-bin metric is monotonically non-decreasing across bins.

    Skips bins with no data (None). Used to assert the headline gate-bias claim.
    """
    prev = None
    for r in rows:
        v = r.get(key)
        if v is None:
            continue
        if prev is not None and v < prev - 1e-9:
            return False
        prev = v
    return True


def _keep_block(counter):
    """{rows, surviving_visible_n, visible_keep_rate, estimated_frac} for a Counter.

    `surviving_visible_n` is the count a VISIBLE-only gate RETAINS (the rankable N).
    """
    est_frac, n = _frac_est(counter)
    vis = counter.get(VISIBLE_VALUE, 0)
    return {
        "rows": n,
        "surviving_visible_n": vis,
        "visible_keep_rate": round(vis / n, 4) if n else None,
        "estimated_frac": round(est_frac, 4) if est_frac is not None else None,
    }


def _quantile(sorted_vals, p):
    """Nearest-rank quantile of a pre-sorted list (returns None if empty)."""
    if not sorted_vals:
        return None
    i = int(round(p * (len(sorted_vals) - 1)))
    return sorted_vals[i]


def main():
    files = sorted(glob.glob(os.path.join(EVENT_DIR, "*.json")))
    if not files:
        raise SystemExit("No event files found under %s" % EVENT_DIR)

    # Global accumulators (visibility Counters).
    overall = collections.Counter()
    onball = collections.Counter()
    offball = collections.Counter()
    attacking = collections.Counter()   # in-possession side, EXCLUDING the on-ball row
    defending = collections.Counter()   # opponent side
    attacking_incl_onball = collections.Counter()  # in-possession side incl. on-ball
    confidence_overall = collections.Counter()
    ball_overall = collections.Counter()

    # Confidence x visibility cross-tab (to document the relationship & the 64% anchor).
    conf_by_vis = collections.defaultdict(collections.Counter)

    # --- Conditional missingness (the gate-bias structure) ---
    # ESTIMATED fraction binned by distance-from-ball and by |y|. We track three
    # populations: ALL player rows, ATTACKING off-ball rows (the exact rows a
    # Space leaderboard ranks), and DEFENDING rows.
    dist_all = [collections.Counter() for _ in _DIST_BINS]
    dist_att_offball = [collections.Counter() for _ in _DIST_BINS]
    dist_def = [collections.Counter() for _ in _DIST_BINS]
    absy_all = [collections.Counter() for _ in _ABSY_BINS]
    absy_att_offball = [collections.Counter() for _ in _ABSY_BINS]
    # rows skipped from distance binning because the event had no ball xy
    dist_skipped_no_ball = collections.Counter()  # by population

    # --- Position-group axis (this round's fix for the two blocking objections) ---
    # All keyed on the ATTACKING OFF-BALL population (the exact rows a Space
    # leaderboard ranks). visibility Counter per fine positionGroupType, per broad
    # group, per (group x coarse-distance) cell, and per individual player.
    pos_fine = collections.defaultdict(collections.Counter)   # positionGroupType -> Counter
    pos_group = collections.defaultdict(collections.Counter)  # broad group -> Counter
    posdist = collections.defaultdict(collections.Counter)    # (group, distbin) -> Counter
    per_player = collections.defaultdict(collections.Counter)  # playerId -> Counter
    per_player_meta = {}  # playerId -> {"pos_fine": .., "pos_group": ..} (last seen)

    per_match = {}             # match_id -> dict of blocks
    n_events_total = 0
    n_events_with_onball = 0
    n_events_no_onball = 0
    n_events_no_ball_xy = 0

    for fpath in files:
        match_id = os.path.splitext(os.path.basename(fpath))[0]

        # Metadata for team names (optional context; not load-bearing for the gate).
        home_nm = away_nm = None
        meta_path = os.path.join(META_DIR, match_id + ".json")
        if os.path.exists(meta_path):
            try:
                meta = json.load(open(meta_path))[0]
                home_nm = meta.get("homeTeam", {}).get("name")
                away_nm = meta.get("awayTeam", {}).get("name")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass

        data = json.load(open(fpath))

        m_overall = collections.Counter()
        m_onball = collections.Counter()
        m_offball = collections.Counter()
        m_attacking = collections.Counter()
        m_defending = collections.Counter()

        for ev in data:
            n_events_total += 1
            home_players = ev.get("homePlayers") or []
            away_players = ev.get("awayPlayers") or []

            obid = on_ball_player_id(ev)
            # Which side is in possession (attacking)?
            hids = {p.get("playerId") for p in home_players}
            aids = {p.get("playerId") for p in away_players}
            attack_side = None
            if obid is not None:
                if obid in hids:
                    attack_side = "home"
                elif obid in aids:
                    attack_side = "away"
            if obid is not None and attack_side is not None:
                n_events_with_onball += 1
            else:
                n_events_no_onball += 1

            bxy = ball_xy(ev)
            if bxy is None:
                n_events_no_ball_xy += 1

            for side_name, players in (("home", home_players), ("away", away_players)):
                for p in players:
                    v = p.get(VISIBILITY_FIELD)
                    overall[v] += 1
                    m_overall[v] += 1
                    confidence_overall[p.get(CONFIDENCE_FIELD)] += 1
                    conf_by_vis[v][p.get(CONFIDENCE_FIELD)] += 1

                    is_on = (obid is not None and p.get("playerId") == obid)
                    if is_on:
                        onball[v] += 1
                        m_onball[v] += 1
                    else:
                        offball[v] += 1
                        m_offball[v] += 1

                    # attack/defend split only when possession side is resolved
                    is_att_offball = False
                    is_defending = False
                    if attack_side is not None:
                        if side_name == attack_side:
                            attacking_incl_onball[v] += 1
                            if not is_on:
                                attacking[v] += 1
                                m_attacking[v] += 1
                                is_att_offball = True
                        else:
                            defending[v] += 1
                            m_defending[v] += 1
                            is_defending = True

                    # --- conditional-missingness binning ---
                    px, py = p.get("x"), p.get("y")
                    # |y| (central vs wide) does not need the ball position
                    if py is not None:
                        yi = _bin_index(abs(py), _ABSY_BINS)
                        absy_all[yi][v] += 1
                        if is_att_offball:
                            absy_att_offball[yi][v] += 1
                    # distance-from-ball needs both the player and ball position
                    has_d = bxy is not None and px is not None and py is not None
                    if has_d:
                        d = math.hypot(px - bxy[0], py - bxy[1])
                        di = _bin_index(d, _DIST_BINS)
                        dist_all[di][v] += 1
                        if is_att_offball:
                            dist_att_offball[di][v] += 1
                        if is_defending:
                            dist_def[di][v] += 1
                    else:
                        dist_skipped_no_ball["all"] += 1
                        if is_att_offball:
                            dist_skipped_no_ball["attacking_off_ball"] += 1
                        if is_defending:
                            dist_skipped_no_ball["defending"] += 1

                    # --- position-group axis (attacking off-ball only) ---
                    # These answer "are the leaders just the most on-camera
                    # players?" and "does distance-stratification remove the bias?".
                    # All marginals (pos_fine / pos_group / per_player) DO NOT need
                    # the ball xy; only the (position x distance) cells do.
                    if is_att_offball:
                        pid = p.get("playerId")
                        pf = p.get(POSITION_FIELD)
                        pg = _POS_GROUP_MAP.get(pf, pf)
                        pos_fine[pf][v] += 1
                        pos_group[pg][v] += 1
                        per_player[pid][v] += 1
                        per_player_meta[pid] = {"position_group_type": pf,
                                                "position_group": pg}
                        if has_d:
                            pdi = _bin_index(d, _POSDIST_BINS)
                            posdist[(pg, pdi)][v] += 1

            # ball visibility (context only)
            ball = ev.get("ball")
            if isinstance(ball, list):
                for b in ball:
                    ball_overall[b.get(VISIBILITY_FIELD)] += 1
            elif isinstance(ball, dict):
                ball_overall[ball.get(VISIBILITY_FIELD)] += 1

        per_match[match_id] = {
            "home_team": home_nm,
            "away_team": away_nm,
            "events": len(data),
            "overall": _block(m_overall),
            "on_ball": _block(m_onball),
            "off_ball": _block(m_offball),
            "attacking_off_ball": _block(m_attacking),
            "defending": _block(m_defending),
        }

    # Rank matches by overall ESTIMATED fraction.
    match_rank = sorted(
        per_match.items(),
        key=lambda kv: -(kv[1]["overall"]["estimated_frac"] or 0),
    )
    worst_matches = [
        {"match_id": mid, "estimated_frac": d["overall"]["estimated_frac"],
         "rows": d["overall"]["rows"]}
        for mid, d in match_rank[:8]
    ]
    best_matches = [
        {"match_id": mid, "estimated_frac": d["overall"]["estimated_frac"],
         "rows": d["overall"]["rows"]}
        for mid, d in match_rank[-8:]
    ]

    # confidence x visibility cross-tab serialisation
    cross = {}
    for vis_val, conf_counter in conf_by_vis.items():
        cross[str(vis_val)] = dict(conf_counter)

    # --- conditional-missingness (gate-bias) serialisation ---
    dist_all_rows = _binned_rows(dist_all, _DIST_LABELS, _DIST_BINS)
    dist_att_rows = _binned_rows(dist_att_offball, _DIST_LABELS, _DIST_BINS)
    dist_def_rows = _binned_rows(dist_def, _DIST_LABELS, _DIST_BINS)
    absy_all_rows = _binned_rows(absy_all, _ABSY_LABELS, _ABSY_BINS)
    absy_att_rows = _binned_rows(absy_att_offball, _ABSY_LABELS, _ABSY_BINS)

    # --- POSITION-GROUP axis (this round's fix) -------------------------------
    # (1) per fine positionGroupType keep-rate (attacking off-ball)
    pos_fine_rows = sorted(
        ({"position_group_type": k, **_keep_block(c)} for k, c in pos_fine.items()),
        key=lambda r: -r["rows"],
    )
    # (2) per broad group keep-rate (attacking off-ball)
    pos_group_rows = sorted(
        ({"position_group": k, **_keep_block(c)} for k, c in pos_group.items()),
        key=lambda r: -r["rows"],
    )
    # (3) (position x distance) cells -- shows the RESIDUAL position bias AFTER
    # distance-conditioning. Within a fixed distance band, keep-rate still spreads
    # widely across positions => distance-stratification alone does NOT de-bias.
    posdist_rows = []
    for pg in sorted({k for (k, _) in posdist.keys()}):
        cells = []
        for di, lab in enumerate(_POSDIST_LABELS):
            lo, hi = _POSDIST_BINS[di]
            blk = _keep_block(posdist.get((pg, di), collections.Counter()))
            cells.append({"dist_bin": lab, "lo": lo,
                          "hi": None if hi == float("inf") else hi, **blk})
        pos_group_rows_for_pg = next((r for r in pos_group_rows
                                      if r["position_group"] == pg), None)
        posdist_rows.append({
            "position_group": pg,
            "overall_visible_keep_rate": (pos_group_rows_for_pg["visible_keep_rate"]
                                          if pos_group_rows_for_pg else None),
            "cells_by_distance": cells,
        })
    # Within-distance-bin position spread: for each distance band, range of
    # keep-rate across position GROUPS. A large spread per band == residual
    # (orthogonal-to-distance) position bias that distance-stratification can't fix.
    within_dist_position_spread = []
    for di, lab in enumerate(_POSDIST_LABELS):
        per_pos = []
        for pg in sorted({k for (k, _) in posdist.keys()}):
            blk = _keep_block(posdist.get((pg, di), collections.Counter()))
            if blk["visible_keep_rate"] is not None and blk["rows"] >= 200:
                per_pos.append((pg, blk["visible_keep_rate"], blk["rows"]))
        if per_pos:
            kr = [x[1] for x in per_pos]
            hi_pg = max(per_pos, key=lambda x: x[1])
            lo_pg = min(per_pos, key=lambda x: x[1])
            within_dist_position_spread.append({
                "dist_bin": lab,
                "n_position_groups": len(per_pos),
                "keep_rate_min": round(min(kr), 4),
                "keep_rate_max": round(max(kr), 4),
                "keep_rate_range": round(max(kr) - min(kr), 4),
                "highest_keep_group": {"position_group": hi_pg[0],
                                       "visible_keep_rate": round(hi_pg[1], 4),
                                       "rows": hi_pg[2]},
                "lowest_keep_group": {"position_group": lo_pg[0],
                                      "visible_keep_rate": round(lo_pg[1], 4),
                                      "rows": lo_pg[2]},
            })
    distance_stratification_residual_bias = any(
        r["keep_rate_range"] >= 0.15 for r in within_dist_position_spread)

    # (4) per-PLAYER table (attacking off-ball). Answers "are the leaders just the
    # most on-camera players?" directly and gives a downstream leaderboard the
    # surviving-N + keep-rate to drop/flag thin or low-keep players.
    per_player_rows = []
    for pid, c in per_player.items():
        blk = _keep_block(c)
        meta = per_player_meta.get(pid, {})
        per_player_rows.append({
            "player_id": pid,
            "position_group_type": meta.get("position_group_type"),
            "position_group": meta.get("position_group"),
            **blk,
        })
    per_player_rows.sort(key=lambda r: -r["rows"])
    # Cross-player dispersion among players with enough RAW exposure to be rankable.
    ranked = [r for r in per_player_rows
              if r["rows"] >= 200 and r["visible_keep_rate"] is not None]
    keep_vals = sorted(r["visible_keep_rate"] for r in ranked)
    per_player_dispersion = {
        "min_rows_for_inclusion": 200,
        "n_players": len(ranked),
        "visible_keep_rate_min": _quantile(keep_vals, 0.0),
        "visible_keep_rate_p10": _quantile(keep_vals, 0.10),
        "visible_keep_rate_median": _quantile(keep_vals, 0.50),
        "visible_keep_rate_p90": _quantile(keep_vals, 0.90),
        "visible_keep_rate_max": _quantile(keep_vals, 1.0),
        "visible_keep_rate_pstdev": (round(statistics.pstdev(keep_vals), 4)
                                     if len(keep_vals) > 1 else None),
    }
    # How many would survive the surviving-N floor a leaderboard should apply.
    below_floor = [r for r in per_player_rows
                   if r["surviving_visible_n"] < MIN_SURVIVING_N]
    n_players_total = len(per_player_rows)
    # Lowest / highest keep among high-RAW-exposure players (>=2000 rows) -- these
    # are the players the gate hits hardest at equal raw exposure.
    high_exposure = [r for r in per_player_rows if r["rows"] >= 2000
                     and r["visible_keep_rate"] is not None]
    lowest_keep_high_exposure = sorted(
        high_exposure, key=lambda r: r["visible_keep_rate"])[:10]
    highest_keep_high_exposure = sorted(
        high_exposure, key=lambda r: -r["visible_keep_rate"])[:10]

    # Headline gate-bias facts for the attacking-off-ball population.
    att_total = sum(r["rows"] for r in dist_att_rows)
    att_kept = sum(round(r["visible_keep_rate"] * r["rows"])
                   for r in dist_att_rows if r["visible_keep_rate"] is not None)
    att_overall_keep = (att_kept / att_total) if att_total else None
    near_keep = next((r["visible_keep_rate"] for r in dist_att_rows
                      if r["bin"] == "0-10m"), None)
    far_keep = next((r["visible_keep_rate"] for r in dist_att_rows
                     if r["bin"] == "60m+"), None)
    near_est = next((r["estimated_frac"] for r in dist_att_rows
                     if r["bin"] == "0-10m"), None)
    far_est = next((r["estimated_frac"] for r in dist_att_rows
                    if r["bin"] == "60m+"), None)
    _near_keep_pct = ("%.0f" % (100 * near_keep)) if near_keep is not None else "na"
    _far_keep_pct = ("%.0f" % (100 * far_keep)) if far_keep is not None else "na"
    _near_est_pct = ("%.0f" % (100 * near_est)) if near_est is not None else "na"
    _far_est_pct = ("%.0f" % (100 * far_est)) if far_est is not None else "na"
    _discard_pct = (("%.0f" % (100 * (1 - att_overall_keep)))
                    if att_overall_keep is not None else "na")

    # Pull the 30-40m (position x distance) keep-rates for the corrected note that
    # shows the residual position bias surviving distance-conditioning.
    def _posdist_keep(pg, lab):
        di = _POSDIST_LABELS.index(lab)
        blk = _keep_block(posdist.get((pg, di), collections.Counter()))
        return blk["visible_keep_rate"]
    _cm_3040 = _posdist_keep("CM", "30-40m")
    _cf_3040 = _posdist_keep("CF", "30-40m")
    _gk_3040 = _posdist_keep("GK", "30-40m")
    def _pct(x):
        return ("%.0f" % (100 * x)) if x is not None else "na"
    gk_keep = next((r["visible_keep_rate"] for r in pos_group_rows
                    if r["position_group"] == "GK"), None)
    cf_keep = next((r["visible_keep_rate"] for r in pos_group_rows
                    if r["position_group"] == "CF"), None)
    cm_keep = next((r["visible_keep_rate"] for r in pos_group_rows
                    if r["position_group"] == "CM"), None)
    p10_keep = per_player_dispersion["visible_keep_rate_p10"]
    p90_keep = per_player_dispersion["visible_keep_rate_p90"]

    gate_bias_honesty_note = (
        "VISIBILITY IS NOT MISSING-AT-RANDOM along THREE compounding axes. "
        "(1) DISTANCE: the attacking off-ball ESTIMATED fraction rises "
        "monotonically from ~" + _near_est_pct + " percent within 10 m of the ball "
        "to ~" + _far_est_pct + " percent beyond 60 m. (2) LATERAL |y|: central play "
        "(|y|<8 m) is more occluded than wide play. (3) POSITION: at the SAME "
        "distance-from-ball, forwards and goalkeepers are far less visible than "
        "midfielders -- in the 30-40 m band the VISIBLE-keep rate is ~" + _pct(_cm_3040)
        + " percent for CM vs ~" + _pct(_cf_3040) + " percent for CF vs ~"
        + _pct(_gk_3040) + " percent for GK. Overall keep-rate by role is GK ~"
        + _pct(gk_keep) + " percent vs CF ~" + _pct(cf_keep) + " percent vs CM ~"
        + _pct(cm_keep) + " percent. "
        "CRITICAL CORRECTION TO PRIOR GUIDANCE: because the position bias is PARTLY "
        "ORTHOGONAL to distance (it persists within every distance bin), "
        "distance-stratification ALONE does NOT neutralize the gate bias -- a "
        "distance-stratified VISIBLE-only leaderboard still over-samples deep "
        "central midfielders and under-samples the forwards / wide runners / keepers "
        "a Space metric most wants to find. The bias is ALSO per-player: across the "
        + str(per_player_dispersion["n_players"]) + " players with >=200 attacking "
        "off-ball rows, the VISIBLE-keep rate spans " + _pct(p10_keep) + "-"
        + _pct(p90_keep) + " percent (p10-p90), so at equal raw exposure some "
        "players keep many times the surviving sample of others. The ONLY safe "
        "downstream guidance is therefore remedy (b): report the per-player / "
        "per-position gate keep-rate ACTUALLY achieved per leaderboard row, drop or "
        "flag players whose post-gate surviving_visible_n is below ~"
        + str(MIN_SURVIVING_N) + " or whose keep-rate is low (under-sampled), and "
        "treat far-from-ball / low-keep ranks as unreliable. Reporting per "
        "distance-from-ball stratum alone (the old remedy 'a') is NECESSARY context "
        "but is NOT sufficient on its own -- see gate_bias.by_position_group, "
        "by_position_x_distance, within_distance_position_spread and per_player."
    )

    out = {
        "field": {
            "name": VISIBILITY_FIELD,
            "location": (
                "per player row inside each event's homePlayers / awayPlayers list "
                "(and inside the ball entries)"
            ),
            "values": [VISIBLE_VALUE, ESTIMATED_VALUE],
            "meaning": {
                VISIBLE_VALUE: "position (x,y) directly tracked from broadcast video",
                ESTIMATED_VALUE: "position imputed/inferred by PFF (off-camera / occluded)",
            },
            "how_to_read": (
                "A player row is OCCLUDED/IMPUTED iff row['%s'] == '%s'; directly "
                "tracked iff == '%s'. Present on 100%% of player rows across all "
                "64 WC22 event files. Use the importable helpers is_estimated() / "
                "is_visible() from this module to gate events."
            ) % (VISIBILITY_FIELD, ESTIMATED_VALUE, VISIBLE_VALUE),
            "secondary_field": {
                "name": CONFIDENCE_FIELD,
                "values": ["HIGH", "MEDIUM", "LOW"],
                "note": (
                    "A separate per-row quality flag; NOT the same as visibility. "
                    "'not-HIGH' (LOW or MEDIUM) is much more common than ESTIMATED. "
                    "The visibility field is the correct VISIBLE/ESTIMATED gate."
                ),
            },
            "gate_helpers": {
                "module": "research/scripts/occlusion_audit.py",
                "import": "from occlusion_audit import is_estimated, is_visible, VISIBILITY_FIELD, ESTIMATED_VALUE",
                "functions": ["is_estimated(player_snapshot)", "is_visible(player_snapshot)",
                              "has_visibility_field(player_snapshot)", "on_ball_player_id(event)"],
            },
        },
        "breakdowns": {
            "overall_player_rows": _block(overall),
            "on_ball": _block(onball),
            "off_ball": _block(offball),
            "attacking_off_ball": _block(attacking),
            "attacking_incl_on_ball": _block(attacking_incl_onball),
            "defending": _block(defending),
            "ball_rows": _block(ball_overall),
        },
        "confidence_field_context": {
            "overall_distribution": dict(confidence_overall),
            "not_high_frac_overall": (
                round(
                    (sum(confidence_overall.values()) - confidence_overall.get("HIGH", 0))
                    / sum(confidence_overall.values()), 4)
                if sum(confidence_overall.values()) else None
            ),
            "confidence_by_visibility": cross,
            "note": (
                "Provided to explain anchor divergence. The visibility ESTIMATED "
                "fraction is LOWER than the confidence not-HIGH fraction; a prior "
                "'~64%% for match 10502' claim matches neither this match's "
                "visibility-ESTIMATED nor its not-HIGH exactly (see anchor notes)."
            ),
        },
        "gate_bias": {
            "what_this_is": (
                "CONDITIONAL missingness of the visibility gate along THREE axes. "
                "Marginal occlusion rates (overall / on-vs-off-ball / per-match) do "
                "NOT tell you whether the gate is biased; these breakdowns do. The "
                "ESTIMATED fraction is conditioned on (1) distance-from-ball (10 m "
                "bins), (2) |y| (central vs wide), and (3) positionGroupType, plus a "
                "(position x distance) cross-tab and a PER-PLAYER table. Computed over "
                "ALL 64 matches. visible_keep_rate is the fraction of rows a "
                "VISIBLE-only gate RETAINS (== 1 - estimated_frac); surviving_visible_n "
                "is the rankable post-gate sample. The position and per-player blocks "
                "exist to show that distance-stratification alone does NOT de-bias the "
                "gate and to give a downstream leaderboard the actual per-row keep-rate "
                "(remedy 'b')."
            ),
            "honesty_note": gate_bias_honesty_note,
            "by_distance_from_ball": {
                "bin_edges_m": [[lo, (None if hi == float("inf") else hi)]
                                for lo, hi in _DIST_BINS],
                "all_player_rows": dist_all_rows,
                "attacking_off_ball": dist_att_rows,
                "defending": dist_def_rows,
                "monotone_nondecreasing_estimated_frac": {
                    "all_player_rows": _is_monotone_nondecreasing(dist_all_rows),
                    "attacking_off_ball": _is_monotone_nondecreasing(dist_att_rows),
                    "defending": _is_monotone_nondecreasing(dist_def_rows),
                },
            },
            "by_lateral_abs_y": {
                "bin_edges_m": [[lo, (None if hi == float("inf") else hi)]
                                for lo, hi in _ABSY_BINS],
                "note": (
                    "Central (|y|<8 m) is MORE occluded than wide. Independent of the "
                    "distance-from-ball axis; both biases compound."
                ),
                "all_player_rows": absy_all_rows,
                "attacking_off_ball": absy_att_rows,
            },
            "by_position_group": {
                "population": "attacking_off_ball",
                "note": (
                    "VISIBLE-keep rate per role for the exact rows a Space leaderboard "
                    "ranks. GKs (~11%) and forwards/wingers (~54-58%) are kept far less "
                    "than central midfielders (~74%). 'position_group' is the broad "
                    "collapse of positionGroupType (CB/FB/DM/CM/W/CF/GK); fine values "
                    "are in by_position_group_type. Sorted by raw rows desc."
                ),
                "by_position_group": pos_group_rows,
                "by_position_group_type": pos_fine_rows,
            },
            "by_position_x_distance": {
                "population": "attacking_off_ball",
                "note": (
                    "The KEY block proving distance-stratification is NOT a sufficient "
                    "cure: within each coarse distance band, the VISIBLE-keep rate still "
                    "spreads widely across position groups (e.g. CM vs CF vs GK in the "
                    "30-40 m band), so the position bias is partly orthogonal to the "
                    "distance axis. dist_bins_m="
                    + str([[lo, (None if hi == float("inf") else hi)]
                           for lo, hi in _POSDIST_BINS])
                ),
                "cells": posdist_rows,
                "within_distance_position_spread": within_dist_position_spread,
                "distance_stratification_residual_position_bias": (
                    distance_stratification_residual_bias),
                "distance_stratification_residual_bias_meaning": (
                    "True iff some distance band has a >=0.15 keep-rate range across "
                    "position groups (with >=200 rows each), i.e. distance "
                    "stratification leaves a material position bias unaddressed."
                ),
            },
            "per_player": {
                "population": "attacking_off_ball",
                "note": (
                    "Answers 'are the leaders just the most on-camera players?'. For "
                    "EACH player: raw attacking-off-ball rows, surviving_visible_n after "
                    "the VISIBLE gate, visible_keep_rate, and estimated_frac. A "
                    "downstream leaderboard MUST report surviving_visible_n + "
                    "visible_keep_rate per ranked player and drop/flag those below "
                    "min_surviving_n_guidance or with low keep-rate as under-sampled. "
                    "Full table sorted by raw rows desc."
                ),
                "min_surviving_n_guidance": MIN_SURVIVING_N,
                "n_players_total": n_players_total,
                "n_players_below_surviving_n_floor": len(below_floor),
                "cross_player_keep_rate_dispersion": per_player_dispersion,
                "lowest_keep_rate_high_exposure": lowest_keep_high_exposure,
                "highest_keep_rate_high_exposure": highest_keep_high_exposure,
                "table": per_player_rows,
            },
            "attacking_off_ball_summary": {
                "total_rows": att_total,
                "overall_visible_keep_rate": (round(att_overall_keep, 4)
                                              if att_overall_keep is not None else None),
                "overall_discard_rate": (round(1 - att_overall_keep, 4)
                                         if att_overall_keep is not None else None),
                "keep_rate_0_10m": near_keep,
                "keep_rate_60m_plus": far_keep,
            },
            "events_without_resolvable_ball_xy": n_events_no_ball_xy,
            "rows_skipped_from_distance_bins_no_ball_xy": dict(dist_skipped_no_ball),
        },
        "per_match": per_match,
        "worst_8_matches_by_estimated_frac": worst_matches,
        "best_8_matches_by_estimated_frac": best_matches,
        "event_counts": {
            "matches": len(files),
            "total_events": n_events_total,
            "events_with_resolved_on_ball": n_events_with_onball,
            "events_without_resolved_on_ball": n_events_no_onball,
        },
        "meta": {
            "data_source": (
                "PFF FC FIFA Men's World Cup 2022 event snapshots (broadcast-tracking "
                "derived). Substrate = the 22 player (x,y) rows carried on EVERY event "
                "snapshot; covers ALL 64 matches (event data is complete for 64; the "
                "30Hz tracking frame cache only covers 44, but this audit does NOT use "
                "the cache -- it reads event snapshots directly)."
            ),
            "substrate": "event-snapshot player rows (all 64 matches)",
            "on_ball_definition": (
                "gameEvents.playerId, falling back to possession-event actor id "
                "(passer/crosser/shooter/clearer/carrier/ballCarrier/dribbler/touch/"
                "rebounder/keeper). The single on-ball player per event; everyone else "
                "off-ball."
            ),
            "attacking_vs_defending": (
                "Attacking = the home/away side the on-ball player belongs to (team in "
                "possession); defending = the opponent. 'attacking_off_ball' EXCLUDES "
                "the on-ball row; 'attacking_incl_on_ball' includes it. Only events with "
                "a resolved on-ball player contribute to this split."
            ),
            "honesty_notes": [
                "These are VISIBLE/ESTIMATED occlusion fractions, NOT positional error "
                "magnitudes. ESTIMATED rows are PFF-imputed; prior work cites ~7m typical "
                "error on imputed off-ball positions, but this script does not measure "
                "error -- only the imputed FRACTION.",
                "The visibility field is the authoritative gate. The confidence field is "
                "a different (coarser) quality signal and is reported only for context / "
                "anchor reconciliation.",
                "Any downstream off-ball metric should apply a per-event visibility gate "
                "(e.g. require the receiver and/or all relevant off-ball rows to be "
                "VISIBLE) and report results visibility-conditioned.",
                "THE GATE IS INFORMATIVELY MISSING (NOT MAR) along THREE compounding "
                "axes -- distance-from-ball (~11% ESTIMATED near-ball to ~99% beyond "
                "60 m), lateral |y| (central more occluded than wide), AND position "
                "group (GK ~11% kept, forwards/wingers ~54-58%, central midfielders "
                "~74%). See the 'gate_bias' block. A VISIBLE-only gate therefore biases "
                "any off-ball/Space leaderboard toward near-ball central midfielders "
                "and against far-from-ball forwards / wide runners / keepers.",
                "DISTANCE-STRATIFICATION ALONE DOES NOT DE-BIAS THE GATE (correction to "
                "prior guidance): the position bias is partly orthogonal to distance "
                "and survives within every distance bin (e.g. 30-40 m keep-rate ~55% "
                "CM vs ~37% CF vs ~7% GK). The earlier note said reporting per "
                "distance-from-ball stratum was a sufficient cure; it is NOT. See "
                "gate_bias.by_position_x_distance.within_distance_position_spread and "
                "distance_stratification_residual_position_bias.",
                "THE ONLY SAFE DOWNSTREAM GUIDANCE IS REMEDY (b): report the per-player "
                "/ per-position gate keep-rate ACTUALLY achieved per leaderboard row "
                "(gate_bias.per_player.table and gate_bias.by_position_group), drop or "
                "flag players whose surviving_visible_n is below the min-surviving-N "
                "guidance or whose keep-rate is low (under-sampled). Per-player "
                "keep-rate spans 0.0-0.93 (p10-p90 ~0.39-0.76) across the 632 players "
                "with >=200 attacking off-ball rows, so 'are the leaders just the most "
                "on-camera players?' is a real risk this table lets a build detect.",
            ],
        },
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # Console summary
    # -----------------------------------------------------------------------
    b = out["breakdowns"]
    print("=== OCCLUSION / VISIBILITY AUDIT (PFF WC22 event snapshots) ===")
    print("field:", VISIBILITY_FIELD, "values:", [VISIBLE_VALUE, ESTIMATED_VALUE])
    print("matches:", len(files), "| total events:", n_events_total,
          "| events w/ on-ball:", n_events_with_onball)
    print()
    def line(label, blk):
        print("  %-26s rows=%-9d est=%6.2f%%  vis=%6.2f%%" % (
            label, blk["rows"], 100 * blk["estimated_frac"], 100 * blk["visible_frac"]))
    line("OVERALL player rows", b["overall_player_rows"])
    line("ON-BALL", b["on_ball"])
    line("OFF-BALL", b["off_ball"])
    line("ATTACKING (off-ball)", b["attacking_off_ball"])
    line("DEFENDING", b["defending"])
    line("BALL rows", b["ball_rows"])
    print()
    print("confidence not-HIGH frac overall:",
          out["confidence_field_context"]["not_high_frac_overall"])
    m10502 = per_match.get("10502")
    if m10502:
        print("match 10502 overall ESTIMATED frac (visibility):",
              m10502["overall"]["estimated_frac"],
              "| off-ball:", m10502["off_ball"]["estimated_frac"],
              "| on-ball VISIBLE frac:", m10502["on_ball"]["visible_frac"])
    print()
    print("worst 5 matches by ESTIMATED frac:")
    for r in worst_matches[:5]:
        print("  %s  est=%.3f  rows=%d" % (r["match_id"], r["estimated_frac"], r["rows"]))
    print()
    print("--- GATE BIAS: ESTIMATED frac by distance-from-ball (attacking off-ball) ---")
    for r in dist_att_rows:
        ef = r["estimated_frac"]
        kr = r["visible_keep_rate"]
        print("  %-7s  est=%s  visible_keep=%s  rows=%d" % (
            r["bin"],
            ("%.3f" % ef) if ef is not None else "   na",
            ("%.3f" % kr) if kr is not None else "   na",
            r["rows"]))
    print("  monotone non-decreasing (attacking off-ball):",
          out["gate_bias"]["by_distance_from_ball"]
             ["monotone_nondecreasing_estimated_frac"]["attacking_off_ball"])
    print("  attacking off-ball overall VISIBLE keep-rate:",
          out["gate_bias"]["attacking_off_ball_summary"]["overall_visible_keep_rate"],
          "| discard:",
          out["gate_bias"]["attacking_off_ball_summary"]["overall_discard_rate"])
    print()
    print("--- GATE BIAS: ESTIMATED frac by |y| (central vs wide, all rows) ---")
    for r in absy_all_rows:
        ef = r["estimated_frac"]
        print("  %-16s est=%s  rows=%d" % (
            r["bin"], ("%.3f" % ef) if ef is not None else "na", r["rows"]))
    print()
    print("--- GATE BIAS: VISIBLE-keep by position group (attacking off-ball) ---")
    for r in pos_group_rows:
        print("  %-4s keep=%.3f  surviving_n=%-7d rows=%d" % (
            r["position_group"], r["visible_keep_rate"],
            r["surviving_visible_n"], r["rows"]))
    print()
    print("--- GATE BIAS: residual position bias WITHIN distance bins ---")
    for r in within_dist_position_spread:
        print("  %-7s keep-range=%.2f  hi=%s(%.2f) lo=%s(%.2f)" % (
            r["dist_bin"], r["keep_rate_range"],
            r["highest_keep_group"]["position_group"],
            r["highest_keep_group"]["visible_keep_rate"],
            r["lowest_keep_group"]["position_group"],
            r["lowest_keep_group"]["visible_keep_rate"]))
    print("  distance-stratification leaves residual position bias:",
          distance_stratification_residual_bias)
    print()
    d_ = per_player_dispersion
    print("--- GATE BIAS: per-player VISIBLE-keep dispersion (>=200 rows) ---")
    print("  players=%d  min=%.3f p10=%.3f median=%.3f p90=%.3f max=%.3f pstdev=%.3f"
          % (d_["n_players"], d_["visible_keep_rate_min"], d_["visible_keep_rate_p10"],
             d_["visible_keep_rate_median"], d_["visible_keep_rate_p90"],
             d_["visible_keep_rate_max"], d_["visible_keep_rate_pstdev"]))
    print("  players total=%d  below surviving-N floor(%d)=%d" % (
        n_players_total, MIN_SURVIVING_N, len(below_floor)))
    print("  lowest-keep high-exposure players:")
    for r in lowest_keep_high_exposure[:4]:
        print("    pid=%s pos=%s keep=%.3f surviving_n=%d rows=%d" % (
            r["player_id"], r["position_group_type"], r["visible_keep_rate"],
            r["surviving_visible_n"], r["rows"]))
    print()
    print("WROTE:", OUT_PATH)


if __name__ == "__main__":
    main()
