#!/usr/bin/env python3
"""
CoCE -- "Cost of the Closed Eye" : the Ignored Open Man Index.

A label-anchored, event-based metric built on PFF FC World Cup 2022 EVENT data.
Every possession event that PFF tagged with a populated ``betterOptionPlayerId``
flags a better option the on-ball player did NOT take. For the "ignored OPEN MAN"
reading we resolve that miss to:

  * the passer (the "closed eye") -- the on-ball actor who ignored the better option
  * the ignored open man (betterOptionPlayerId -> roster name/team)
  * the pressureType on the passer (N / P / A / L)
  * the ignored man's (x, y) at the event snapshot, oriented so the player's team
    attacks +x, and his per-event tracking VISIBILITY (VISIBLE vs ESTIMATED)
  * the BALL's (x, y) at the snapshot and its per-event VISIBILITY (both endpoints
    of the xT-proxy delta are now visibility-tracked)

and VALUES the miss as a SOFT xT proxy (see the loud caveat below).

==============================================================================
LABEL HYGIENE -- betterOptionPlayerId is NOT purely "an open teammate"
==============================================================================
betterOptionPlayerId is a single PFF analyst's "the better option was X" judgement.
In 8 of the 518 events the flagged better option is the ON-BALL ACTOR HIMSELF
(betterOptionPlayerId == the resolved actorId), with betterOptionType encoding an
ACTION the analyst thought the player should have taken himself (H=header, S=shot,
B, L, P) -- i.e. "you should have shot/headed it yourself", NOT "a different
teammate was open." There is NO betterOptionType codebook in the repo, so the
action-code meaning is inferred only from these self-reference rows.

Those 8 self-reference events are NOT "ignored open man" events: the "ignored
location" is just the actor's own (ball) location, so their xt_proxy is ~0 and
they silently pad the Ignored-Creator / Closed-Eye / team tallies. We therefore
EXCLUDE them from every load-bearing tally (Ignored Creator, Closed Eye, team
counts, and the xT-proxy aggregates) and count them in meta.self_reference. This
matters for the headline: En-Nesyri had 1 self-reference event, so his raw N=8
"most-ignored open man" drops to N=7 NET, tying the existing five-way N=7 group
(now a SIX-way tie). The self-reference rows are kept in the per-row table with a
``self_reference`` flag and ``in_tally=False`` for audit, and meta.label_decomposition
breaks the 518 down by possessionEventType and self-reference so a reader can see
the label is not a pure "open teammate" signal.

The SYMMETRIC TWIN of self-reference is CROSS-TEAM (opponent) contamination: in 2
of the events the betterOptionPlayerId is on the OPPOSING team, not a teammate of
the on-ball actor (almost certainly a PFF playerId data-entry slip). An opponent
is even MORE clearly NOT "an ignored open teammate" than a self-reference is, and
it breaks the load-bearing teammate assumptions of this metric:
  (a) team_misses would credit the miss to the IGNORED MAN's (opponent's) team --
      e.g. a Danish passer's miss credited to AUSTRALIA;
  (b) the xt_proxy orients the "ball" reference to the IGNORED MAN's attacking
      direction on the (correct, for teammates) premise that "the ball belongs to
      the SAME attacking team" -- but for an opponent the ball and the ignored man
      sit on OPPOSITE attack directions, so the proxy delta mixes two orientations.
The two confirmed events (verified from raw Event Data + Rosters AND by snapshot
home/away-side disagreement):
  * game 3848 (Denmark vs Australia): actor=Andreas Skov Olsen (Denmark),
    betterOption=Mathew Leckie (Australia), PA / betterOptionType=P
  * game 3854 (Spain vs Japan): actor=Pedri (Spain), betterOption=Ayase Ueda
    (Japan), PA / betterOptionType=P (Ueda not in the snapshot -> pos_missing)
We EXCLUDE these from every load-bearing tally exactly like self-reference (they
are kept as audit rows with ``cross_team=True`` / ``in_tally=False``), count them
in meta.cross_team, and trim the affected team boards: Australia 7->6, Japan
16->15. None of the headline leaderboard ranks change (Skov Olsen / Pedri are not
top-20 closed-eye; Australia / Japan are not board leaders) -- this is a
LOW-MATERIALITY integrity fix that restores the truth of the "open teammate"
claim and the teammate-based team attribution + orientation.

The TOTAL PFF label count remains 518 (``total_better_option_events``); the number
actually TALLIED into the leaderboards is ``coce_tallied_events`` = 518 - 8 (self-
reference) - 2 (cross-team) = 508.

==============================================================================
SOFT-PROXY DISCLAIMER (read before quoting any number)
==============================================================================
The "xT left on the table" value is a STATIC Singh (2019) xT-grid LOOKUP DIFFERENCE:

    xt_proxy = xT(ignored_open_man_location) - xT(actual_ball_location)

It is a coarse, hand-wavy *positional* proxy for "how much more dangerous the
ignored option's spot was than where the ball actually was." It is:
  - NOT calibrated P(score)
  - NOT StatsBomb xG (no PFF<->StatsBomb possession alignment exists in-repo)
  - NOT a model output; it is a fixed 12x8 grid lookup at two points
Treat every xt_proxy figure as a soft, directional, exploratory proxy only.

==============================================================================
STATISTICAL ROBUSTNESS (read before quoting any RANKING)
==============================================================================
With only 518 betterOption events spread over ~281 ignored men / ~288 passers,
the per-player leaderboards are THIN DESCRIPTIVE TALLIES, NOT a separable
ranking. Most players appear 1-2 times; only a handful reach N>=5. After the
self-reference drop the Ignored-Creator board has NO unique rank-1: En-Nesyri
(was N=8 raw) falls to N=7 and joins a SIX-way tie at N=7 (a Poisson
+/- sqrt(count) band on N=7 is [4.4, 9.6], heavily overlapping the N>=4 tail).
We therefore:
  - attach a Poisson +/- sqrt(count) interval (``ci_lo``/``ci_hi``) to every
    leaderboard row's primary count;
  - flag tie groups explicitly (``tie_group`` field) so ordering within a tie
    is not read as a finding;
  - publish the full N-distribution in meta so a reader sees the long tail;
  - for the xT-proxy boards, expose ``positive_delta_events`` (N) and
    ``max_single_delta_share`` (largest single event / total) and flag rows that
    are effectively single-event (``concentration_flag``); a minimum-N display
    cut (MIN_XT_POS_EVENTS) is applied to a separate "stable" view.
The HARD COUNTS (misses, times-ignored, pressure split) are exact PFF label
counts and are the load-bearing numbers; everything else is descriptive.

Team totals are EXPOSURE-DRIVEN: a team accrues betterOption events simply by
playing more matches, so the raw team total is correlated with how far the team
advanced. We therefore add ``games_played`` and a ``per_game`` rate to every
team row; the per-game rate is the comparable figure (it reorders the board --
Germany 9.67/game tops it, while Argentina's raw-#1 32 is 4.57/game).

==============================================================================
SUBSTRATE / COVERAGE
==============================================================================
betterOptionPlayerId lives in the EVENT data, which covers ALL 64 matches
(the tracking *cache* only covers 44 -- this metric does NOT use it). Player
(x,y) and per-player ``visibility`` come from the event snapshot's
homePlayers/awayPlayers arrays (22 positions per event). ~46% of off-ball
positions tournament-wide are ESTIMATED; we attach a per-row visibility flag to
BOTH the ignored man AND the ball and report aggregates split on the JOINT
both-endpoints-VISIBLE condition.

==============================================================================
ORIENTATION (now GK-derived, no hand parity formula)
==============================================================================
Coordinates are meters, center origin, x in [-52.5, 52.5], y in [-34, 34].
We orient every quoted location so the relevant player's TEAM attacks +x.

We DERIVE the attack direction per (game, period) DIRECTLY from each team's
goalkeeper mean x-position in the event snapshots: a GK sitting at -x means his
team defends the left goal and therefore ATTACKS +x. This is robust to whatever
homeTeamStartLeftExtraTime actually encodes. We verified it against all matches:
it agrees with the metadata odd/even parity rule on 100% of normal-time periods
(P1/P2), and DISAGREES only in extra time (8 of 138 periods) -- exactly where
the old parity formula was inverted.

The old parity rule (start_left == period-is-odd, reusing start_left_et for ET)
was WRONG for ET: in match 10517 (Final) observed home GK mean x is +37.2 in P3
and -40.3 in P4 (so home attacks -x in P3, +x in P4), but the parity rule
predicted the opposite. 9 of the 11 ET betterOption events had a mirrored
location and thus a wrong-sign/magnitude xt_proxy under the old rule. The
GK-derived orientation fixes all of them.

Pure standard library + the bundled Singh xT grid. Run from repo root:
    PYTHONPATH=src uv run python research/scripts/coce_ignored_open_man.py
"""

import json
import glob
import math
import os
from collections import defaultdict, Counter

from wc2026_tracking_transformer.baselines.xt import xt_for_ball

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_ROOT = os.environ.get("PFF_ROOT") or "/Users/nick/pff_wc22_local"
EVENT_GLOB = os.path.join(DATA_ROOT, "Event Data", "*.json")
ROSTER_GLOB = os.path.join(DATA_ROOT, "Rosters", "*.json")
META_GLOB = os.path.join(DATA_ROOT, "Metadata", "*.json")
OUT_PATH = "/Users/nick/wc2026-tracking-transformer/research/data/coce.json"

# Pitch half-extents (meters), center origin.
PITCH_HALF_X = 52.5
PITCH_HALF_Y = 34.0

# A GK whose mean |x| in a period is below this (meters) is too central to
# disambiguate attack direction; we fall back to the other team's GK.
GK_X_MIN = 10.0

# Minimum positive-delta event count for the "stable" xT-proxy display view.
MIN_XT_POS_EVENTS = 3

# pressureType on the on-ball actor: N=none, P=pressured, A=aggressive, L=lunge.
# UNDER PRESSURE (P/A/L) = the miss is partly excusable (rushed, hounded).
# IN SPACE (N) = no pressure on the passer => ignoring the open man is damning.
PRESSURE_UNDER = {"P", "A", "L"}

# Actor priority for the "closed eye" (who held/played the ball and ignored the
# better option). Same priority family the EDA template uses.
ACTOR_FIELDS = [
    ("passerPlayerId", "passerPlayerName"),
    ("crosserPlayerId", "crosserPlayerName"),
    ("shooterPlayerId", "shooterPlayerName"),
    ("clearerPlayerId", "clearerPlayerName"),
    ("ballCarrierPlayerId", "ballCarrierPlayerName"),
    ("carrierPlayerId", "carrierPlayerName"),
    ("dribblerPlayerId", "dribblerPlayerName"),
    ("touchPlayerId", "touchPlayerName"),
]


def load_rosters():
    """playerId(int) -> (name, team). Authoritative 32-squad mapping."""
    pid_name, pid_team = {}, {}
    for fp in glob.glob(ROSTER_GLOB):
        with open(fp) as f:
            rows = json.load(f)
        for row in rows:
            try:
                pid = int(row["player"]["id"])
            except (KeyError, TypeError, ValueError):
                continue
            nm = row["player"].get("nickname")
            if nm:
                pid_name[pid] = nm
            tm = (row.get("team") or {}).get("name")
            if tm:
                pid_team[pid] = tm
    return pid_name, pid_team


def gk_orientation_for_match(data):
    """Derive home-attacks-+x per period DIRECTLY from GK mean x-positions.

    Returns ``period -> bool|None`` where True means the HOME team attacks +x in
    that period. A GK at -x means his team defends the left goal and attacks +x.
    We average over every event snapshot in the period; if the home GK is too
    central (|mean x| < GK_X_MIN) we use the away GK (mirrored). None if neither
    GK is resolvable for that period.
    """
    home_gk = defaultdict(list)
    away_gk = defaultdict(list)
    for ev in data:
        per = (ev.get("gameEvents") or {}).get("period")
        if per not in (1, 2, 3, 4):
            continue
        for p in ev.get("homePlayers") or []:
            if p.get("positionGroupType") == "GK" and p.get("x") is not None:
                home_gk[per].append(p["x"])
        for p in ev.get("awayPlayers") or []:
            if p.get("positionGroupType") == "GK" and p.get("x") is not None:
                away_gk[per].append(p["x"])
    out = {}
    for per in (1, 2, 3, 4):
        h = sum(home_gk[per]) / len(home_gk[per]) if home_gk[per] else None
        a = sum(away_gk[per]) / len(away_gk[per]) if away_gk[per] else None
        if h is not None and abs(h) >= GK_X_MIN:
            out[per] = (h < 0)            # home GK on -x => home attacks +x
        elif a is not None and abs(a) >= GK_X_MIN:
            out[per] = (a > 0)            # away GK on +x => home attacks +x
        else:
            out[per] = None
    return out


def orient_xy(x, y, team_is_home, home_plus_x):
    """Rotate (x,y) so the player's TEAM attacks +x.

    If the player's team already attacks +x in this period, return as-is.
    Otherwise 180-deg rotate (negate both axes).
    """
    team_plus_x = home_plus_x if team_is_home else (not home_plus_x)
    if team_plus_x:
        return x, y
    return -x, -y


def xt_at(x_m, y_m):
    """Static Singh xT lookup at a metric (x,y) location, oriented to attack +x.

    Normalize meters -> [-1,1] for the grid helper. x_norm=+1 is the attacking
    goal line; the grid increases toward +x and peaks in the central channel.
    """
    xn = max(-1.0, min(1.0, x_m / PITCH_HALF_X))
    yn = max(-1.0, min(1.0, y_m / PITCH_HALF_Y))
    return xt_for_ball(xn, yn)


def find_player_pos(ev, pid):
    """Return the (player_dict, side) for playerId pid in the event snapshot, or (None, None)."""
    for side in ("homePlayers", "awayPlayers"):
        for p in ev.get(side) or []:
            if p.get("playerId") == pid:
                return p, side
    return None, None


def actor_id_name(pe):
    """(playerId, playerName) of the on-ball actor (the closed eye)."""
    for idf, namef in ACTOR_FIELDS:
        if pe.get(idf):
            return pe.get(idf), pe.get(namef)
    return None, None


def ball_xy_vis(ev):
    """(x, y, visibility) of the ball at the snapshot, or (None, None, 'NO_BALL')."""
    ball = ev.get("ball")
    b0 = None
    if isinstance(ball, list) and ball:
        b0 = ball[0]
    elif isinstance(ball, dict):
        b0 = ball
    if b0 and b0.get("x") is not None and b0.get("y") is not None:
        return b0.get("x"), b0.get("y"), b0.get("visibility")
    return None, None, "NO_BALL"


def poisson_ci(count):
    """Symmetric Poisson 1-sigma band: count +/- sqrt(count), floored at 0."""
    s = math.sqrt(count)
    return round(max(0.0, count - s), 2), round(count + s, 2)


def tie_groups(counter):
    """Map playerId -> tie-group size at its count (how many players share that count)."""
    by_count = Counter(counter.values())
    return {pid: by_count[c] for pid, c in counter.items()}


def main():
    pid_name, pid_team = load_rosters()
    ev_name = {}  # event-data fallback names

    def name_of(pid, fallback=None):
        if fallback:
            ev_name.setdefault(pid, fallback)
        return pid_name.get(pid) or ev_name.get(pid) or fallback or "Unknown(%s)" % pid

    def team_of(pid, fallback=None):
        return pid_team.get(pid) or fallback or "Unknown"

    # ---- accumulators ----
    # Closed Eye (passer-side)
    ce_misses = Counter()                  # total misses
    ce_misses_pressure = Counter()         # under pressure (P/A/L)
    ce_misses_space = Counter()            # in space (N)
    ce_xt_total = defaultdict(float)       # total positive xt-proxy forgone (any visibility)
    ce_xt_space = defaultdict(float)       # xt forgone with no pressure
    ce_xt_vis = defaultdict(float)         # positive xt forgone, BOTH endpoints VISIBLE only
    ce_xt_pos_n = Counter()                # # positive-delta events (any vis)
    ce_xt_pos_n_vis = Counter()            # # positive-delta events, both VISIBLE
    ce_xt_max = defaultdict(float)         # largest single positive delta
    ce_name = {}
    ce_team = {}

    # Ignored Creator (receiver-side)
    ic_count = Counter()
    ic_count_pressure = Counter()          # ignored while passer under pressure
    ic_count_space = Counter()             # ignored while passer in space (damning)
    ic_xt_total = defaultdict(float)
    ic_xt_vis = defaultdict(float)
    ic_xt_pos_n = Counter()
    ic_xt_pos_n_vis = Counter()
    ic_xt_max = defaultdict(float)
    ic_name = {}
    ic_team = {}

    # Team-level (attribution = the team of the IGNORED OPEN MAN / their own
    # attacking team, since the ignored man and the passer are teammates).
    team_misses = Counter()
    team_misses_space = Counter()
    team_misses_pressure = Counter()
    team_xt_total = defaultdict(float)
    team_xt_vis = defaultdict(float)
    team_games = defaultdict(set)          # distinct game ids per team (exposure)

    # per-row detail (for visibility flags + audit)
    rows = []

    # tournament counters
    n_matches = 0
    total_bo = 0                   # ALL populated betterOptionPlayerId events (the PFF label total)
    tallied_events = 0             # events actually counted into the leaderboards (self-ref + cross-team dropped)
    self_ref_count = 0             # betterOptionPlayerId == on-ball actor (NOT an open-teammate miss)
    self_ref_examples = []         # audit list of the dropped self-reference events
    cross_team_count = 0           # betterOptionPlayerId on the OPPONENT (NOT an open teammate)
    cross_team_examples = []       # audit list of the dropped cross-team events
    # label decomposition: possessionEventType x self-reference, to show the label
    # is NOT a pure "open teammate" signal.
    label_petype_all = Counter()
    label_petype_selfref = Counter()
    pressure_dist = Counter()
    bo_type_dist = Counter()
    period_dist = Counter()
    vis_dist = Counter()           # visibility of the ignored man
    ball_vis_dist = Counter()      # visibility of the ball (reference endpoint)
    joint_visible = 0              # BOTH ignored man and ball VISIBLE
    pos_missing = 0                # ignored man not in snapshot
    ball_missing = 0               # no ball location AND no actor fallback
    ref_used = Counter()           # which reference location used for the actual-ball xT
    xt_proxy_positive = 0          # ignored spot more valuable than ball
    xt_proxy_nonpos = 0
    et_events = 0                  # events in extra-time periods (orientation-sensitive)
    orient_unresolved = 0          # events where GK orientation could not be derived

    files = sorted(glob.glob(EVENT_GLOB))

    for fp in files:
        with open(fp) as f:
            data = json.load(f)
        if not data:
            continue
        n_matches += 1
        try:
            gid = int(data[0].get("gameId"))
        except (TypeError, ValueError):
            gid = None

        # GK-derived attack direction per period for THIS match.
        gk_orient = gk_orientation_for_match(data)

        for ev in data:
            pe = ev.get("possessionEvents") or {}
            bo_id = pe.get("betterOptionPlayerId")
            if not bo_id:
                continue
            total_bo += 1

            ge = ev.get("gameEvents") or {}
            period = ge.get("period")
            bo_type = pe.get("betterOptionType")
            pet = pe.get("possessionEventType")

            # names / teams
            bo_name = pe.get("betterOptionPlayerName")
            if bo_name:
                ev_name.setdefault(bo_id, bo_name)
            bo_team = team_of(bo_id)

            actor_id, actor_nm = actor_id_name(pe)
            if actor_id and actor_nm:
                ev_name.setdefault(actor_id, actor_nm)

            # ---- LABEL HYGIENE: drop self-reference events ----
            # betterOptionPlayerId == the on-ball actor means the analyst flagged an
            # action the player should have done HIMSELF (header/shot/etc.), NOT an
            # ignored OPEN TEAMMATE. These are not "ignored open man" events; they
            # silently pad the load-bearing tallies (their xt_proxy is ~0 because the
            # "ignored location" is the actor's own ball location). Count them in the
            # label decomposition, record an audit row, and EXCLUDE them from every
            # leaderboard / team / xt-proxy aggregate.
            self_reference = (actor_id is not None and actor_id == bo_id)
            label_petype_all[pet] += 1
            if self_reference:
                self_ref_count += 1
                label_petype_selfref[pet] += 1
                self_ref_examples.append({
                    "game_id": gid,
                    "period": period,
                    "player": name_of(bo_id, bo_name),
                    "team": bo_team,
                    "possession_event_type": pet,
                    "better_option_type": bo_type,
                })
                rows.append({
                    "game_id": gid,
                    "period": period,
                    "is_extra_time": period in (3, 4),
                    "passer_id": actor_id,
                    "passer": name_of(actor_id, actor_nm) if actor_id else None,
                    "team": bo_team,
                    "ignored_id": bo_id,
                    "ignored_man": name_of(bo_id, bo_name),
                    "pressure_type": pe.get("pressureType"),
                    "better_option_type": bo_type,
                    "possession_event_type": pet,
                    "self_reference": True,
                    "cross_team": False,
                    "in_tally": False,
                    "note": "self-reference (betterOptionPlayerId == on-ball actor); NOT an ignored-open-man event; excluded from all tallies",
                })
                continue

            # ---- LABEL HYGIENE: drop cross-team (opponent) events ----
            # betterOptionPlayerId on the OPPOSING team (the on-ball actor's roster
            # team != the betterOption's roster team, both known) is NOT an "ignored
            # OPEN TEAMMATE" -- it is almost certainly a PFF playerId data-entry slip.
            # It is the symmetric twin of the self-reference defect (an opponent is
            # even more clearly not a teammate). Leaving it in (a) mis-credits the
            # miss to the ignored man's (opponent's) team and (b) mixes two attacking
            # orientations in the xt_proxy (the ball belongs to the passer's team, but
            # the proxy orients the ball to the ignored man's opposing team). We
            # EXCLUDE it from every load-bearing tally exactly like self-reference,
            # keep it as an audit row (cross_team=True, in_tally=False), and count it
            # in meta.cross_team.
            actor_team = team_of(actor_id) if actor_id is not None else None
            actor_team_known = actor_id is not None and actor_id in pid_team
            bo_team_known = bo_id in pid_team
            cross_team = actor_team_known and bo_team_known and actor_team != bo_team
            if cross_team:
                cross_team_count += 1
                cross_team_examples.append({
                    "game_id": gid,
                    "period": period,
                    "actor_id": actor_id,
                    "actor": name_of(actor_id, actor_nm),
                    "actor_team": actor_team,
                    "ignored_id": bo_id,
                    "ignored_man": name_of(bo_id, bo_name),
                    "ignored_man_team": bo_team,
                    "possession_event_type": pet,
                    "better_option_type": bo_type,
                })
                rows.append({
                    "game_id": gid,
                    "period": period,
                    "is_extra_time": period in (3, 4),
                    "passer_id": actor_id,
                    "passer": name_of(actor_id, actor_nm) if actor_id else None,
                    "team": bo_team,
                    "ignored_id": bo_id,
                    "ignored_man": name_of(bo_id, bo_name),
                    "pressure_type": pe.get("pressureType"),
                    "better_option_type": bo_type,
                    "possession_event_type": pet,
                    "self_reference": False,
                    "cross_team": True,
                    "in_tally": False,
                    "note": "cross-team (betterOptionPlayerId on the OPPONENT, actor_team=%s != ignored_man_team=%s); NOT an ignored-open-teammate event; likely a PFF playerId data-entry error; excluded from all tallies (team attribution and xt_proxy would be unreliable)" % (actor_team, bo_team),
                })
                continue

            # ---- from here on: genuine ignored-open-man events only ----
            tallied_events += 1
            period_dist[period] += 1
            if period in (3, 4):
                et_events += 1
            pt = pe.get("pressureType")
            pressure_dist[pt] += 1
            bo_type_dist[bo_type] += 1

            under_pressure = pt in PRESSURE_UNDER
            in_space = (pt == "N")

            # ---- locate the ignored open man in the snapshot ----
            bo_pos, bo_side = find_player_pos(ev, bo_id)
            ignored_x = ignored_y = None
            visibility = None
            team_is_home = None
            if bo_pos and bo_pos.get("x") is not None:
                team_is_home = (bo_side == "homePlayers")
                visibility = bo_pos.get("visibility")
                vis_dist[visibility] += 1
                ignored_x, ignored_y = bo_pos.get("x"), bo_pos.get("y")
            else:
                pos_missing += 1
                vis_dist["NO_POSITION"] += 1

            # ---- reference location for the "actual ball" xT (track ball visibility) ----
            # Prefer the ball snapshot location; fall back to actor position; if
            # neither is available we cannot compute the xt-proxy delta for this event.
            bx, by, ball_vis = ball_xy_vis(ev)
            ball_vis_dist[ball_vis] += 1
            ref_x = ref_y = None
            ref_team_is_home = team_is_home
            ref_visible = (ball_vis == "VISIBLE")
            if bx is not None and by is not None:
                ref_x, ref_y = bx, by
                ref_used["ball"] += 1
            else:
                actor_pos, actor_side = (None, None)
                if actor_id:
                    actor_pos, actor_side = find_player_pos(ev, actor_id)
                if actor_pos and actor_pos.get("x") is not None:
                    ref_x, ref_y = actor_pos.get("x"), actor_pos.get("y")
                    ref_team_is_home = (actor_side == "homePlayers")
                    ref_used["actor"] += 1
                    ref_visible = (actor_pos.get("visibility") == "VISIBLE")
                else:
                    ball_missing += 1
                    ref_used["none"] += 1
                    ref_visible = False

            # joint both-endpoints-VISIBLE = ignored man VISIBLE AND reference VISIBLE
            ignored_visible = (visibility == "VISIBLE")
            both_visible = ignored_visible and ref_visible
            if both_visible:
                joint_visible += 1

            # ---- soft xT proxy (GK-derived orientation) ----
            xt_proxy = None
            xt_ignored = None
            xt_ball = None
            hpx = gk_orient.get(period) if period in (1, 2, 3, 4) else None
            if (ignored_x is not None and team_is_home is not None
                    and ref_x is not None and gid is not None and hpx is not None):
                # Orient ignored man so HIS team attacks +x.
                ox, oy = orient_xy(ignored_x, ignored_y, team_is_home, hpx)
                xt_ignored = xt_at(ox, oy)
                # Orient the reference (ball/actor) the same way -- the ball belongs
                # to the SAME attacking team as the open man. This teammate premise is
                # ENFORCED above: self-reference and cross-team (opponent) betterOption
                # tags are gated out before reaching here, so for every TALLIED event
                # the passer/ball and the ignored man share one attacking direction.
                rx, ry = orient_xy(ref_x, ref_y,
                                   ref_team_is_home if ref_team_is_home is not None else team_is_home,
                                   hpx)
                xt_ball = xt_at(rx, ry)
                xt_proxy = xt_ignored - xt_ball
                if xt_proxy > 0:
                    xt_proxy_positive += 1
                else:
                    xt_proxy_nonpos += 1
            elif (ignored_x is not None and team_is_home is not None
                    and ref_x is not None and gid is not None and hpx is None):
                orient_unresolved += 1

            # ---- accumulate Closed Eye (passer) ----
            if actor_id:
                ce_misses[actor_id] += 1
                ce_name[actor_id] = name_of(actor_id, actor_nm)
                ce_team[actor_id] = team_of(actor_id)
                if under_pressure:
                    ce_misses_pressure[actor_id] += 1
                if in_space:
                    ce_misses_space[actor_id] += 1
                if xt_proxy is not None and xt_proxy > 0:
                    ce_xt_total[actor_id] += xt_proxy
                    ce_xt_pos_n[actor_id] += 1
                    if xt_proxy > ce_xt_max[actor_id]:
                        ce_xt_max[actor_id] = xt_proxy
                    if in_space:
                        ce_xt_space[actor_id] += xt_proxy
                    if both_visible:
                        ce_xt_vis[actor_id] += xt_proxy
                        ce_xt_pos_n_vis[actor_id] += 1

            # ---- accumulate Ignored Creator (open man) ----
            ic_count[bo_id] += 1
            ic_name[bo_id] = name_of(bo_id, bo_name)
            ic_team[bo_id] = bo_team
            if under_pressure:
                ic_count_pressure[bo_id] += 1
            if in_space:
                ic_count_space[bo_id] += 1
            if xt_proxy is not None and xt_proxy > 0:
                ic_xt_total[bo_id] += xt_proxy
                ic_xt_pos_n[bo_id] += 1
                if xt_proxy > ic_xt_max[bo_id]:
                    ic_xt_max[bo_id] = xt_proxy
                if both_visible:
                    ic_xt_vis[bo_id] += xt_proxy
                    ic_xt_pos_n_vis[bo_id] += 1

            # ---- team-level (the open man's attacking team) ----
            team_misses[bo_team] += 1
            team_games[bo_team].add(gid)
            if under_pressure:
                team_misses_pressure[bo_team] += 1
            if in_space:
                team_misses_space[bo_team] += 1
            if xt_proxy is not None and xt_proxy > 0:
                team_xt_total[bo_team] += xt_proxy
                if both_visible:
                    team_xt_vis[bo_team] += xt_proxy

            # ---- per-row detail ----
            rows.append({
                "game_id": gid,
                "period": period,
                "is_extra_time": period in (3, 4),
                "passer_id": actor_id,
                "passer": name_of(actor_id, actor_nm) if actor_id else None,
                "team": bo_team,
                "ignored_id": bo_id,
                "ignored_man": name_of(bo_id, bo_name),
                "pressure_type": pt,
                "pressure_bucket": "under_pressure" if under_pressure else ("in_space" if in_space else "other"),
                "better_option_type": bo_type,
                "possession_event_type": pet,
                "self_reference": False,
                "cross_team": False,
                "in_tally": True,
                "ignored_visibility": visibility,
                "ignored_estimated": (visibility == "ESTIMATED"),
                "ball_visibility": ball_vis,
                "ball_estimated": (ball_vis == "ESTIMATED"),
                "both_endpoints_visible": both_visible,
                "ignored_x": round(ignored_x, 3) if ignored_x is not None else None,
                "ignored_y": round(ignored_y, 3) if ignored_y is not None else None,
                "xt_proxy_ignored": round(xt_ignored, 5) if xt_ignored is not None else None,
                "xt_proxy_ball": round(xt_ball, 5) if xt_ball is not None else None,
                "xt_proxy_left_on_table": round(xt_proxy, 5) if xt_proxy is not None else None,
            })

    # ---------------------------------------------------------------------
    # Build leaderboards (with robustness annotations)
    # ---------------------------------------------------------------------
    ce_tie = tie_groups(ce_misses)
    ic_tie = tie_groups(ic_count)

    def closed_eye_rows(n=20):
        out = []
        for pid, c in ce_misses.most_common(n):
            lo, hi = poisson_ci(c)
            out.append({
                "player": ce_name.get(pid, "Unknown(%s)" % pid),
                "team": ce_team.get(pid, "Unknown"),
                "misses": c,
                "ci_lo": lo,
                "ci_hi": hi,
                "tie_group": ce_tie.get(pid, 1),
                "misses_in_space_N": ce_misses_space.get(pid, 0),
                "misses_under_pressure_PAL": ce_misses_pressure.get(pid, 0),
                "xt_proxy_forgone_total": round(ce_xt_total.get(pid, 0.0), 5),
                "xt_proxy_forgone_in_space": round(ce_xt_space.get(pid, 0.0), 5),
                "xt_proxy_forgone_both_visible": round(ce_xt_vis.get(pid, 0.0), 5),
            })
        return out

    def closed_eye_by_xt(n=20):
        items = sorted(ce_xt_total.items(), key=lambda kv: kv[1], reverse=True)[:n]
        out = []
        for pid, v in items:
            posn = ce_xt_pos_n.get(pid, 0)
            mx = ce_xt_max.get(pid, 0.0)
            share = round(mx / v, 3) if v > 0 else None
            out.append({
                "player": ce_name.get(pid, "Unknown(%s)" % pid),
                "team": ce_team.get(pid, "Unknown"),
                "xt_proxy_forgone_total": round(v, 5),
                "xt_proxy_forgone_both_visible": round(ce_xt_vis.get(pid, 0.0), 5),
                "positive_delta_events": posn,
                "positive_delta_events_both_visible": ce_xt_pos_n_vis.get(pid, 0),
                "max_single_delta": round(mx, 5),
                "max_single_delta_share": share,
                "concentration_flag": (posn < MIN_XT_POS_EVENTS or (share is not None and share >= 0.6)),
                "misses": ce_misses.get(pid, 0),
                "xt_proxy_forgone_in_space": round(ce_xt_space.get(pid, 0.0), 5),
            })
        return out

    def closed_eye_by_xt_stable(n=20):
        """Same xT board but restricted to players with >= MIN_XT_POS_EVENTS positive events."""
        items = [(pid, v) for pid, v in ce_xt_total.items()
                 if ce_xt_pos_n.get(pid, 0) >= MIN_XT_POS_EVENTS]
        items.sort(key=lambda kv: kv[1], reverse=True)
        out = []
        for pid, v in items[:n]:
            posn = ce_xt_pos_n.get(pid, 0)
            mx = ce_xt_max.get(pid, 0.0)
            out.append({
                "player": ce_name.get(pid, "Unknown(%s)" % pid),
                "team": ce_team.get(pid, "Unknown"),
                "xt_proxy_forgone_total": round(v, 5),
                "positive_delta_events": posn,
                "max_single_delta_share": round(mx / v, 3) if v > 0 else None,
                "misses": ce_misses.get(pid, 0),
            })
        return out

    def ignored_creator_rows(n=20):
        out = []
        for pid, c in ic_count.most_common(n):
            lo, hi = poisson_ci(c)
            posn = ic_xt_pos_n.get(pid, 0)
            mx = ic_xt_max.get(pid, 0.0)
            tot = ic_xt_total.get(pid, 0.0)
            out.append({
                "player": ic_name.get(pid, "Unknown(%s)" % pid),
                "team": ic_team.get(pid, "Unknown"),
                "times_ignored": c,
                "ci_lo": lo,
                "ci_hi": hi,
                "tie_group": ic_tie.get(pid, 1),
                "ignored_in_space_N": ic_count_space.get(pid, 0),
                "ignored_under_pressure_PAL": ic_count_pressure.get(pid, 0),
                "xt_proxy_total": round(tot, 5),
                "xt_proxy_total_both_visible": round(ic_xt_vis.get(pid, 0.0), 5),
                "positive_delta_events": posn,
                "max_single_delta_share": round(mx / tot, 3) if tot > 0 else None,
                "concentration_flag": (posn < MIN_XT_POS_EVENTS or (tot > 0 and mx / tot >= 0.6)),
            })
        return out

    def team_rows(n=40):
        out = []
        for t, c in team_misses.most_common(n):
            g = len(team_games.get(t, set()))
            lo, hi = poisson_ci(c)
            out.append({
                "team": t,
                "misses": c,
                "ci_lo": lo,
                "ci_hi": hi,
                "games_played": g,
                "misses_per_game": round(c / g, 3) if g else None,
                "misses_in_space_N": team_misses_space.get(t, 0),
                "misses_under_pressure_PAL": team_misses_pressure.get(t, 0),
                "xt_proxy_forgone_total": round(team_xt_total.get(t, 0.0), 5),
                "xt_proxy_forgone_both_visible": round(team_xt_vis.get(t, 0.0), 5),
            })
        return out

    def team_rows_per_game(n=40):
        """Same teams ordered by the EXPOSURE-NORMALIZED per-game rate (the comparable figure)."""
        items = []
        for t, c in team_misses.items():
            g = len(team_games.get(t, set()))
            if g:
                items.append((t, c, g, c / g))
        items.sort(key=lambda r: r[3], reverse=True)
        return [{
            "team": t, "misses": c, "games_played": g, "misses_per_game": round(rate, 3),
        } for t, c, g, rate in items[:n]]

    leaderboards = {
        "closed_eye_by_misses": closed_eye_rows(),
        "closed_eye_by_xt_proxy_forgone": closed_eye_by_xt(),
        "closed_eye_by_xt_proxy_forgone_stable_minN%d" % MIN_XT_POS_EVENTS: closed_eye_by_xt_stable(),
        "ignored_creator_by_times_ignored": ignored_creator_rows(),
        "team_ignored_open_men": team_rows(),
        "team_ignored_open_men_per_game": team_rows_per_game(),
    }

    # ---- N-distributions (the long tail that makes rankings non-separable) ----
    ic_n_hist = dict(sorted(Counter(ic_count.values()).items(), reverse=True))
    ce_n_hist = dict(sorted(Counter(ce_misses.values()).items(), reverse=True))

    # pressure split summary (tournament-level) -- over TALLIED events only.
    n_under = sum(v for k, v in pressure_dist.items() if k in PRESSURE_UNDER)
    n_space = pressure_dist.get("N", 0)
    n_other = tallied_events - n_under - n_space

    ball_est = ball_vis_dist.get("ESTIMATED", 0)

    meta = {
        "metric": "CoCE -- Cost of the Closed Eye (Ignored Open Man Index)",
        "data_source": "PFF FC FIFA Men's World Cup 2022 EVENT data (broadcast-tracking derived)",
        "substrate": "event data (betterOptionPlayerId); covers ALL matches -- does NOT use the 44-match tracking cache",
        "matches_covered": n_matches,
        "total_better_option_events": total_bo,
        "coce_tallied_events": tallied_events,
        "self_reference": {
            "definition": (
                "betterOptionPlayerId == the resolved on-ball actorId: the analyst flagged an "
                "action the player should have done HIMSELF (betterOptionType H=header, S=shot, "
                "B/L/P), NOT an ignored OPEN TEAMMATE. There is no betterOptionType codebook in "
                "the repo; the action-code reading is inferred from these self-reference rows."
            ),
            "self_reference_excluded": self_ref_count,
            "tallied_after_self_reference_exclusion_only": total_bo - self_ref_count,
            "tallied_after_all_exclusions": tallied_events,
            "total_label_events": total_bo,
            "events": self_ref_examples,
            "headline_effect": (
                "En-Nesyri had 1 self-reference event (a header he should have taken himself), so "
                "his raw N=8 'most-ignored open man' drops to N=7 NET, tying the existing five-way "
                "N=7 group (Ferran Torres, Bruno Fernandes, Ronaldo, Raum, Mitrovic) -- now a "
                "SIX-way tie at N=7 with NO separable rank-1. Team Morocco drops 27->26; Senegal "
                "(3 self-ref), Poland, Netherlands, Qatar, Denmark each drop their self-ref events "
                "from team tallies. Self-reference rows are kept in `rows` with self_reference=true "
                "and in_tally=false for audit."
            ),
        },
        "cross_team": {
            "definition": (
                "betterOptionPlayerId on the OPPONENT: the on-ball actor's roster team != the "
                "betterOption's roster team (both known). An opponent is NOT 'an ignored open "
                "teammate' -- almost certainly a PFF playerId data-entry slip. The symmetric twin "
                "of the self-reference defect (actor==betterOption). Left in, it (a) mis-credits the "
                "miss to the ignored man's OPPONENT team in team_ignored_open_men and (b) mixes two "
                "attacking orientations in the xt_proxy (the ball belongs to the passer's team, but "
                "the proxy orients the ball to the ignored man's opposing team). EXCLUDED from every "
                "load-bearing tally exactly like self-reference; kept as audit rows with "
                "cross_team=true / in_tally=false."
            ),
            "n_excluded": cross_team_count,
            "events": cross_team_examples,
            "headline_effect": (
                "2 events: game 3848 actor=Andreas Skov Olsen (Denmark) -> betterOption=Mathew Leckie "
                "(Australia); game 3854 actor=Pedri (Spain) -> betterOption=Ayase Ueda (Japan). "
                "Dropping them trims the team boards Australia 7->6 and Japan 16->15 (Japan keeps its "
                "15 genuine Japanese-passer events; Australia keeps its 6 genuine ones, including the "
                "two OTHER genuine Leckie/Duke events in game 3848). coce_tallied_events 510->508. "
                "NO headline leaderboard rank changes (Skov Olsen / Pedri are not top-20 closed-eye; "
                "Australia / Japan are not board leaders). Low-materiality integrity fix."
            ),
        },
        "label_decomposition": {
            "note": (
                "The 518 populated betterOptionPlayerId events broken down by possessionEventType "
                "and self-reference, to show the label is NOT a pure 'ignored open teammate' signal."
            ),
            "by_possession_event_type_all": dict(sorted(label_petype_all.items())),
            "by_possession_event_type_self_reference": dict(sorted(label_petype_selfref.items())),
        },
        "ROBUSTNESS_DISCLAIMER": (
            "After excluding %d self-reference events, %d genuine ignored-open-man events are spread "
            "over %d distinct ignored men and %d distinct passers; the per-player leaderboards are "
            "THIN DESCRIPTIVE TALLIES, NOT a separable ranking. There is NO unique rank-1 on the "
            "Ignored-Creator board: En-Nesyri (N=8 RAW) falls to N=7 NET after the self-reference "
            "drop and joins a SIX-way tie at N=7 (Poisson +/-sqrt(count) band on N=7 is [%.1f, %.1f], "
            "heavily overlapping the N>=4 tail). Do NOT read within-tie order as a finding (see "
            "tie_group on each row). Every leaderboard row carries a ci_lo/ci_hi Poisson interval. "
            "The HARD COUNTS (misses, times-ignored, pressure split) are the load-bearing numbers; "
            "the xt-proxy is a soft secondary signal and at this N is concentration-prone (see "
            "concentration_flag)."
            % (self_ref_count, tallied_events, len(ic_count), len(ce_misses), *poisson_ci(7))
        ),
        "n_distribution": {
            "ignored_creator_times_ignored": ic_n_hist,
            "closed_eye_misses": ce_n_hist,
            "note": ("count -> number of players with that count. The mass is in tiny N: most "
                     "players appear 1-2 times; only a handful reach N>=5, so single-event "
                     "differences dominate the ordering."),
        },
        "value_proxy": {
            "definition": "xt_proxy_left_on_table = staticSinghXT(ignored_open_man_location) - staticSinghXT(actual_ball_location), both oriented so the attacking team attacks +x",
            "DISCLAIMER": "SOFT positional proxy ONLY. NOT calibrated P(score), NOT StatsBomb xG, NOT a model output. A fixed 12x8 Singh (2019) xT grid lookup difference at two points. Directional / exploratory only.",
            "reference_location": "ball snapshot location preferred; actor (passer) position fallback when ball missing",
            "negative_proxy_handling": "xt-proxy aggregates (forgone totals) sum only POSITIVE deltas (ignored spot more dangerous than the ball); the per-row table keeps signed values",
            "concentration_warning": (
                "At this N the xt-proxy boards are concentration-prone: a single large positive "
                "delta can vault a player to #1. Each xt row exposes positive_delta_events (N) and "
                "max_single_delta_share (largest event / total); concentration_flag marks rows that "
                "are effectively single-event (N<%d) or single-event-dominated (share>=0.60). A "
                "'_stable_minN%d' board excludes N<%d rows. Do NOT read the xt-proxy board as a "
                "stable ordering." % (MIN_XT_POS_EVENTS, MIN_XT_POS_EVENTS, MIN_XT_POS_EVENTS)
            ),
        },
        "pressure_split": {
            "definition": "pressureType on the on-ball actor: N=none, P=pressured, A=aggressive, L=lunge",
            "under_pressure_PAL": n_under,
            "in_space_N": n_space,
            "other_or_missing": n_other,
            "interpretation": "in_space (N) misses are DAMNING (no excuse); under_pressure (P/A/L) misses are partly excusable",
            "raw_distribution": dict(pressure_dist),
        },
        "better_option_type_distribution": dict(bo_type_dist),
        "period_distribution": {str(k): v for k, v in period_dist.items()},
        "extra_time_events": et_events,
        "visibility_gate": {
            "field": "homePlayers/awayPlayers[].visibility (ignored man) AND ball[].visibility (reference) at the event snapshot",
            "ignored_man_VISIBLE": vis_dist.get("VISIBLE", 0),
            "ignored_man_ESTIMATED": vis_dist.get("ESTIMATED", 0),
            "ignored_man_NO_POSITION": vis_dist.get("NO_POSITION", 0),
            "ball_VISIBLE": ball_vis_dist.get("VISIBLE", 0),
            "ball_ESTIMATED": ball_est,
            "ball_NO_BALL": ball_vis_dist.get("NO_BALL", 0),
            "denominator": "tallied events (%d) -- visibility counters accrue only on genuine ignored-open-man events, after the %d self-reference events are dropped" % (tallied_events, self_ref_count),
            "ball_estimated_fraction": round(ball_est / tallied_events, 3) if tallied_events else None,
            "BOTH_ENDPOINTS_VISIBLE": joint_visible,
            "both_endpoints_visible_fraction": round(joint_visible / tallied_events, 3) if tallied_events else None,
            "note": (
                "The xt-proxy delta has TWO endpoints (ignored man + ball). Over the %d TALLIED "
                "events: the ignored man is VISIBLE on %d/%d (%.1f%%), but the BALL reference is "
                "ESTIMATED on %d/%d (%.1f%%), so the TRUE both-endpoints-VISIBLE rate is only "
                "%d/%d (%.1f%%). Each xt leaderboard row also carries an xt_proxy_*_both_visible "
                "aggregate (summed over both-endpoints-VISIBLE positive events only); per-row "
                "both_endpoints_visible flags each event."
                % (tallied_events,
                   vis_dist.get("VISIBLE", 0), tallied_events, 100.0 * vis_dist.get("VISIBLE", 0) / tallied_events,
                   ball_est, tallied_events, 100.0 * ball_est / tallied_events,
                   joint_visible, tallied_events, 100.0 * joint_visible / tallied_events)
            ),
        },
        "reference_location_used": dict(ref_used),
        "ignored_man_position_missing": pos_missing,
        "ball_and_actor_both_missing": ball_missing,
        "orientation_unresolved_events": orient_unresolved,
        "xt_proxy_sign": {"positive": xt_proxy_positive, "non_positive": xt_proxy_nonpos},
        "orientation": (
            "GK-DERIVED per (game, period): each team's GK mean x-position fixes attack "
            "direction (GK at -x => that team attacks +x). Robust to homeTeamStartLeft(ExtraTime) "
            "encoding. Verified across all matches: agrees with the metadata odd/even parity rule "
            "on 100%% of NORMAL-TIME periods (P1/P2) and corrects it in EXTRA TIME (the old parity "
            "rule was inverted for P3/P4). E.g. match 10517 home GK mean x = P1 -38.0, P2 +40.2, "
            "P3 +37.2, P4 -40.3 => home attacks P1 +x, P2 -x, P3 -x, P4 +x (the old rule had P3/P4 "
            "flipped). 9 of the %d ET betterOption events had their xt_proxy corrected by this fix."
            % et_events
        ),
        "team_attribution": (
            "team_ignored_open_men attributes a miss to the ignored open man's team. For every "
            "TALLIED event the ignored man IS the passer's teammate -- this is now ENFORCED by the "
            "label-hygiene gates: self-reference (betterOption == actor) and cross-team (betterOption "
            "on the opponent) events are EXCLUDED from all tallies (see meta.self_reference and "
            "meta.cross_team), so the teammate relationship holds for all %d tallied events and the "
            "team attribution is correct. 2 cross-team tags (a Danish passer's miss that would have "
            "been credited to Australia; a Spanish passer's miss to Japan) were removed precisely "
            "because that 'passer's teammate' premise was FALSE for them." % tallied_events
        ),
        "team_exposure_note": (
            "Raw team totals are EXPOSURE-DRIVEN: a team accrues betterOption events simply by "
            "playing more matches, so the raw total correlates with how far the team advanced. "
            "Argentina leads in ABSOLUTE terms (32) but that is driven by reaching the Final "
            "(7 games = 4.57/game); on a per-game basis Germany (29 in 3 games = 9.67/game) tops "
            "the board. Use misses_per_game (team_ignored_open_men_per_game) as the comparable "
            "figure; the raw total is for absolute volume only."
        ),
        "caveats": [
            "xt_proxy is a SOFT Singh-xT-grid positional proxy (difference of two fixed grid lookups), NOT P(score), NOT StatsBomb xG, NOT a model output. Treat all xt-proxy figures as directional/exploratory.",
            "betterOptionPlayerId is NOT purely 'an ignored open teammate': in %d of %d events the flagged better option is the ON-BALL ACTOR HIMSELF (a header/shot/etc. the player should have taken himself, NOT a different open man). Those %d self-reference events are EXCLUDED from every tally. See meta.self_reference and meta.label_decomposition." % (self_ref_count, total_bo, self_ref_count),
            "betterOptionPlayerId is OCCASIONALLY a NON-TEAMMATE (the OPPONENT): in %d of %d events the flagged better option is on the OPPOSING team -- almost certainly a PFF playerId data-entry slip, and an opponent is even more clearly NOT 'an ignored open teammate' than a self-reference is. Left in, these mis-credit the miss to the opponent's team (a Danish passer's miss -> Australia; a Spanish passer's miss -> Japan) and mix two attacking orientations in the xt_proxy. They are EXCLUDED from every tally (cross_team=true / in_tally=false; see meta.cross_team), trimming Australia 7->6 and Japan 16->15. After both gates, %d genuine ignored-open-TEAMMATE events are tallied and the teammate relationship holds for all of them." % (cross_team_count, total_bo, tallied_events),
            "Per-player leaderboards are DESCRIPTIVE TALLIES, not a separable ranking. After the self-reference drop there is NO unique rank-1: En-Nesyri falls from N=8 raw to N=7 net and joins a SIX-way tie at N=7 (overlapping Poisson +/-sqrt(N) bands). ci_lo/ci_hi and tie_group are on every row; do not read within-tie order as a finding.",
            "betterOption tags are sparse (%d total, %d tallied) and analyst-selected, biased toward on-camera high-leverage moments; absolute counts are conservative." % (total_bo, tallied_events),
            "Team totals are exposure-driven (more matches => more events). misses_per_game reorders the board (Germany 9.67/game tops it; Argentina's raw #1 is 4.57/game and reflects reaching the Final).",
            "BOTH endpoints of the xt-proxy delta carry occlusion uncertainty (over the %d tallied events): the ignored man is ESTIMATED on %d/%d AND the ball reference is ESTIMATED on %d/%d (%.1f%%); only %d/%d (%.1f%%) have BOTH endpoints VISIBLE. xt_proxy_*_both_visible aggregates the visibility-gated subset; per-row both_endpoints_visible flags each." % (
                tallied_events, vis_dist.get("ESTIMATED", 0), tallied_events, ball_est, tallied_events,
                100.0 * ball_est / tallied_events, joint_visible, tallied_events, 100.0 * joint_visible / tallied_events),
            "The xt-proxy boards are concentration-prone at this N: one large positive delta can dominate a player's total. positive_delta_events (N) and max_single_delta_share are on each xt row; concentration_flag marks effectively-single-event rows; a _stable_minN%d board excludes them." % MIN_XT_POS_EVENTS,
            "betterOptionPlayerId is a single-source PFF analyst judgement; no second source confirms the 'better option' call.",
            "No PFF<->StatsBomb possession/temporal alignment exists in-repo (only a coarse match-level join), so the metric does NOT credit ensuing-possession xG.",
            "Attack-direction orientation is GK-derived per (game, period), correcting an inverted extra-time parity bug in the prior version (9 of %d ET events affected); verified against GK x-positions across all matches." % et_events,
        ],
    }

    out = {
        "meta": meta,
        "leaderboards": leaderboards,
        "rows": rows,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    # ---- console summary ----
    print("CoCE -- Cost of the Closed Eye")
    print("Matches covered: %d | betterOption label events: %d | self-reference dropped: %d | cross-team dropped: %d | tallied: %d | ET events: %d"
          % (n_matches, total_bo, self_ref_count, cross_team_count, tallied_events, et_events))
    print("Self-reference (betterOption == actor) excluded:", [e["player"] + "(" + str(e["better_option_type"]) + ")" for e in self_ref_examples])
    print("Cross-team (betterOption on OPPONENT) excluded:", [e["actor"] + "(" + e["actor_team"] + ")->" + e["ignored_man"] + "(" + e["ignored_man_team"] + ")" for e in cross_team_examples])
    print("Pressure split (tallied): under_pressure(P/A/L)=%d | in_space(N)=%d | other=%d"
          % (n_under, n_space, n_other))
    print("Ignored-man visibility: VISIBLE=%d ESTIMATED=%d NO_POSITION=%d"
          % (vis_dist.get("VISIBLE", 0), vis_dist.get("ESTIMATED", 0), vis_dist.get("NO_POSITION", 0)))
    print("Ball visibility:        VISIBLE=%d ESTIMATED=%d NO_BALL=%d (ball ESTIMATED frac=%.3f)"
          % (ball_vis_dist.get("VISIBLE", 0), ball_est, ball_vis_dist.get("NO_BALL", 0),
             ball_est / tallied_events))
    print("JOINT both-endpoints VISIBLE: %d/%d (%.1f%%)"
          % (joint_visible, tallied_events, 100.0 * joint_visible / tallied_events))
    print("xt-proxy reference used:", dict(ref_used), "| positive deltas:", xt_proxy_positive,
          "| orient_unresolved:", orient_unresolved)
    print("Wrote", OUT_PATH)
    print()

    print("== IGNORED CREATOR (most-ignored open men) -- DESCRIPTIVE, not separable ==")
    for i, r in enumerate(leaderboards["ignored_creator_by_times_ignored"][:12], 1):
        print("  %2d. %-22s %-12s ignored=%d [%.1f-%.1f] tie=%d (space=%d, pressured=%d)"
              % (i, r["player"], r["team"], r["times_ignored"], r["ci_lo"], r["ci_hi"],
                 r["tie_group"], r["ignored_in_space_N"], r["ignored_under_pressure_PAL"]))
    print()
    print("== CLOSED EYE (most misses) -- DESCRIPTIVE, not separable ==")
    for i, r in enumerate(leaderboards["closed_eye_by_misses"][:12], 1):
        print("  %2d. %-22s %-12s misses=%d [%.1f-%.1f] tie=%d (space=%d, pressured=%d)"
              % (i, r["player"], r["team"], r["misses"], r["ci_lo"], r["ci_hi"], r["tie_group"],
                 r["misses_in_space_N"], r["misses_under_pressure_PAL"]))
    print()
    print("== CLOSED EYE by xT-proxy forgone (SOFT proxy, concentration-prone) ==")
    for i, r in enumerate(leaderboards["closed_eye_by_xt_proxy_forgone"][:8], 1):
        print("  %2d. %-22s %-12s xt=%.4f (visOnly=%.4f) posN=%d maxShare=%s %s"
              % (i, r["player"], r["team"], r["xt_proxy_forgone_total"],
                 r["xt_proxy_forgone_both_visible"], r["positive_delta_events"],
                 r["max_single_delta_share"], "<<concentrated" if r["concentration_flag"] else ""))
    print()
    print("== CLOSED EYE by xT-proxy, STABLE view (posN>=%d) ==" % MIN_XT_POS_EVENTS)
    for i, r in enumerate(leaderboards["closed_eye_by_xt_proxy_forgone_stable_minN%d" % MIN_XT_POS_EVENTS][:8], 1):
        print("  %2d. %-22s %-12s xt=%.4f posN=%d maxShare=%s"
              % (i, r["player"], r["team"], r["xt_proxy_forgone_total"],
                 r["positive_delta_events"], r["max_single_delta_share"]))
    print()
    print("== TEAM ignored open men (RAW -- exposure-driven) ==")
    for i, r in enumerate(leaderboards["team_ignored_open_men"][:8], 1):
        print("  %2d. %-14s misses=%d [%.1f-%.1f] games=%d perGame=%.2f"
              % (i, r["team"], r["misses"], r["ci_lo"], r["ci_hi"],
                 r["games_played"], r["misses_per_game"]))
    print()
    print("== TEAM ignored open men (PER-GAME -- comparable) ==")
    for i, r in enumerate(leaderboards["team_ignored_open_men_per_game"][:8], 1):
        print("  %2d. %-14s perGame=%.2f (misses=%d in %d games)"
              % (i, r["team"], r["misses_per_game"], r["misses"], r["games_played"]))


if __name__ == "__main__":
    main()
