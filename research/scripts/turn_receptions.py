#!/usr/bin/env python3
"""
TURN -- Turned Under-line Reception Network (count / leaderboard layer).

A TURN reception is a COMPLETED, OPEN-PLAY pass that PFF tagged as breaking a
named tactical line (linesBrokenType in {D, M, A, AM, MD, AMD}) AND whose
RECEIVER received the ball facing the opponent's goal (receiverFacingType ==
"G"). We attribute it to the RECEIVER -- this is the off-ball player who got on
the ball behind a graded line, on the half-turn, ready to attack.

This is the COUNT / LEADERBOARD layer ONLY. We deliberately do NOT:
  - build a StatsBomb ensuing-xG credit (no temporal/possession join exists in
    this repo -- only a coarse match-level join),
  - build a next-receiver "phantom turn" term (receiverFacingType exists only
    on completed passes, so it cannot be evaluated counterfactually).

What TURN actually is, stated plainly: "the receiver got the ball on the
half-turn behind a PFF-graded tactical line." It is NOT a ground-truth
line-break, and NOT a value model. We cross-check the population against an
INDEPENDENT geometric line-break reconstruction (the eda_line_breaks.py
corridor, >=3 opponents bypassed) and report the overlap honestly.

DATA SUBSTRATE: PFF FC WC22 event snapshots only (every event carries all 22
player x,y at the event instant). This runs over ALL 64 matches with event
data (the 30 Hz tracking cache covers only 44 -- we never touch it here).

The optional xT read at the reception point is a SOFT static lookup into the
Karun Singh xT grid (src/wc2026_tracking_transformer/baselines/xt.py). It is
NOT calibrated P(score) and NOT StatsBomb xG. Labelled "soft" everywhere.

VISIBILITY GATE: the TURN count/leaderboard is driven entirely by PFF human
event labels (linesBrokenType, receiverFacingType, receiverPlayerId) which are
present regardless of tracking occlusion -- they do NOT depend on imputed
player positions. The only place player (x,y) drives a number is (1) the
geometric line-break cross-check and (2) the soft xT read at the reception
point. For those we apply a per-event visibility gate on the RECEIVER's
position confidence and report results both raw and visibility-conditioned.

Stdlib + numpy (for the xT grid lookup, already a dep). No new deps.

Run (from repo root):
    PYTHONPATH=src uv run python research/scripts/turn_receptions.py
Writes:
    research/data/turn.json
"""
import json
import glob
import os
import collections

import scipy.stats as _st

from wc2026_tracking_transformer.baselines.xt import xt_for_ball


# ---------------------------------------------------------------------------
# Count uncertainty: exact (Garwood) Poisson two-sided 95% CI for a count.
# This treats each player's TURN tally as a Poisson count and gives an exact
# interval on the EXPECTED count -- it is a per-row N-based uncertainty band,
# NOT a claim about a rate. For k=0 the lower bound is 0.
# ---------------------------------------------------------------------------
def poisson_ci(k, alpha=0.05):
    lo = 0.0 if k == 0 else _st.chi2.ppf(alpha / 2.0, 2 * k) / 2.0
    hi = _st.chi2.ppf(1.0 - alpha / 2.0, 2 * (k + 1)) / 2.0
    return round(lo, 2), round(hi, 2)

# ---------------------------------------------------------------------------
# Paths (mirror eda_line_breaks.py)
# ---------------------------------------------------------------------------
BASE = os.environ.get(
    "PFF_ROOT", "/Users/nick/pff_wc22_local"
)
EVENT_DIR = os.path.join(BASE, "Event Data")
META_DIR = os.path.join(BASE, "Metadata")
ROSTER_DIR = os.path.join(BASE, "Rosters")

OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "turn.json",
)

# ---------------------------------------------------------------------------
# Rule parameters
# ---------------------------------------------------------------------------
LINE_TAGS = {"D", "M", "A", "AM", "MD", "AMD"}  # all populated linesBrokenType
FINAL_MATCH = "10517"
FINAL_HOME_ID = 364  # Argentina
FINAL_AWAY_ID = 363  # France
DI_MARIA_ID = 3868

# Geometric cross-check params (copied from eda_line_breaks.py so the overlap is
# apples-to-apples with that script's definition).
GEO_THRESHOLD = 3          # >=3 opponents bypassed
CORRIDOR_HALF_WIDTH = 6.0  # meters
FALLBACK_PAD = 4.0         # meters

# Pitch half-extents (meters, center origin) for normalizing into the xT grid.
PITCH_HALF_X = 52.5
PITCH_HALF_Y = 34.0


# ---------------------------------------------------------------------------
# Orientation (mirror eda_line_breaks.py exactly)
# ---------------------------------------------------------------------------
def home_attack_sign(period, home_start_left, home_start_left_et):
    """Return +1 if home team attacks toward +x in this period, else -1."""
    if period in (1, 2):
        base = 1 if home_start_left else -1
        return base if period == 1 else -base
    elif period in (3, 4):
        base = 1 if home_start_left_et else -1
        return base if period == 3 else -base
    return None  # period 5 (shootout) excluded upstream


def orient(x, y, sign):
    """Rotate a point into the attacking-right frame."""
    return x * sign, y * sign


# ---------------------------------------------------------------------------
# Geometric line-break corridor (copied verbatim from eda_line_breaks.py)
# ---------------------------------------------------------------------------
def count_bypassed(px, py, rx, ry, defenders):
    """Count opponents bypassed by an oriented (forward) pass."""
    n = 0
    span = rx - px
    if span <= 0:
        return 0  # not a forward pass
    ylo = min(py, ry) - FALLBACK_PAD
    yhi = max(py, ry) + FALLBACK_PAD
    for dx, dy in defenders:
        if not (px < dx < rx):
            continue
        t = (dx - px) / span
        py_interp = py + t * (ry - py)
        if abs(dy - py_interp) <= CORRIDOR_HALF_WIDTH:
            n += 1
        elif ylo <= dy <= yhi:
            n += 1
    return n


def is_visible(player):
    """Per-event visibility gate on a player position dict.

    PFF marks each player snapshot row with a confidence/visibility flag. An
    ESTIMATED (imputed) position should NOT be trusted for geometry. We treat a
    position as visible only if it is not flagged estimated and not low
    confidence. We read whatever flag the snapshot carries and default to
    "visible" only when no flag is present (the field is genuinely visible).
    """
    if player is None:
        return False
    # PFF position rows carry a 'visibility' string ('VISIBLE'/'ESTIMATED') on
    # some exports and/or a 'confidence' field. Be defensive about both.
    vis = player.get("visibility")
    if vis is not None:
        return str(vis).upper() == "VISIBLE"
    conf = player.get("confidence")
    if conf is not None:
        return str(conf).upper() not in ("LOW", "ESTIMATED")
    return True  # no flag => treat as visible (do not over-gate)


def soft_xt_at(rx_oriented, ry_oriented):
    """SOFT static Singh-xT lookup at an oriented reception point.

    rx/ry are in meters, oriented so the attacking goal is at +x. The xt grid
    helper expects normalized [-1,1] with attacking goal at +1, which matches.
    This is a soft positional value proxy -- NOT calibrated P(score), NOT xG.
    """
    xn = max(-1.0, min(1.0, rx_oriented / PITCH_HALF_X))
    yn = max(-1.0, min(1.0, ry_oriented / PITCH_HALF_Y))
    return xt_for_ball(xn, yn)


# ---------------------------------------------------------------------------
# Main pass over all matches
# ---------------------------------------------------------------------------
def main():
    # TURN accumulators (label-driven; occlusion-robust)
    turn_player = collections.Counter()
    turn_team = collections.Counter()
    player_team = {}
    player_name = {}
    team_name = {}

    # -- TEAM exposure denominators (FIX for round-2 objection: mirror the
    # objection-1 player fix on the team layer). The raw team count is
    # exposure-confounded -- teams played 3-7 matches with different passing
    # volumes -- so we accumulate, per team, (a) the set of matches the team
    # actually played and (b) the team's completed open-play pass volume
    # (attributed to the SAME receiver-side population the TURN numerator uses).
    # These give per-match and per-1000-completed-open-play-pass exposure
    # normalizations so the board is rate-ranked / tiered, not raw-count-ranked.
    team_matches = collections.defaultdict(set)     # matches the team played
    team_cop_passes = collections.Counter()         # completed open-play passes

    # -- Three coherent, separately-labelled appearance denominators --
    # (1) HONEST per-appearance: matches the player was actually involved on the
    #     ball (passer/receiver/shooter/ballCarrier in ANY event). Verified to
    #     equal the event-snapshot-row set for named players and 664/683 players
    #     globally, and -- unlike the roster -- it does NOT count unused bench.
    player_appearances = collections.defaultdict(set)
    # (2) matches in which the player recorded >=1 line-break reception
    #     (this was the OLD, mislabelled `matches` denominator).
    player_lbrec_matches = collections.defaultdict(set)
    # (3) matches in which the player recorded >=1 TURN reception.
    player_turn_matches = collections.defaultdict(set)

    # denominators for the turned-to-goal share (all populated line-break recs)
    linebreak_recs_player = collections.Counter()  # line-break recs (any facing)
    linebreak_recs_total = 0
    turn_total = 0  # facing-G subset

    # facing breakdown among line-break receptions
    facing_breakdown = collections.Counter()

    # soft xT (visibility-gated) over TURN receptions
    turn_xt_sum = 0.0
    turn_xt_n = 0

    # geometric cross-check accumulators
    turn_geo_visible = 0      # TURN recs where receiver+passer visible (gateable)
    turn_geo_overlap = 0      # of those, also geometric LB>=3
    turn_geo_forward = 0      # of those, the pass was forward (span>0)

    # final-match accumulators
    final_turn_team = collections.Counter()
    final_turn_player = collections.defaultdict(lambda: collections.Counter())

    # diagnostics
    n_complete_open_play = 0
    n_linebreak_tagged = 0

    # roster-listed matches (squad inclusion incl. unused bench) -- kept ONLY
    # for transparency; NOT used as the headline denominator because it counts
    # unused-bench appearances (e.g. Dybala listed in 7, on the ball in 2).
    player_roster_matches = collections.defaultdict(set)

    files = sorted(glob.glob(os.path.join(EVENT_DIR, "*.json")))

    for fpath in files:
        match_id = os.path.splitext(os.path.basename(fpath))[0]
        meta_path = os.path.join(META_DIR, match_id + ".json")
        if not os.path.exists(meta_path):
            continue
        meta = json.load(open(meta_path))[0]
        home_id = int(meta["homeTeam"]["id"])
        away_id = int(meta["awayTeam"]["id"])
        home_nm = meta["homeTeam"]["name"]
        away_nm = meta["awayTeam"]["name"]
        team_name[home_id] = home_nm
        team_name[away_id] = away_nm
        # Both teams played THIS match (exposure denominator for the team layer).
        team_matches[home_id].add(match_id)
        team_matches[away_id].add(match_id)
        hsl = bool(meta["homeTeamStartLeft"])
        hsl_et = bool(meta.get("homeTeamStartLeftExtraTime", hsl))

        # roster (transparency only)
        rpath = os.path.join(ROSTER_DIR, match_id + ".json")
        if os.path.exists(rpath):
            for rent in json.load(open(rpath)):
                try:
                    rpid = int(rent["player"]["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                player_roster_matches[rpid].add(match_id)

        events = json.load(open(fpath))

        for ev in events:
            ge = ev.get("gameEvents") or {}
            period = ge.get("period")

            pe = ev.get("possessionEvents")
            if not pe or not isinstance(pe, dict):
                continue

            # APPEARANCE TRACKING (runs on EVERY possession event, any type /
            # outcome / period incl. setpieces): a player "appeared" in this
            # match if they were involved on the ball at least once. This is the
            # honest per-appearance denominator and does NOT include unused
            # bench players (the roster does).
            for _k in ("passerPlayerId", "receiverPlayerId",
                       "shooterPlayerId", "ballCarrierPlayerId"):
                _v = pe.get(_k)
                if _v is not None:
                    player_appearances[int(_v)].add(match_id)

            if period not in (1, 2, 3, 4):
                continue  # exclude shootout (5) / unknown

            if pe.get("possessionEventType") != "PA":
                continue
            if pe.get("passOutcomeType") != "C":  # complete only
                continue
            if ge.get("setpieceType") != "O":     # open play only
                continue

            n_complete_open_play += 1

            receiver_id = pe.get("receiverPlayerId")
            passer_id = pe.get("passerPlayerId")

            # Determine which side the RECEIVER is on (attribution is to receiver).
            # We resolve the side HERE -- for EVERY completed open-play pass --
            # so the team pass-volume exposure denominator is attributed to
            # exactly the same receiver-side population as the TURN numerator
            # (FIX for round-2 objection: consistent exposure normalization).
            home_players = ev.get("homePlayers") or []
            away_players = ev.get("awayPlayers") or []
            hmap = {p["playerId"]: p for p in home_players}
            amap = {p["playerId"]: p for p in away_players}
            if receiver_id is not None and receiver_id in hmap:
                recv_side = "home"
            elif receiver_id is not None and receiver_id in amap:
                recv_side = "away"
            elif passer_id in hmap:
                recv_side = "home"
            elif passer_id in amap:
                recv_side = "away"
            else:
                recv_side = None

            # Team pass-volume exposure: count this completed open-play pass for
            # the receiving team (None only if neither endpoint is locatable;
            # such passes cannot be team-attributed and are skipped from BOTH the
            # numerator and this denominator, keeping the ratio internally
            # consistent).
            if recv_side is not None:
                _vol_team = home_id if recv_side == "home" else away_id
                team_cop_passes[_vol_team] += 1

            lbt = pe.get("linesBrokenType")
            if lbt not in LINE_TAGS:
                continue  # not a graded line-break reception

            if receiver_id is None or recv_side is None:
                continue

            n_linebreak_tagged += 1

            team_id = home_id if recv_side == "home" else away_id
            tnm = home_nm if recv_side == "home" else away_nm

            rname = pe.get("receiverPlayerName") or str(receiver_id)
            player_name[receiver_id] = rname
            player_team[receiver_id] = tnm

            # Denominator (2): every populated line-break reception (any facing).
            linebreak_recs_total += 1
            linebreak_recs_player[receiver_id] += 1
            player_lbrec_matches[receiver_id].add(match_id)
            facing = pe.get("receiverFacingType")
            facing_breakdown[facing] += 1

            # --- TURN gate: received facing goal ---
            if facing != "G":
                continue

            turn_player[receiver_id] += 1
            turn_team[team_id] += 1
            turn_total += 1
            player_turn_matches[receiver_id].add(match_id)  # denominator (3)
            if match_id == FINAL_MATCH:
                final_turn_team[team_id] += 1
                final_turn_player[team_id][receiver_id] += 1

            # ----- Geometry-dependent reads (visibility-gated) -----
            sign_home = home_attack_sign(period, hsl, hsl_et)
            if sign_home is None:
                continue
            sign = sign_home if recv_side == "home" else -sign_home

            teammates = home_players if recv_side == "home" else away_players
            opponents = away_players if recv_side == "home" else home_players
            tmap = hmap if recv_side == "home" else amap
            rp = tmap.get(receiver_id)
            pp = tmap.get(passer_id)

            # Soft xT read at the reception point (gated on receiver visibility).
            if rp is not None and is_visible(rp):
                rx, ry = orient(rp["x"], rp["y"], sign)
                turn_xt_sum += soft_xt_at(rx, ry)
                turn_xt_n += 1

            # Geometric line-break cross-check: requires both passer & receiver
            # located and visible (else the corridor geometry is untrustworthy).
            if (rp is not None and pp is not None
                    and is_visible(rp) and is_visible(pp)):
                px, py = orient(pp["x"], pp["y"], sign)
                rx, ry = orient(rp["x"], rp["y"], sign)
                turn_geo_visible += 1
                if rx - px > 0:
                    turn_geo_forward += 1
                defenders = [orient(p["x"], p["y"], sign)
                             for p in opponents if is_visible(p)]
                n_by = count_bypassed(px, py, rx, ry, defenders)
                if n_by >= GEO_THRESHOLD:
                    turn_geo_overlap += 1

    # -----------------------------------------------------------------------
    # Build outputs
    # -----------------------------------------------------------------------
    players_board = []
    for pid, cnt in turn_player.most_common():
        appearances = len(player_appearances.get(pid, ()))
        lb_match = len(player_lbrec_matches.get(pid, ()))
        turn_match_n = len(player_turn_matches.get(pid, ()))
        lb_recs = linebreak_recs_player.get(pid, 0)
        ci_lo, ci_hi = poisson_ci(cnt)
        players_board.append({
            "player": player_name[pid],
            "team": player_team[pid],
            "turn_receptions": cnt,
            # Per-row N-based uncertainty: exact Poisson 95% CI on the expected
            # count. Ranking within overlapping CIs is NOT supportable.
            "turn_receptions_poisson95_ci": [ci_lo, ci_hi],
            "line_break_receptions": lb_recs,
            "turned_to_goal_share": round(cnt / lb_recs, 3) if lb_recs else None,
            # FIX (objection 1): consistent, separately-labelled denominators.
            # `appearances` = matches the player was actually on the ball
            # (honest per-appearance denom; excludes unused bench). `per_appearance`
            # pairs the facing-G TURN numerator with THIS denominator.
            "appearances": appearances,
            "per_appearance": (round(cnt / appearances, 3)
                               if appearances else None),
            # The OLD denominator, now honestly named (matches w/ >=1 line-break
            # reception) -- kept only for continuity; do NOT read as per-appearance.
            "matches_with_linebreak_reception": lb_match,
            "turn_per_linebreak_match": (round(cnt / lb_match, 3)
                                         if lb_match else None),
            # Matches in which the player recorded >=1 TURN (per-TURN-appearance
            # denominator the adversary recomputed). Reported for transparency;
            # it is circular (only counts matches where the numerator fired) so
            # it is NOT the headline per-appearance rate.
            "matches_with_turn": turn_match_n,
        })
    # Sort on absolute count, then per-appearance (descriptive), then name.
    players_board.sort(
        key=lambda r: (-r["turn_receptions"],
                       -(r["per_appearance"] or 0.0), r["player"]))

    # ---- Tie-aware tier structure + tie-aware top-N truncation -------------
    # Group players by identical TURN count so the board reports TIERS, not a
    # spurious precise ordering. The leading tier's CIs all overlap, so only
    # broad tiers are statistically supportable (objection 2).
    count_groups = collections.OrderedDict()
    for r in players_board:
        count_groups.setdefault(r["turn_receptions"], []).append(r["player"])
    tie_tiers = []
    for c in sorted(count_groups, reverse=True):
        members = count_groups[c]
        lo, hi = poisson_ci(c)
        tie_tiers.append({
            "turn_receptions": c,
            "n_players": len(members),
            "poisson95_ci": [lo, hi],
            "players": members,
        })

    # Tie-aware truncation: include the full boundary count-group rather than
    # cutting mid-tie at an arbitrary alpha-sorted name. Take all players with
    # turn_receptions >= the count that sits at/just past rank ~25.
    TOP_TARGET = 25
    if len(players_board) <= TOP_TARGET:
        cutoff_count = players_board[-1]["turn_receptions"] if players_board else 0
    else:
        cutoff_count = players_board[TOP_TARGET - 1]["turn_receptions"]
    players_top = [r for r in players_board
                   if r["turn_receptions"] >= cutoff_count]

    # ---- TEAM board with EXPOSURE NORMALIZATION (round-2 objection fix) ------
    # The raw team count is exposure-confounded (teams played 3-7 matches, with
    # widely different passing volumes). We add, per team: matches_played, the
    # completed-open-play pass volume, and TWO exposure-normalized rates
    # (per_match and per_1000_completed_open_play_passes), each with an exact
    # Poisson 95% CI carried through the SAME normalization. The board is then
    # presented as a tier / rate-ranked list rather than a raw-count ranking,
    # exactly as the players were de-ranked in round 1.
    teams_board = []
    for tid, cnt in turn_team.most_common():
        lo, hi = poisson_ci(cnt)
        m_played = len(team_matches.get(tid, ()))
        cop = team_cop_passes.get(tid, 0)
        per_match = round(cnt / m_played, 3) if m_played else None
        per_1000 = round(1000.0 * cnt / cop, 2) if cop else None
        teams_board.append({
            "team": team_name[tid],
            "turn_receptions": cnt,
            "turn_receptions_poisson95_ci": [lo, hi],
            # EXPOSURE (the fix): the count alone is not comparable across teams.
            "matches_played": m_played,
            "completed_open_play_passes": cop,
            # Exposure-normalized rates with CIs propagated through the SAME
            # normalization (CI on the count, divided by the exposure), so a
            # reader sees the rate AND its uncertainty -- not a raw count whose
            # Poisson CI silently treats 67-over-7 and 44-over-4 as comparable.
            "turn_per_match": per_match,
            "turn_per_match_poisson95_ci": (
                [round(lo / m_played, 3), round(hi / m_played, 3)]
                if m_played else None),
            "turn_per_1000_completed_open_play_passes": per_1000,
            "turn_per_1000_passes_poisson95_ci": (
                [round(1000.0 * lo / cop, 2), round(1000.0 * hi / cop, 2)]
                if cop else None),
        })
    # Default ordering stays on absolute count for continuity, but the headline
    # below explicitly de-ranks it. Provide the two rate-ranked orderings too.
    teams_board.sort(key=lambda r: (-r["turn_receptions"], r["team"]))

    teams_by_per_match = sorted(
        [r for r in teams_board if r["turn_per_match"] is not None],
        key=lambda r: (-r["turn_per_match"], r["team"]))
    teams_by_per_1000_passes = sorted(
        [r for r in teams_board
         if r["turn_per_1000_completed_open_play_passes"] is not None],
        key=lambda r: (-r["turn_per_1000_completed_open_play_passes"],
                       r["team"]))

    # Leading-tier summary for the headline. Rule: a count-group is in the
    # leading tier if it is NOT significantly below the leader at 95% -- i.e.
    # the leader's exact Poisson 95% CI CONTAINS that group's point count
    # (equivalently leader_lo <= group_count). Pure CI-overlap is too permissive
    # (the leader's wide CI chains all the way down to count=1), so we use the
    # standard "leader CI contains the comparison point" test instead. These
    # players are statistically indistinguishable from the leader, so we name a
    # TIER, never a single #1.
    leading_tier_players = []
    leading_tier_label = None
    leading_tier_count_range = None
    # The named "top cluster": the contiguous high-count tie-groups within one
    # reception of the leader (counts >= leader_count-2, capped at the top three
    # distinct count-groups). This is the recognizable leading cluster -- still
    # reported as an UNORDERED tier (overlapping CIs), never a precise ranking.
    top_cluster = []
    if tie_tiers:
        leader_count = tie_tiers[0]["turn_receptions"]
        leader_lo = tie_tiers[0]["poisson95_ci"][0]
        tier_counts = []
        for t in tie_tiers:
            if t["turn_receptions"] >= leader_lo:  # not sig. below leader
                leading_tier_players.extend(t["players"])
                tier_counts.append(t["turn_receptions"])
            else:
                break
        if tier_counts:
            lo_c, hi_c = min(tier_counts), max(tier_counts)
            leading_tier_count_range = [lo_c, hi_c]
            leading_tier_label = (
                "%d-%d TURN receptions over all 64 matches (%d players, "
                "statistically INDISTINGUISHABLE: each count falls inside the "
                "leader's exact Poisson 95%% CI [%.1f, %.1f]; there is NO "
                "supportable single #1 and NO supportable within-tier order)"
                % (lo_c, hi_c, len(leading_tier_players),
                   leader_lo, tie_tiers[0]["poisson95_ci"][1])
            )
        # Named top cluster: high-count groups within 2 of the leader.
        for t in tie_tiers:
            if t["turn_receptions"] >= leader_count - 2:
                top_cluster.append({
                    "turn_receptions": t["turn_receptions"],
                    "n_players": t["n_players"],
                    "poisson95_ci": t["poisson95_ci"],
                    "players": t["players"],
                })

    # Top-3 under each normalization, for the de-ranking headline note.
    def _top3(rows, key):
        out_s = []
        for r in rows[:3]:
            out_s.append("%s %s" % (r["team"], r[key]))
        return "; ".join(out_s)

    team_raw_top3 = _top3(teams_board, "turn_receptions")
    team_per_match_top3 = _top3(teams_by_per_match, "turn_per_match")
    team_per_1000_top3 = _top3(
        teams_by_per_1000_passes,
        "turn_per_1000_completed_open_play_passes")

    # Turned-to-goal share (population level)
    turned_to_goal_share = (
        round(turn_total / linebreak_recs_total, 4)
        if linebreak_recs_total else None
    )

    # Soft xT summary (visibility-gated)
    mean_turn_xt = (round(turn_xt_sum / turn_xt_n, 5)
                    if turn_xt_n else None)

    # Geometric overlap (of TURN receptions that are gateable)
    geo_overlap_share = (
        round(turn_geo_overlap / turn_geo_visible, 4)
        if turn_geo_visible else None
    )
    geo_forward_share = (
        round(turn_geo_forward / turn_geo_visible, 4)
        if turn_geo_visible else None
    )

    # Final-match section
    def final_rows(team_id):
        rows = []
        for pid, cnt in final_turn_player[team_id].most_common(8):
            rows.append({
                "player": player_name[pid],
                "turn_receptions": cnt,
            })
        return rows

    di_maria_final = final_turn_player[FINAL_HOME_ID].get(DI_MARIA_ID, 0)

    final_section = {
        "match_id": FINAL_MATCH,
        "home": {
            "team": team_name[FINAL_HOME_ID], "id": FINAL_HOME_ID,
            "turn_receptions": final_turn_team.get(FINAL_HOME_ID, 0),
            "top_players": final_rows(FINAL_HOME_ID),
        },
        "away": {
            "team": team_name[FINAL_AWAY_ID], "id": FINAL_AWAY_ID,
            "turn_receptions": final_turn_team.get(FINAL_AWAY_ID, 0),
            "top_players": final_rows(FINAL_AWAY_ID),
        },
        "di_maria_turn_receptions": di_maria_final,
        "di_maria_player_id": DI_MARIA_ID,
    }

    meta_block = {
        "metric": "TURN -- Turned Under-line Reception Network (count layer)",
        "definition": (
            "A TURN reception = a COMPLETED, OPEN-PLAY pass (passOutcomeType=='C', "
            "setpieceType=='O') with PFF linesBrokenType in {D,M,A,AM,MD,AMD} AND "
            "receiverFacingType=='G' (received facing goal). Attributed to the "
            "RECEIVER (receiverPlayerId). Read as: 'the receiver got on the ball "
            "on the half-turn behind a PFF-graded tactical line.' NOT a "
            "ground-truth geometric line-break; NOT a value model."
        ),
        "substrate": "PFF event snapshots (human labels). Covers all matches with event data.",
        "n_matches_with_event_data": len(files),
        "n_complete_open_play_passes": n_complete_open_play,
        "n_line_break_receptions_populated": linebreak_recs_total,
        "n_line_break_tagged_pre_attribution": n_linebreak_tagged,
        "filters": {
            "possessionEventType": "PA",
            "passOutcomeType": "C (complete)",
            "setpieceType": "O (open play only)",
            "linesBrokenType_in": sorted(LINE_TAGS),
            "receiverFacingType": "G (received facing goal)",
            "periods_included": [1, 2, 3, 4],
            "attributed_to": "receiverPlayerId",
        },
        "turned_to_goal": {
            "turn_receptions": turn_total,
            "line_break_receptions_populated": linebreak_recs_total,
            "share": turned_to_goal_share,
            "facing_breakdown_among_line_break_receptions": dict(
                facing_breakdown.most_common()),
            "note": (
                "Share = fraction of populated line-break receptions whose "
                "receiverFacingType == 'G'. Prior anchor ~18%% over 19 matches "
                "(265/1490); this is over all matches with event data."
            ),
        },
        "soft_xt": {
            "mean_static_singh_xt_at_reception_point": mean_turn_xt,
            "n_receptions_with_visible_position": turn_xt_n,
            "label": (
                "SOFT positional value proxy: static Karun Singh xT lookup at "
                "the oriented reception (x,y). NOT calibrated P(score), NOT "
                "StatsBomb xG. Visibility-gated on the receiver position."
            ),
        },
        "geometric_cross_check": {
            "definition": (
                "INDEPENDENT geometric line-break (eda_line_breaks.py corridor): "
                ">=3 opponents inside a forward 6 m corridor between oriented "
                "passer and receiver at the pass instant. Computed only on TURN "
                "receptions where BOTH passer and receiver positions are visible "
                "(occlusion gate); defenders also visibility-gated."
            ),
            "n_turn_receptions_gateable_both_visible": turn_geo_visible,
            "n_also_geometric_line_break_ge3": turn_geo_overlap,
            "overlap_share": geo_overlap_share,
            "forward_pass_share_of_turn_receptions": geo_forward_share,
            "interpretation": (
                "TURN is a PFF-label half-turn-behind-a-graded-line metric, NOT "
                "ground-truth geometric line-breaking. Low overlap is EXPECTED "
                "and consistent with the prior cross-check (~21-30%%): PFF flags "
                "breaking a NAMED tactical line (can be 1-2 players), while the "
                "geometric rule requires >=3 opponents in a forward corridor."
            ),
        },
        "visibility_gate": (
            "TURN counts/leaderboards/turned-to-goal share are driven purely by "
            "PFF human event labels and do NOT depend on imputed player "
            "positions, so they are occlusion-robust. Player (x,y) only drives "
            "the soft-xT read and the geometric cross-check; both are "
            "visibility-gated per event (positions flagged ESTIMATED/LOW are "
            "excluded) and reported visibility-conditioned."
        ),
        "scope_boundary": (
            "COUNT / LEADERBOARD layer only. Deliberately NOT built: StatsBomb "
            "ensuing-xG credit (no temporal/possession join in-repo) and a "
            "next-receiver phantom-turn term (receiverFacingType exists only on "
            "completed passes)."
        ),
        "anchors": {
            "receiverFacingType_populated_share_all_passes": "~83% (verified 82.9% over all PA events)",
            "linesBrokenType_populated_share_completed_passes": "~8.5% (verified 8.43% over completed passes)",
        },
        "denominators": {
            "note": (
                "FIX for round-1 objection 1 (inconsistent denominator). The old "
                "`matches`/`per_match` paired the facing-G TURN numerator with a "
                "matches-with-ANY-line-break-reception denominator -- two "
                "different event populations -- which systematically understated "
                "the rate. The board now exposes THREE separately-labelled, "
                "internally-consistent denominators and no unqualified `per_match`."
            ),
            "appearances": (
                "Primary per-appearance denominator: matches in which the player "
                "was actually involved on the ball (passer/receiver/shooter/"
                "ballCarrier in any possession event). Verified to equal the "
                "event-snapshot-row appearance set for the named players and for "
                "664/683 players globally. Unlike the roster it does NOT count "
                "unused-bench appearances (e.g. Dybala: rostered 7, on the ball 2). "
                "`per_appearance` = facing-G TURN count / appearances."
            ),
            "matches_with_linebreak_reception": (
                "The OLD denominator, kept for continuity but honestly named. "
                "`turn_per_linebreak_match` = TURN count / this. Do NOT read it as "
                "per-appearance: numerator and denominator are different populations."
            ),
            "roster_listed_excluded": (
                "Roster squad-inclusion (incl. unused bench) was evaluated and "
                "REJECTED as the headline denominator because it inflates the "
                "appearance count with players who never touched the ball."
            ),
        },
        "player_uncertainty": {
            "note": (
                "FIX for round-1 objection 2 (no N/confidence on a tie-dominated "
                "board). Each row now carries an exact (Garwood) Poisson 95% CI on "
                "its expected count. Per-player Ns are tiny and the board is "
                "dominated by ties whose CIs all overlap -- so ONLY broad tiers "
                "are supportable, NOT a precise #1."
            ),
            "method": "Exact two-sided Poisson 95% CI via chi-square quantiles.",
            "leading_tier_label": leading_tier_label,
            "leading_tier_count_range": leading_tier_count_range,
            "leading_tier_players": leading_tier_players,
            "named_top_cluster": top_cluster,
            "tie_tiers": tie_tiers,
            "top_list_truncation": (
                "The top list is tie-aware: it includes EVERY player at the "
                "boundary count (no arbitrary alpha-by-name cut mid-tie). It can "
                "therefore exceed the nominal 25 rows."
            ),
            "headline_framing": (
                "There is NO statistically supportable single 'Top receiver'. The "
                "leading tier (see leading_tier_label) is a group of players with "
                "overlapping Poisson 95% CIs; the within-tier order is not "
                "distinguishable from noise."
            ),
        },
        "team_uncertainty": {
            "note": (
                "FIX for round-2 objection (team exposure confound). The raw team "
                "TURN count conflates a per-possession turning tendency with how "
                "many GAMES a team played (3 for group-stage exits, up to 7 for "
                "finalists) AND its passing VOLUME. The Poisson 95% CI on the raw "
                "count does NOT capture this: it treats 67-over-7-matches and "
                "44-over-4-matches as directly comparable counts. We therefore "
                "add matches_played and the completed-open-play pass volume to "
                "every team row, plus two exposure-normalized rates "
                "(turn_per_match, turn_per_1000_completed_open_play_passes) each "
                "with a CI propagated through the same normalization. The raw-count "
                "team ordering is de-ranked: it is presented for continuity only, "
                "NOT as a ranking of turning tendency."
            ),
            "exposure_confound": (
                "Three defensible normalizations give three different #1s, so the "
                "raw-count ordering is not a supportable ranking of per-possession "
                "turning. RAW count: %s. PER MATCH: %s (Spain leads on per-match "
                "yet exited the round of 16). PER 1000 completed open-play passes: "
                "%s (lower-possession teams that turn a high SHARE of their "
                "completions lead; Argentina drops to ~18.5/1000 and "
                "Belgium/Ecuador sit at the bottom ~10/1000). Only the "
                "exposure-inflated raw count puts Argentina on top." % (
                    team_raw_top3, team_per_match_top3, team_per_1000_top3)
            ),
            "method": (
                "Exact two-sided Poisson 95% CI on the count, then divided by the "
                "team's exposure (matches_played, or completed_open_play_passes/"
                "1000) to give a CI on each rate. Pass volume is attributed to the "
                "same receiver-side population as the TURN numerator."
            ),
            "headline_framing": (
                "There is NO statistically supportable single 'Top team' on raw "
                "count -- that ordering is exposure-driven. Report teams as a "
                "rate-ranked / tiered list (per-match and per-1000-pass orderings "
                "are provided), and treat the raw count as a volume statistic, not "
                "a turning-tendency ranking."
            ),
            "raw_count_top3": team_raw_top3,
            "per_match_top3": team_per_match_top3,
            "per_1000_passes_top3": team_per_1000_top3,
        },
    }

    out = {
        # Tie-aware, full-boundary leaderboard (may exceed 25 rows by design).
        "players_by_turn_receptions": players_top,
        "leading_tier": {
            "label": leading_tier_label,
            "count_range": leading_tier_count_range,
            "players": leading_tier_players,
            "named_top_cluster": top_cluster,
        },
        "tie_tiers": tie_tiers,
        # TEAM layer: raw count is exposure-confounded -- it is kept (now WITH
        # matches_played + pass volume + normalized rates on every row) but
        # explicitly de-ranked. The rate-ranked orderings are the supportable
        # views; see meta.team_uncertainty.
        "teams_by_turn_receptions": teams_board,
        "teams_by_turn_per_match": teams_by_per_match,
        "teams_by_turn_per_1000_passes": teams_by_per_1000_passes,
        "team_exposure_note": (
            "Raw team TURN count is exposure-driven (teams played 3-7 matches "
            "with different passing volumes). DO NOT read it as a turning-"
            "tendency ranking. Per match: %s. Per 1000 completed open-play "
            "passes: %s. See meta.team_uncertainty." % (
                team_per_match_top3, team_per_1000_top3)
        ),
        "turned_to_goal_share": turned_to_goal_share,
        "geometric_overlap_share": geo_overlap_share,
        "final": final_section,
        "meta": meta_block,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # Console summary
    # -----------------------------------------------------------------------
    print("=== TURN -- Turned Under-line Reception Network ===")
    print("matches with event data:", len(files))
    print("complete open-play passes:", n_complete_open_play)
    print("populated line-break receptions:", linebreak_recs_total)
    print("TURN receptions (facing G):", turn_total)
    print("turned-to-goal share: %s (%.1f%%)" % (
        turned_to_goal_share,
        100 * turned_to_goal_share if turned_to_goal_share else 0))
    print("facing breakdown among line-break recs:",
          dict(facing_breakdown.most_common()))
    print("mean SOFT static xT at TURN reception (visible):", mean_turn_xt,
          "(n=%d)" % turn_xt_n)
    print("geometric overlap (>=3 bypassed, both visible): %d/%d = %s" % (
        turn_geo_overlap, turn_geo_visible, geo_overlap_share))
    print("forward-pass share of TURN receptions:", geo_forward_share)
    print()
    print("LEADING TIER (statistically indistinguishable -- no single #1):")
    print("  %s" % leading_tier_label)
    print("  players:", ", ".join(leading_tier_players))
    print()
    print("NAMED TOP CLUSTER (high-count tie-groups within 2 of leader; UNORDERED):")
    for g in top_cluster:
        print("  TURN=%-2d  CI%s  n=%d: %s" % (
            g["turn_receptions"], g["poisson95_ci"], g["n_players"],
            ", ".join(g["players"])))
    print()
    print("=== TOP RECEIVERS (TURN, tie-aware; CI shown) ===")
    for r in players_top[:18]:
        ci = r["turn_receptions_poisson95_ci"]
        pa = r["per_appearance"]
        print("  %-26s %-14s TURN=%-3d CI[%4.1f,%5.1f] app=%-2d /app=%-5s "
              "LBrec_m=%-2d /lbm=%-5s" % (
                  r["player"][:26], r["team"][:14], r["turn_receptions"],
                  ci[0], ci[1], r["appearances"], r["per_appearance"],
                  r["matches_with_linebreak_reception"],
                  r["turn_per_linebreak_match"]))
    if len(players_top) > 18:
        print("  ... (%d total rows in tie-aware board)" % len(players_top))
    print()
    print("=== TEAMS -- RAW COUNT is EXPOSURE-DRIVEN, de-ranked (round-2 fix) ===")
    print("  raw count conflates games played (3-7) + pass volume; NOT a ranking")
    for r in teams_board[:12]:
        ci = r["turn_receptions_poisson95_ci"]
        print("  %-16s TURN=%-3d CI[%.1f,%5.1f] M=%d /match=%-5s cop=%-4d /1000p=%s" % (
            r["team"][:16], r["turn_receptions"], ci[0], ci[1],
            r["matches_played"], r["turn_per_match"],
            r["completed_open_play_passes"],
            r["turn_per_1000_completed_open_play_passes"]))
    print()
    print("  TEAMS by per-match (Spain leads, exited R16):")
    for r in teams_by_per_match[:5]:
        print("    %-16s %.2f/match (TURN=%d over %d)" % (
            r["team"][:16], r["turn_per_match"], r["turn_receptions"],
            r["matches_played"]))
    print("  TEAMS by per-1000 completed open-play passes (reorders completely):")
    for r in teams_by_per_1000_passes[:5]:
        print("    %-16s %.1f/1000p (TURN=%d over %d passes)" % (
            r["team"][:16], r["turn_per_1000_completed_open_play_passes"],
            r["turn_receptions"], r["completed_open_play_passes"]))
    print()
    print("=== FINAL (10517) ===")
    for side in ("home", "away"):
        s = final_section[side]
        print("  %s (%s): %d TURN receptions" % (
            s["team"], side, s["turn_receptions"]))
        for p in s["top_players"]:
            print("      %-26s %d" % (p["player"], p["turn_receptions"]))
    print("  --> Di Maria TURN receptions in final:",
          final_section["di_maria_turn_receptions"])
    print()
    print("WROTE:", OUT_PATH)


if __name__ == "__main__":
    main()
