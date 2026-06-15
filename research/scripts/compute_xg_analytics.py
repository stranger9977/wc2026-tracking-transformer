"""
Compute REAL xG analytics from StatsBomb open-data (WC2022) for the soccer Space project.

Outputs:
  research/site/data/eda_xg.json            -- tournament xG leaderboards
  research/site/data/match_report_final.json -- the Final (match 3869685)

Re-run:
  cd ~/wc2026-tracking-transformer && uv run python research/compute_xg_analytics.py
"""
import json
import glob
import os
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
RAW_EVENTS = os.path.join(ROOT, "research/data/raw_statsbomb/events")
MATCHES_PARQUET = os.path.join(ROOT, "research/data/statsbomb/matches_wc_2022_sb.parquet")
WC_MATCHES_RAW = os.path.join(ROOT, "research/data/raw_statsbomb/matches/43/106.json")
OUT_DIR = os.path.join(ROOT, "research/site/data")
FINAL_MATCH_ID = 3869685

# StatsBomb pitch is 120 x 80; site renders on 105 x 68.
SB_X, SB_Y = 120.0, 80.0
PITCH_X, PITCH_Y = 105.0, 68.0


def load_events(match_id):
    with open(os.path.join(RAW_EVENTS, f"{match_id}.json")) as f:
        return json.load(f)


def is_shootout(ev):
    return ev.get("period") == 5


def is_shot(ev):
    return ev.get("type", {}).get("name") == "Shot"


# ---------------------------------------------------------------------------
# 1) TOURNAMENT xG LEADERBOARDS
# ---------------------------------------------------------------------------
def tournament_leaderboards(match_ids):
    # player -> aggregates
    pl_xg = defaultdict(float)
    pl_shots = defaultdict(int)
    pl_goals = defaultdict(int)
    pl_team = {}            # player -> last team seen
    pl_has_pen = defaultdict(bool)

    tm_xg = defaultdict(float)
    tm_shots = defaultdict(int)
    tm_goals = defaultdict(int)

    n_matches = 0
    n_shots = 0

    for mid in match_ids:
        path = os.path.join(RAW_EVENTS, f"{mid}.json")
        if not os.path.exists(path):
            continue
        n_matches += 1
        for ev in load_events(mid):
            if not is_shot(ev):
                continue
            if is_shootout(ev):           # exclude penalty shootout entirely
                continue
            shot = ev["shot"]
            xg = shot.get("statsbomb_xg", 0.0) or 0.0
            team = ev["team"]["name"]
            player = ev["player"]["name"]
            outcome = shot.get("outcome", {}).get("name")
            stype = shot.get("type", {}).get("name")
            is_pen = stype == "Penalty"

            n_shots += 1
            pl_team[player] = team
            pl_xg[player] += xg
            pl_shots[player] += 1
            tm_xg[team] += xg
            tm_shots[team] += 1
            if is_pen:
                pl_has_pen[player] = True
            if outcome == "Goal":
                pl_goals[player] += 1
                tm_goals[team] += 1

    players_by_xg = sorted(pl_xg.items(), key=lambda kv: kv[1], reverse=True)[:20]
    players_xg = [
        {
            "player": p,
            "team": pl_team[p],
            "xg": round(pl_xg[p], 2),
            "shots": pl_shots[p],
            "goals": pl_goals[p],
            "includes_penalty": pl_has_pen[p],
        }
        for p, _ in players_by_xg
    ]

    teams_by_xg = sorted(tm_xg.items(), key=lambda kv: kv[1], reverse=True)[:20]
    teams_xg = [
        {"team": t, "xg": round(tm_xg[t], 2), "shots": tm_shots[t], "goals": tm_goals[t]}
        for t, _ in teams_by_xg
    ]

    players_by_goals = sorted(
        pl_goals.items(), key=lambda kv: (kv[1], pl_xg[kv[0]]), reverse=True
    )[:15]
    players_goals = [
        {
            "player": p,
            "team": pl_team[p],
            "goals": pl_goals[p],
            "xg": round(pl_xg[p], 2),
            "shots": pl_shots[p],
        }
        for p, _ in players_by_goals
    ]

    return {
        "meta": {
            "competition": "FIFA World Cup 2022 (StatsBomb open-data)",
            "n_matches": n_matches,
            "n_shots": n_shots,
            "note": "xG is StatsBomb's statsbomb_xg. Penalty shootouts (period 5) excluded "
                    "from all xG/shot/goal totals. In-game penalties are KEPT and flagged "
                    "(players[].includes_penalty).",
        },
        "players_by_xg": players_xg,
        "teams_by_xg": teams_xg,
        "players_by_goals": players_goals,
    }


# ---------------------------------------------------------------------------
# Orientation helpers
# ---------------------------------------------------------------------------
def scale_xy(x, y):
    """Scale StatsBomb 120x80 to render pitch 105x68."""
    return x * (PITCH_X / SB_X), y * (PITCH_Y / SB_Y)


def team_period_attack_dir(events, team, period):
    """
    Determine which way a team attacks in a given period using their PASS events.
    StatsBomb records true pitch coords for passes; a team progresses the ball
    toward the goal it attacks. We compare mean of pass end_location.x vs
    start location.x is unreliable, so instead use mean shot/forward-pass x.

    Returns +1 if team attacks toward x=120 (already right), -1 if toward x=0.
    Heuristic: a team attacks the goal that its open-play shots aim at. But shot
    locations are stored in attack direction. So we use pass progression:
    forward passes net toward the attacking goal. We compute the median x of the
    team's pass START locations weighted toward where they spend possession is
    ambiguous. Most robust: use the location of the team's shots is biased.

    Best signal available: each event 'location' for passes is true-pitch. A
    team attacking right has higher mean end_location.x than start across
    completed forward passes. We use sign of mean(end.x - start.x) for passes
    that gained ground, but simplest robust proxy is mean pass start x relative
    to 60: teams build from their own half. We instead use the team's shots,
    which in SB are in attack frame, combined with the GK/keeper events.
    """
    raise NotImplementedError  # replaced by data-driven approach below


def compute_attack_dirs(events):
    """
    Robust attack-direction per (team, period), derived from the team's own
    actions. StatsBomb stores PASS/CARRY locations in TRUE pitch coordinates
    that swap by period. We use the mean x of each team's *attacking-third entry*
    proxy: the average x location of the team's PASSES that immediately precede
    or lead toward goal is messy. Instead, the cleanest robust signal:

    A team's GOAL-KEEPER and defensive actions cluster near their OWN goal.
    Goalkeeper events have true-pitch locations. The keeper's mean x tells us
    which goal the team defends; they attack the opposite end.

    Returns dict[(team, period)] -> +1 (attack right / toward x=120) or -1.
    """
    # collect keeper event x by (team, period)
    keeper_x = defaultdict(list)
    for ev in events:
        if ev.get("type", {}).get("name") == "Goal Keeper":
            loc = ev.get("location")
            if loc:
                keeper_x[(ev["team"]["name"], ev.get("period"))].append(loc[0])

    dirs = {}
    for (team, period), xs in keeper_x.items():
        mean_x = sum(xs) / len(xs)
        # keeper near x=0 -> team defends left -> attacks right -> +1
        dirs[(team, period)] = +1 if mean_x < 60 else -1
    return dirs


def orient_location(x, y, attack_dir):
    """
    Flip a true-pitch StatsBomb (120x80) location so the team attacks RIGHT
    (toward x=120), then scale to 105x68.
    """
    if attack_dir == -1:
        x = SB_X - x
        y = SB_Y - y
    return scale_xy(x, y)


# ---------------------------------------------------------------------------
# Jersey numbers from Starting XI + Tactical Shift events
# ---------------------------------------------------------------------------
def jersey_map(events):
    jersey = {}
    for ev in events:
        t = ev.get("type", {}).get("name")
        if t in ("Starting XI", "Tactical Shift"):
            for entry in ev.get("tactics", {}).get("lineup", []):
                jersey[entry["player"]["name"]] = entry["jersey_number"]
    return jersey


# ---------------------------------------------------------------------------
# 2) THE FINAL
# ---------------------------------------------------------------------------
def final_report():
    events = load_events(FINAL_MATCH_ID)
    raw_match = json.load(open(WC_MATCHES_RAW))
    meta_match = next(m for m in raw_match if m["match_id"] == FINAL_MATCH_ID)

    home = meta_match["home_team"]["home_team_name"]   # Argentina
    away = meta_match["away_team"]["away_team_name"]    # France
    teams = [home, away]

    attack_dirs = compute_attack_dirs(events)
    jersey = jersey_map(events)

    # ---- per-team aggregates (exclude shootout) ----
    xg = {home: 0.0, away: 0.0}
    shots_ct = {home: 0, away: 0}
    sot = {home: 0, away: 0}            # shots on target = Goal or Saved
    passes_total = {home: 0, away: 0}
    passes_completed = {home: 0, away: 0}

    shots_list = []
    scorers = []
    xg_timeline = []

    ON_TARGET = {"Goal", "Saved", "Saved to Post"}

    for ev in events:
        t = ev.get("type", {}).get("name")
        team = ev.get("team", {}).get("name")
        if t == "Pass" and not is_shootout(ev):
            if team in passes_total:
                passes_total[team] += 1
                # complete pass = no pass.outcome key
                if "outcome" not in ev.get("pass", {}):
                    passes_completed[team] += 1
        elif t == "Shot":
            if is_shootout(ev):
                continue
            shot = ev["shot"]
            sxg = shot.get("statsbomb_xg", 0.0) or 0.0
            outcome = shot.get("outcome", {}).get("name")
            stype = shot.get("type", {}).get("name")
            is_pen = stype == "Penalty"
            minute = ev.get("minute")
            period = ev.get("period")
            player = ev["player"]["name"]

            xg[team] += sxg
            shots_ct[team] += 1
            if outcome in ON_TARGET:
                sot[team] += 1

            # StatsBomb shot locations are stored in the ATTACK frame already
            # (toward x=120). So both teams' shots are toward high x; we just scale.
            loc = ev.get("location", [None, None])
            sx, sy = scale_xy(loc[0], loc[1])
            shots_list.append({
                "team": team,
                "x": round(sx, 2),
                "y": round(sy, 2),
                "xg": round(sxg, 4),
                "outcome": outcome,
                "player": player,
                "minute": minute,
                "period": period,
                "is_penalty": is_pen,
            })
            xg_timeline.append({"team": team, "minute": minute, "xg": round(sxg, 4)})
            if outcome == "Goal":
                scorers.append({
                    "player": player, "team": team, "minute": minute,
                    "xg": round(sxg, 4), "period": period,
                })

    # order timeline chronologically by (period, minute, second)
    # re-derive with second for stable ordering
    def shot_key(ev):
        return (ev.get("period"), ev.get("minute"), ev.get("second"))
    shot_evs = [e for e in events if e.get("type", {}).get("name") == "Shot" and not is_shootout(e)]
    shot_evs.sort(key=shot_key)
    xg_timeline = [
        {"team": e["team"]["name"], "minute": e.get("minute"),
         "xg": round(e["shot"].get("statsbomb_xg", 0.0) or 0.0, 4)}
        for e in shot_evs
    ]

    possession_pct = {
        t: round(100.0 * passes_completed[t] / max(1, sum(passes_completed.values())), 1)
        for t in teams
    }
    pass_pct = {
        t: round(100.0 * passes_completed[t] / max(1, passes_total[t]), 1) for t in teams
    }

    per_team = {}
    for t in teams:
        per_team[t] = {
            "xg": round(xg[t], 2),
            "shots": shots_ct[t],
            "shots_on_target": sot[t],
            "possession_pct": possession_pct[t],
            "passes_total": passes_total[t],
            "passes_completed": passes_completed[t],
            "pass_pct": pass_pct[t],
        }

    # ---- shootout (period 5) ----
    so_goals = {home: 0, away: 0}
    so_attempts = []
    for ev in events:
        if is_shootout(ev) and ev.get("type", {}).get("name") == "Shot":
            team = ev["team"]["name"]
            outcome = ev["shot"].get("outcome", {}).get("name")
            scored = outcome == "Goal"
            if scored:
                so_goals[team] += 1
            so_attempts.append({"team": team, "player": ev["player"]["name"],
                                "scored": scored, "outcome": outcome})

    # ---- pass networks ----
    pass_networks = {}
    for t in teams:
        nodes, edges = build_pass_network(events, t, attack_dirs, jersey)
        pass_networks[t] = {"nodes": nodes, "edges": edges}

    # validation: fraction of shots in attacking half (x>52.5 on 105 pitch)
    n_att_half = sum(1 for s in shots_list if s["x"] > PITCH_X / 2)
    frac_att = round(100.0 * n_att_half / max(1, len(shots_list)), 1)

    report = {
        "meta": {
            "match_id": FINAL_MATCH_ID,
            "competition": "FIFA World Cup 2022 Final",
            "home_team": home,
            "away_team": away,
            "date": meta_match["match_date"],
            "stadium": meta_match.get("stadium", {}).get("name"),
            "score_regulation": f"{meta_match['home_score']}-{meta_match['away_score']}",
            "score_note": "3-3 after extra time",
            "shootout": f"{home} won {so_goals[home]}-{so_goals[away]} on penalties",
            "shootout_attempts": so_attempts,
            "orientation_method": (
                "Shot scatter: StatsBomb stores shot locations in each team's attack "
                "frame (toward x=120), so both teams already attack the same (high-x) "
                "side; coords only scaled 120x80 -> 105x68. Pass-network coords use TRUE "
                "pitch coords (which swap by period), so per (team,period) attack "
                "direction is inferred from that team's goalkeeper event x (keeper near "
                "x<60 => team defends left => attacks right => +1, else flip x,y). All "
                "oriented to attack RIGHT, then scaled to 105x68."
            ),
            "possession_method": (
                "possession_pct computed as each team's share of COMPLETED passes "
                "(in-play, shootout excluded)."
            ),
            "xg_note": "xG excludes penalty shootout. In-game penalties kept.",
        },
        "per_team": per_team,
        "validation": {
            "shots_total": len(shots_list),
            "shots_in_attacking_half_pct": frac_att,
        },
        "shots": shots_list,
        "scorers": sorted(scorers, key=lambda s: (s["period"], s["minute"])),
        "xg_timeline": xg_timeline,
        "pass_network": pass_networks,
    }
    return report


def build_pass_network(events, team, attack_dirs, jersey):
    """
    Completed passes between teammates (exclude shootout). Node position = mean
    oriented location of the player's pass origins; node size = #passes made.
    Returns top-11 nodes by involvement and top ~14 edges by count.
    """
    loc_sum = defaultdict(lambda: [0.0, 0.0])
    loc_n = defaultdict(int)
    made = defaultdict(int)
    edge = defaultdict(int)

    for ev in events:
        if ev.get("type", {}).get("name") != "Pass":
            continue
        if is_shootout(ev):
            continue
        if ev.get("team", {}).get("name") != team:
            continue
        p = ev["pass"]
        if "outcome" in p:                # incomplete / out / offside
            continue
        recipient = p.get("recipient", {}).get("name")
        if not recipient:
            continue
        passer = ev["player"]["name"]
        loc = ev.get("location")
        period = ev.get("period")
        ad = attack_dirs.get((team, period), +1)
        if loc:
            ox, oy = orient_location(loc[0], loc[1], ad)
            loc_sum[passer][0] += ox
            loc_sum[passer][1] += oy
            loc_n[passer] += 1
        made[passer] += 1
        # undirected-ish but keep direction passer->recipient
        edge[(passer, recipient)] += 1

    # involvement = passes made + passes received
    received = defaultdict(int)
    for (a, b), c in edge.items():
        received[b] += c
    involvement = defaultdict(int)
    for pl in set(list(made) + list(received)):
        involvement[pl] = made.get(pl, 0) + received.get(pl, 0)

    top_players = [p for p, _ in sorted(involvement.items(), key=lambda kv: kv[1],
                                        reverse=True)[:11]]
    top_set = set(top_players)

    nodes = []
    for pl in top_players:
        n = max(1, loc_n[pl])
        nodes.append({
            "player": pl,
            "jersey": jersey.get(pl),
            "avg_x": round(loc_sum[pl][0] / n, 2),
            "avg_y": round(loc_sum[pl][1] / n, 2),
            "passes": made.get(pl, 0),
        })

    edges_filtered = [
        {"from": a, "to": b, "count": c}
        for (a, b), c in edge.items()
        if a in top_set and b in top_set
    ]
    edges_filtered.sort(key=lambda e: e["count"], reverse=True)
    edges_filtered = edges_filtered[:14]

    return nodes, edges_filtered


def main():
    import pandas as pd
    matches = pd.read_parquet(MATCHES_PARQUET)
    match_ids = matches["match_id"].tolist()
    assert FINAL_MATCH_ID in match_ids, "Final not in WC2022 match list!"

    os.makedirs(OUT_DIR, exist_ok=True)

    eda = tournament_leaderboards(match_ids)
    with open(os.path.join(OUT_DIR, "eda_xg.json"), "w") as f:
        json.dump(eda, f, indent=2, ensure_ascii=False)

    final = final_report()
    with open(os.path.join(OUT_DIR, "match_report_final.json"), "w") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)

    # ---- console validation ----
    print("=== eda_xg.json ===")
    print("n_matches:", eda["meta"]["n_matches"], "n_shots:", eda["meta"]["n_shots"])
    print("top scorer:", eda["players_by_goals"][0])
    print("top xG player:", eda["players_by_xg"][0])
    print("top xG team:", eda["teams_by_xg"][0])
    print()
    print("=== match_report_final.json ===")
    pt = final["per_team"]
    h, a = final["meta"]["home_team"], final["meta"]["away_team"]
    print(f"final xG: {h} {pt[h]['xg']} - {pt[a]['xg']} {a}")
    print("score:", final["meta"]["score_regulation"], "/", final["meta"]["shootout"])
    print("shots in attacking half pct:", final["validation"]["shots_in_attacking_half_pct"])
    print("scorers:", [(s["player"].split()[0], s["minute"]) for s in final["scorers"]])
    print("per_team:", json.dumps(pt, indent=2))


if __name__ == "__main__":
    main()
