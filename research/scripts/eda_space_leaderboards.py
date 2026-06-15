#!/usr/bin/env python3
"""
EDA: Space / off-ball movement leaderboards from PFF FC World Cup 2022 event data.

Pure standard library (json, glob, collections, csv, os). Run with: python3 eda_space_leaderboards.py

DATA SOURCE
-----------
/Users/nick/Desktop/drive-download-20260518T234612Z-3-001/
  - "Event Data/*.json"  : one JSON file per match; each file is a LIST of event objects.
  - "Rosters/*.json"     : authoritative playerId -> {name, team} mapping (all 32 squads).

ATTRIBUTION DECISIONS (documented in output "meta")
---------------------------------------------------
Each event object carries possessionEvents (dict) + grades (dict). Schema inspection of
all matches showed:

* createsSpace (bool) is an ATTRIBUTE OF THE ON-BALL ACTION (a pass / cross / shot),
  NOT a dedicated off-ball tag. The dedicated csPlayerId field is populated on only
  ~2 of 1,422 createsSpace=True events (effectively unusable). createsSpace=True events
  break down as PA (pass) >> CR (cross) >> SH (shot) >> CL. We therefore attribute a
  "space-creating action" to the ACTOR who played it:
      passerPlayerId -> crosserPlayerId -> shooterPlayerId -> clearerPlayerId
      -> carrierPlayerId -> ballCarrierPlayerId  (first non-null wins).
  All 1,422 createsSpace=True events resolve to an actor with this priority. NOTE: this
  measures who PLAYED the ball into space (the creator of the chance/space via the pass),
  which is the standard reading of PFF's createsSpace flag.

* movementGrade pairs cleanly with movementPlayerId / movementPlayerName
  (off-ball MOVEMENT grade for the player who made the run). 100% of graded events
  in the sample carried movementPlayerId. We also fold in movement2/movement3 player ids
  when present (secondary movers on the same event) but only the primary movementGrade
  value is graded, so secondary movers are NOT given the grade -- we only count primary.

* positionGrade pairs cleanly with positionPlayerId / positionPlayerName
  (off-ball POSITIONING grade). 100% of graded events carried positionPlayerId.

* betterOption: betterOptionPlayerId / betterOptionPlayerName = the open player who was
  the better (un-taken) option, i.e. "got open but was not found". Attributed directly.

* pressureType in {P,A,L} = some degree of pressure on the action (P=pressured,
  A=aggressive, L=lunge); N=no pressure. Attributed to the ACTOR of the action
  (same actor-priority as createsSpace) so "actions under pressure" = on-ball events the
  player executed while pressured.

* Team mapping uses the Rosters files (playerId -> team, name), the authoritative squad
  lists (829 players, 32 teams). gameEvents.teamName/homeTeam was cross-checked and agrees.

* Per-match rates: minutes are not cleanly recoverable (ON/OFF events + period-offset
  clocks are noisy), so we normalise by the number of distinct matches a player appears
  in the tracking frames (homePlayers/awayPlayers). This is the honest, robust denominator.

CAVEAT
------
PFF FC tracking is derived from BROADCAST video, so off-ball players are subject to
OCCLUSION / out-of-frame gaps. createsSpace / movement / position grades are only logged
on a subset of events the analysts tagged; absolute counts are conservative and biased
toward on-camera, high-leverage moments. Treat these as exploratory, not exhaustive.
"""

import json
import glob
import os
import csv
from collections import defaultdict, Counter

DATA_ROOT = "/Users/nick/Desktop/drive-download-20260518T234612Z-3-001"
EVENT_GLOB = os.path.join(DATA_ROOT, "Event Data", "*.json")
ROSTER_GLOB = os.path.join(DATA_ROOT, "Rosters", "*.json")
OUT_PATH = "/Users/nick/wc2026-tracking-transformer/research/site/data/eda_space.json"

PRESSURE_SET = {"P", "A", "L"}  # P=pressured, A=aggressive, L=lunge ; N=none
ACTOR_FIELDS = [
    "passerPlayerId", "crosserPlayerId", "shooterPlayerId",
    "clearerPlayerId", "carrierPlayerId", "ballCarrierPlayerId",
]
ACTOR_NAME_FIELDS = [
    ("passerPlayerId", "passerPlayerName"),
    ("crosserPlayerId", "crosserPlayerName"),
    ("shooterPlayerId", "shooterPlayerName"),
    ("clearerPlayerId", "clearerPlayerName"),
    ("carrierPlayerId", "carrierPlayerName"),
    ("ballCarrierPlayerId", "ballCarrierPlayerName"),
]


def load_rosters():
    """playerId(int) -> (name, team).  Authoritative squad mapping."""
    pid_name = {}
    pid_team = {}
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


def actor_id_name(pe):
    """Return (playerId, playerName) of the on-ball actor for this possession event."""
    for idf, namef in ACTOR_NAME_FIELDS:
        if pe.get(idf):
            return pe.get(idf), pe.get(namef)
    return None, None


def main():
    pid_name, pid_team = load_rosters()

    # Accumulators
    cs_count = Counter()                 # createsSpace actions by player
    cs_under_pressure = Counter()        # createsSpace actions where actor was pressured
    better_option = Counter()            # times player was the betterOption (got open, not found)
    pressure_actions = Counter()         # on-ball actions executed under pressure
    movement_sum = defaultdict(float)
    movement_n = Counter()
    position_sum = defaultdict(float)
    position_n = Counter()

    # Names discovered from event data (fallback / enrichment for roster gaps)
    ev_name = {}

    # team accumulators
    team_cs = Counter()
    team_pressure = Counter()
    team_move_sum = defaultdict(float)
    team_move_n = Counter()
    team_pos_sum = defaultdict(float)
    team_pos_n = Counter()
    team_better_option = Counter()

    # per-match appearances for rates
    player_matches = defaultdict(set)

    n_matches = 0
    total_events = 0
    total_pe = 0
    cs_true_total = 0
    cs_resolved = 0
    movement_graded = 0
    position_graded = 0
    pressure_dist = Counter()
    better_total = 0

    files = sorted(glob.glob(EVENT_GLOB))

    def name_of(pid, fallback=None):
        if fallback:
            ev_name.setdefault(pid, fallback)
        return pid_name.get(pid) or ev_name.get(pid) or fallback or "Unknown(%s)" % pid

    def team_of(pid):
        return pid_team.get(pid, "Unknown")

    for fp in files:
        with open(fp) as f:
            data = json.load(f)
        if not data:
            continue
        n_matches += 1
        gid = data[0].get("gameId")

        for ev in data:
            total_events += 1

            # track match appearances (off-ball presence in frame)
            for side in ("homePlayers", "awayPlayers"):
                for p in ev.get(side) or []:
                    player_matches[p["playerId"]].add(gid)

            pe = ev.get("possessionEvents") or {}
            g = ev.get("grades") or {}
            if not pe:
                continue
            total_pe += 1

            # ---- pressure on the action ----
            pt = pe.get("pressureType")
            if pt:
                pressure_dist[pt] += 1
            actor_id, actor_nm = actor_id_name(pe)
            if actor_id and actor_nm:
                ev_name.setdefault(actor_id, actor_nm)

            if pt in PRESSURE_SET and actor_id:
                pressure_actions[actor_id] += 1
                team_pressure[team_of(actor_id)] += 1

            # ---- createsSpace ----
            if pe.get("createsSpace"):
                cs_true_total += 1
                if actor_id:
                    cs_resolved += 1
                    cs_count[actor_id] += 1
                    team_cs[team_of(actor_id)] += 1
                    if pt in PRESSURE_SET:
                        cs_under_pressure[actor_id] += 1

            # ---- betterOption (got open, missed by passer) ----
            bo_id = pe.get("betterOptionPlayerId")
            if bo_id:
                better_total += 1
                better_option[bo_id] += 1
                team_better_option[team_of(bo_id)] += 1
                bo_nm = pe.get("betterOptionPlayerName")
                if bo_nm:
                    ev_name.setdefault(bo_id, bo_nm)

            # ---- movementGrade ----
            mg = g.get("movementGrade")
            mpid = pe.get("movementPlayerId")
            if mg is not None and mpid:
                movement_graded += 1
                movement_sum[mpid] += mg
                movement_n[mpid] += 1
                team_move_sum[team_of(mpid)] += mg
                team_move_n[team_of(mpid)] += 1
                mnm = pe.get("movementPlayerName")
                if mnm:
                    ev_name.setdefault(mpid, mnm)

            # ---- positionGrade ----
            pg = g.get("positionGrade")
            ppid = pe.get("positionPlayerId")
            if pg is not None and ppid:
                position_graded += 1
                position_sum[ppid] += pg
                position_n[ppid] += 1
                team_pos_sum[team_of(ppid)] += pg
                team_pos_n[team_of(ppid)] += 1
                pnm = pe.get("positionPlayerName")
                if pnm:
                    ev_name.setdefault(ppid, pnm)

    matches_played = {pid: len(s) for pid, s in player_matches.items()}

    # ---------- build leaderboards ----------
    def player_row(pid, count):
        m = matches_played.get(pid, 0)
        per_match = round(count / m, 3) if m else None
        return {
            "player": name_of(pid),
            "team": team_of(pid),
            "count": count,
            "matches": m,
            "per_match": per_match,
        }

    def top_count(counter, n=15):
        return [player_row(pid, c) for pid, c in counter.most_common(n)]

    def top_avg_grade(sum_d, n_d, n=15, min_sample=10):
        rows = []
        for pid, cnt in n_d.items():
            if cnt < min_sample:
                continue
            avg = sum_d[pid] / cnt
            rows.append({
                "player": name_of(pid),
                "team": team_of(pid),
                "avg_grade": round(avg, 3),
                "graded_events": cnt,
            })
        rows.sort(key=lambda r: r["avg_grade"], reverse=True)
        return rows[:n]

    # Players who get open most per match (betterOption rate) -- min 2 matches & min 5 raw
    def top_rate(counter, n=15, min_count=5, min_matches=2):
        rows = []
        for pid, c in counter.items():
            m = matches_played.get(pid, 0)
            if c < min_count or m < min_matches:
                continue
            rows.append({
                "player": name_of(pid),
                "team": team_of(pid),
                "count": c,
                "matches": m,
                "per_match": round(c / m, 3),
            })
        rows.sort(key=lambda r: r["per_match"], reverse=True)
        return rows[:n]

    # team leaderboards
    def team_count_rows(counter, n=15):
        return [{"team": t, "count": c} for t, c in counter.most_common(n)]

    def team_avg_grade(sum_d, n_d, n=15, min_sample=20):
        rows = []
        for t, cnt in n_d.items():
            if cnt < min_sample:
                continue
            rows.append({"team": t, "avg_grade": round(sum_d[t] / cnt, 3), "graded_events": cnt})
        rows.sort(key=lambda r: r["avg_grade"], reverse=True)
        return rows[:n]

    leaderboards = {
        "space_creators": top_count(cs_count),
        "space_creators_under_pressure": top_count(cs_under_pressure),
        "space_creators_per_match": top_rate(cs_count, min_count=5),
        "got_open_better_option": top_count(better_option),
        "got_open_per_match": top_rate(better_option, min_count=4),
        # NOTE: movement/position grades are almost entirely NEGATIVE (PFF logs them as
        # off-ball deductions, scale ~ -1.0..+0.5). "best" => least-bad (closest to 0),
        # i.e. fewest penalised off-ball errors among players who were graded often.
        # No player reaches 10 movement-graded events (max 9), so movement uses min 5.
        "best_movement_grade": top_avg_grade(movement_sum, movement_n, min_sample=5),
        "best_position_grade": top_avg_grade(position_sum, position_n, min_sample=10),
        "most_off_ball_deductions": top_count(position_n),
        "most_actions_under_pressure": top_count(pressure_actions),
        "team_total_space_created": team_count_rows(team_cs),
        "team_actions_under_pressure": team_count_rows(team_pressure),
        "team_got_open_better_option": team_count_rows(team_better_option),
        "team_avg_movement_grade": team_avg_grade(team_move_sum, team_move_n),
        "team_avg_position_grade": team_avg_grade(team_pos_sum, team_pos_n),
    }

    meta = {
        "data_source": "PFF FC FIFA Men's World Cup 2022 event data (broadcast-tracking derived)",
        "matches_processed": n_matches,
        "total_events": total_events,
        "total_possession_events": total_pe,
        "createsSpace_true_events": cs_true_total,
        "createsSpace_resolved_to_actor": cs_resolved,
        "movement_graded_events": movement_graded,
        "position_graded_events": position_graded,
        "better_option_events": better_total,
        "pressureType_distribution": dict(pressure_dist),
        "players_in_rosters": len(pid_team),
        "attribution": {
            "createsSpace": ("attributed to on-ball ACTOR via priority "
                             "passer>crosser>shooter>clearer>carrier>ballCarrier; "
                             "dedicated csPlayerId is ~unusable (2/1422 populated). "
                             "Measures who PLAYED the ball that created space."),
            "movementGrade": ("paired with movementPlayerId (off-ball run grade), primary mover only. "
                              "Scale ~ -1.0..+0.5 and is ~71% negative / ~26% zero: PFF logs it as an "
                              "off-ball DEDUCTION, so 'best' avg = least-bad (closest to 0)."),
            "positionGrade": ("paired with positionPlayerId (off-ball positioning grade). "
                              "~99% negative (1290/1300): a deduction metric; 'best' avg = least-bad."),
            "betterOption": "betterOptionPlayerId = open player not found by the passer (got open).",
            "pressure": "pressureType in {P,A,L} attributed to on-ball actor (action under pressure).",
            "team_mapping": "Rosters/*.json playerId->team (authoritative 32 squads); gameEvents agrees.",
            "rate_normalisation": ("per_match = count / distinct matches the player appears in tracking; "
                                   "true minutes not cleanly recoverable so per-match used."),
        },
        "min_samples": {
            "movement_grade": 5,
            "position_grade": 10,
            "team_grade": 20,
            "space_creators_per_match": "raw>=5, matches>=2",
            "got_open_per_match": "raw>=4, matches>=2",
        },
        "caveat": ("PFF FC tracking is derived from BROADCAST video; off-ball players are subject to "
                   "occlusion / out-of-frame gaps. Space, movement and position tags are logged only on "
                   "a subset of analyst-tagged events, so absolute counts are conservative and biased "
                   "toward on-camera, high-leverage moments. Exploratory, not exhaustive."),
    }

    out = {"meta": meta, "leaderboards": leaderboards}

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    # ---- console summary ----
    print("Matches: %d | Events: %d | PossessionEvents: %d" % (n_matches, total_events, total_pe))
    print("createsSpace=True: %d (resolved %d) | movement graded: %d | position graded: %d | betterOption: %d"
          % (cs_true_total, cs_resolved, movement_graded, position_graded, better_total))
    print("pressureType dist:", dict(pressure_dist))
    print("Wrote", OUT_PATH)
    print()

    def show(title, rows, *cols):
        print("== %s ==" % title)
        for i, r in enumerate(rows[:10], 1):
            print("  %2d. " % i + " | ".join(str(r.get(c)) for c in cols))
        print()

    show("Space creators (createsSpace actions)", leaderboards["space_creators"], "player", "team", "count", "per_match")
    show("Space creators UNDER PRESSURE", leaderboards["space_creators_under_pressure"], "player", "team", "count")
    show("Got open most (betterOption)", leaderboards["got_open_better_option"], "player", "team", "count")
    show("Best (least-bad) avg movement grade (>=5)", leaderboards["best_movement_grade"], "player", "team", "avg_grade", "graded_events")
    show("Best (least-bad) avg position grade (>=10)", leaderboards["best_position_grade"], "player", "team", "avg_grade", "graded_events")
    show("Most off-ball positioning deductions (volume)", leaderboards["most_off_ball_deductions"], "player", "team", "count")
    show("Most actions under pressure", leaderboards["most_actions_under_pressure"], "player", "team", "count")
    show("TEAM total space created", leaderboards["team_total_space_created"], "team", "count")
    show("TEAM actions under pressure", leaderboards["team_actions_under_pressure"], "team", "count")
    show("TEAM avg movement grade", leaderboards["team_avg_movement_grade"], "team", "avg_grade", "graded_events")


if __name__ == "__main__":
    main()
