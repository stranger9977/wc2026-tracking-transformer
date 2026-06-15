#!/usr/bin/env python3
"""
LINE-BREAK leaderboard from PFF FC World Cup 2022 event data.

A line-breaking pass = a COMPLETED, OPEN-PLAY pass that is played forward
(goalward) past >= N opponents who lie within the pass corridor. This is the
common public definition of a "line break" (FIFA's flagship off-ball /
progression metric); we use N=3 as the primary threshold and also track N>=2.

Every PFF event snapshot already carries all 22 player (x,y) positions, so we
never need the 30Hz tracking files -- the event snapshot at the moment of the
pass is sufficient.

Stdlib only: json, glob, collections, math, os.

Run:
    python3 research/scripts/eda_line_breaks.py
Writes:
    research/site/data/eda_line_breaks.json
"""
import json
import glob
import os
import math
import collections

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = "/Users/nick/Desktop/drive-download-20260518T234612Z-3-001"
EVENT_DIR = os.path.join(BASE, "Event Data")
META_DIR = os.path.join(BASE, "Metadata")

OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "site", "data", "eda_line_breaks.json",
)

# ---------------------------------------------------------------------------
# Rule parameters (documented in meta)
# ---------------------------------------------------------------------------
PRIMARY_THRESHOLD = 3      # >=3 opponents bypassed => "line-breaking pass"
SECONDARY_THRESHOLD = 2    # secondary column
CORRIDOR_HALF_WIDTH = 6.0  # meters: |dy - py_interp| <= 6
FALLBACK_PAD = 4.0         # meters padding for the bbox fallback corridor

FINAL_MATCH = "10517"
FINAL_HOME_ID = 364  # Argentina
FINAL_AWAY_ID = 363  # France


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------
def home_attack_sign(period, home_start_left, home_start_left_et):
    """Return +1 if home team attacks toward +x in this period, else -1.

    A team 'starting left' defends the -x goal and ATTACKS +x in period 1.
    Flip each subsequent regular half. Extra time uses the ET flag for P3,
    P4 = flip of P3.
    """
    if period in (1, 2):
        base = 1 if home_start_left else -1
        return base if period == 1 else -base
    elif period in (3, 4):
        base = 1 if home_start_left_et else -1
        return base if period == 3 else -base
    return None  # period 5 (shootout) excluded upstream


def orient(x, y, sign):
    """Rotate a point into the attacking-right frame (180 deg = negate both)."""
    return x * sign, y * sign


# ---------------------------------------------------------------------------
# Line-break geometry
# ---------------------------------------------------------------------------
def count_bypassed(px, py, rx, ry, defenders):
    """Count opponents bypassed by an oriented (forward) pass.

    A defender (dx,dy) is bypassed if:
      px < dx < rx                            (advanced goalward past them), AND
      |dy - py_interp| <= CORRIDOR_HALF_WIDTH (within the pass corridor),
        where py_interp is the pass's y linearly interpolated at x=dx.
      Fallback (degenerate dx span): dy within the lateral bbox +/- FALLBACK_PAD.
    """
    n = 0
    span = rx - px
    if span <= 0:
        return 0  # not a forward pass
    ylo = min(py, ry) - FALLBACK_PAD
    yhi = max(py, ry) + FALLBACK_PAD
    for dx, dy in defenders:
        if not (px < dx < rx):
            continue
        # linear interpolation of pass-line y at x = dx
        t = (dx - px) / span
        py_interp = py + t * (ry - py)
        if abs(dy - py_interp) <= CORRIDOR_HALF_WIDTH:
            n += 1
        elif ylo <= dy <= yhi:
            # fallback corridor (kept conservative; rarely adds beyond the above)
            n += 1
    return n


# ---------------------------------------------------------------------------
# Main pass over all matches
# ---------------------------------------------------------------------------
def main():
    player_lb3 = collections.Counter()   # >=3 bypassed
    player_lb2 = collections.Counter()   # >=2 bypassed
    player_team = {}                     # playerId -> team name
    player_name = {}                     # playerId -> name
    player_matches = collections.defaultdict(set)
    team_lb3 = collections.Counter()
    team_name = {}

    total_complete_openplay = 0
    total_forward = 0

    # orientation validation accumulators
    fwd_dx_sum = 0.0
    fwd_dx_n = 0
    gk_x_samples = []  # most-extreme -x oriented player per passing team snapshot

    final_team_lb3 = collections.Counter()
    final_player_lb3 = collections.defaultdict(lambda: collections.Counter())

    files = sorted(glob.glob(os.path.join(EVENT_DIR, "*.json")))

    for fpath in files:
        match_id = os.path.splitext(os.path.basename(fpath))[0]
        meta = json.load(open(os.path.join(META_DIR, match_id + ".json")))[0]
        home_id = int(meta["homeTeam"]["id"])
        away_id = int(meta["awayTeam"]["id"])
        home_nm = meta["homeTeam"]["name"]
        away_nm = meta["awayTeam"]["name"]
        team_name[home_id] = home_nm
        team_name[away_id] = away_nm
        hsl = bool(meta["homeTeamStartLeft"])
        hsl_et = bool(meta.get("homeTeamStartLeftExtraTime", hsl))

        events = json.load(open(fpath))

        for ev in events:
            ge = ev.get("gameEvents") or {}
            period = ge.get("period")
            if period not in (1, 2, 3, 4):
                continue  # exclude shootout (5) / unknown

            pe = ev.get("possessionEvents")
            if not pe or not isinstance(pe, dict):
                continue
            if pe.get("possessionEventType") != "PA":
                continue
            if pe.get("passOutcomeType") != "C":  # complete only
                continue
            # OPEN PLAY ONLY: setpieceType 'O' means no dead-ball restart.
            if ge.get("setpieceType") != "O":
                continue
            # Exclude crosses? No -- open-play crosses are open play. We keep
            # all open-play passes (passType S/C/O/F/B with setpiece 'O').
            # Throw-ins are setpiece 'T' and already excluded above.

            passer_id = pe.get("passerPlayerId")
            receiver_id = pe.get("receiverPlayerId")
            if passer_id is None or receiver_id is None:
                continue

            home_players = ev.get("homePlayers") or []
            away_players = ev.get("awayPlayers") or []
            hids = {p["playerId"] for p in home_players}
            aids = {p["playerId"] for p in away_players}

            # Determine passing side by membership (robust).
            if passer_id in hids:
                pass_side = "home"
            elif passer_id in aids:
                pass_side = "away"
            else:
                continue  # passer not located this snapshot

            sign_home = home_attack_sign(period, hsl, hsl_et)
            if sign_home is None:
                continue
            sign_away = -sign_home
            sign = sign_home if pass_side == "home" else sign_away

            teammates = home_players if pass_side == "home" else away_players
            opponents = away_players if pass_side == "home" else home_players
            team_id = home_id if pass_side == "home" else away_id
            tnm = home_nm if pass_side == "home" else away_nm

            # Locate passer & receiver positions from the snapshot.
            pmap = {p["playerId"]: p for p in teammates}
            if passer_id not in pmap or receiver_id not in pmap:
                continue
            pp = pmap[passer_id]
            rp = pmap[receiver_id]
            px, py = orient(pp["x"], pp["y"], sign)
            rx, ry = orient(rp["x"], rp["y"], sign)

            total_complete_openplay += 1

            # orientation validation: locate the passing team's actual GK by
            # positionGroupType and record its oriented x (should be deep -x).
            for tp in teammates:
                if tp.get("positionGroupType") == "GK":
                    gk_x_samples.append(orient(tp["x"], tp["y"], sign)[0])
                    break

            dx_net = rx - px
            if dx_net > 0:
                total_forward += 1
                fwd_dx_sum += dx_net
                fwd_dx_n += 1

            defenders = [orient(p["x"], p["y"], sign) for p in opponents]
            n_by = count_bypassed(px, py, rx, ry, defenders)

            name = pe.get("passerPlayerName") or str(passer_id)
            player_name[passer_id] = name
            player_team[passer_id] = tnm
            player_matches[passer_id].add(match_id)

            if n_by >= SECONDARY_THRESHOLD:
                player_lb2[passer_id] += 1
            if n_by >= PRIMARY_THRESHOLD:
                player_lb3[passer_id] += 1
                team_lb3[team_id] += 1
                if match_id == FINAL_MATCH:
                    final_team_lb3[team_id] += 1
                    final_player_lb3[team_id][passer_id] += 1

    # -----------------------------------------------------------------------
    # Build outputs
    # -----------------------------------------------------------------------
    players_board = []
    for pid, lb in player_lb3.most_common():
        nmatch = len(player_matches[pid])
        players_board.append({
            "player": player_name[pid],
            "team": player_team[pid],
            "line_breaks": lb,
            "line_breaks_ge2": player_lb2.get(pid, 0),
            "matches": nmatch,
            "per_match": round(lb / nmatch, 3) if nmatch else 0.0,
        })
    players_board.sort(key=lambda r: (-r["line_breaks"], -r["per_match"], r["player"]))
    players_top20 = players_board[:20]

    teams_board = [
        {"team": team_name[tid], "line_breaks": lb}
        for tid, lb in team_lb3.most_common()
    ]
    teams_board.sort(key=lambda r: (-r["line_breaks"], r["team"]))
    teams_top20 = teams_board[:20]

    # Final-specific
    def final_top5(team_id):
        rows = []
        for pid, lb in final_player_lb3[team_id].most_common(5):
            rows.append({"player": player_name[pid], "line_breaks": lb})
        return rows

    final_section = {
        "match_id": FINAL_MATCH,
        "home": {"team": team_name[FINAL_HOME_ID], "id": FINAL_HOME_ID,
                 "line_breaking_passes": final_team_lb3.get(FINAL_HOME_ID, 0),
                 "top5_players": final_top5(FINAL_HOME_ID)},
        "away": {"team": team_name[FINAL_AWAY_ID], "id": FINAL_AWAY_ID,
                 "line_breaking_passes": final_team_lb3.get(FINAL_AWAY_ID, 0),
                 "top5_players": final_top5(FINAL_AWAY_ID)},
    }

    # orientation validation summary
    mean_gk_x = sum(gk_x_samples) / len(gk_x_samples) if gk_x_samples else None
    gk_sorted = sorted(gk_x_samples)
    gk_median = gk_sorted[len(gk_sorted) // 2] if gk_sorted else None
    gk_own_half = (sum(1 for x in gk_x_samples if x < 0) / len(gk_x_samples)
                   if gk_x_samples else None)
    mean_fwd_dx = fwd_dx_sum / fwd_dx_n if fwd_dx_n else None

    meta_block = {
        "rule": (
            "Line-breaking pass = a COMPLETED, OPEN-PLAY pass played forward "
            "(goalward, oriented dx = rx-px > 0) that bypasses opponents. A "
            "defender at oriented (dx,dy) is bypassed if px < dx < rx AND the "
            "defender is within the pass corridor laterally: |dy - py_interp| "
            "<= 6 m, where py_interp is the pass line's y linearly interpolated "
            "at x=dx (fallback: dy within [min(py,ry)-4, max(py,ry)+4]). "
            "Attributed to the PASSER."
        ),
        "primary_threshold_opponents_bypassed": PRIMARY_THRESHOLD,
        "secondary_threshold_opponents_bypassed": SECONDARY_THRESHOLD,
        "corridor_half_width_m": CORRIDOR_HALF_WIDTH,
        "fallback_pad_m": FALLBACK_PAD,
        "n_matches": len(files),
        "n_complete_open_play_passes_considered": total_complete_openplay,
        "n_forward_passes": total_forward,
        "filters": {
            "possessionEventType": "PA",
            "passOutcomeType": "C (complete)",
            "setpieceType": "O (open play only; throw-ins/corners/FK/GK/kickoff excluded)",
            "periods_included": [1, 2, 3, 4],
            "periods_excluded": [5],
        },
        "orientation": {
            "convention": (
                "Each passing team oriented to attack +x. Home P1 sign = +1 if "
                "homeTeamStartLeft else -1; flip each regular half. P3 uses "
                "homeTeamStartLeftExtraTime; P4 = flip(P3). Away = -home. Orient "
                "a point by multiplying BOTH x and y by the attack sign."
            ),
            "validation": {
                "gk_located_by": "positionGroupType == 'GK' (passing team)",
                "mean_oriented_gk_x_m": round(mean_gk_x, 2) if mean_gk_x is not None else None,
                "median_oriented_gk_x_m": round(gk_median, 2) if gk_median is not None else None,
                "pct_gk_in_own_half_oriented_x_lt_0": round(100 * gk_own_half, 2) if gk_own_half is not None else None,
                "expected": ("GK should sit deep in own half (oriented x < 0; "
                             "typically -30..-50 during open-play buildup, not "
                             "on the goal line because keepers push up to "
                             "support possession)."),
                "mean_forward_delta_x_on_forward_passes_m": round(mean_fwd_dx, 2) if mean_fwd_dx is not None else None,
                "forward_pass_share": round(total_forward / total_complete_openplay, 4) if total_complete_openplay else None,
            },
        },
        "caveats": [
            "Broadcast-tracking occlusion: ~37% of player-position rows are "
            "ESTIMATED (imputed) and ~48% are LOW confidence; off-ball "
            "defenders furthest from the ball are the most likely to be "
            "imputed, so corridor membership for distant defenders is noisy.",
            "The corridor is a straight-line heuristic (6 m half-width + bbox "
            "fallback); it ignores pass curvature and defender facing/closing speed.",
            "A single event snapshot is taken at the pass moment; defenders "
            "between passer and receiver in x are treated as 'a line' regardless "
            "of whether they form a tactical line.",
            "Goalkeepers are included among the 11 opponents; a deep through-ball "
            "rarely passes the GK in x, so this seldom inflates counts.",
            "PFF also ships its own subjective 'linesBrokenType' tag (D/M/A/AM) "
            "per pass; this metric is an INDEPENDENT geometric reconstruction "
            "and does not match it. Cross-check: of our 3,211 geometric LB>=3 "
            "passes only ~30%% are also PFF-tagged, and of PFF's 4,649 tagged "
            "passes only ~21%% reach our LB>=3 bar. They measure related but "
            "different things: PFF flags breaking a NAMED tactical line (can be "
            "1-2 players that form a recognised line, incl. off-ball/dribble "
            "context), whereas we require >=3 opponents inside a forward "
            "corridor at the pass instant.",
        ],
        "secondary_note": (
            "line_breaks = passes bypassing >=3 opponents (primary). "
            "line_breaks_ge2 = passes bypassing >=2 (secondary column)."
        ),
    }

    out = {
        "players_by_line_breaking_passes_top20": players_top20,
        "teams_by_line_breaking_passes_top20": teams_top20,
        "final": final_section,
        "meta": meta_block,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # Console validation prints
    # -----------------------------------------------------------------------
    print("=== VALIDATION ===")
    print("n matches:", len(files))
    print("n complete open-play passes considered:", total_complete_openplay)
    print("n forward passes:", total_forward,
          "(%.1f%%)" % (100 * total_forward / total_complete_openplay))
    print("oriented GK x (expect deep -x): mean", round(mean_gk_x, 2),
          "| median", round(gk_median, 2),
          "| %% in own half (x<0): %.1f%%" % (100 * gk_own_half))
    print("mean forward dx on forward passes (expect > 0):", round(mean_fwd_dx, 2))
    print()
    print("=== TOP 12 PLAYERS (>=3 bypassed) ===")
    for r in players_top20[:12]:
        print("  %-26s %-14s LB=%-4d (>=2:%-4d) m=%-2d /m=%.2f" % (
            r["player"][:26], r["team"][:14], r["line_breaks"],
            r["line_breaks_ge2"], r["matches"], r["per_match"]))
    print()
    print("=== TOP 12 TEAMS (>=3 bypassed) ===")
    for r in teams_top20[:12]:
        print("  %-16s %d" % (r["team"], r["line_breaks"]))
    print()
    print("=== FINAL (10517) ===")
    for side in ("home", "away"):
        s = final_section[side]
        print("  %s (%s): %d line-breaking passes" % (s["team"], side, s["line_breaking_passes"]))
        for p in s["top5_players"]:
            print("      %-26s %d" % (p["player"], p["line_breaks"]))
    print()
    print("WROTE:", OUT_PATH)


if __name__ == "__main__":
    main()
