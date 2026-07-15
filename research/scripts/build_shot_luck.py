#!/usr/bin/env python3
"""Build shot_luck.json — the evidence that finishing is mostly a chance event and xG is
the predictive part. This is the analytic backing for the site's finishing boards, whose
own caption already says "who's running hot, not a verdict on finishing skill."

Three real cuts, all from StatsBomb open shot data (non-penalty shots only):

  1. CALIBRATION — bin every shot by its xG and check how often it actually scored. The ball
     goes in at almost exactly its xG in every decile: the *chance* determines the outcome,
     not the shooter's name. (This is "xG is predictive".)

  2. RELIABILITY — split each high-volume shooter's shots into two random halves. Chance
     quality (xG per shot) carries over strongly (r ~ 0.7 = a repeatable skill: getting into
     good spots). Finishing (goals - xG per shot) barely carries over (r ~ 0.1 = noise).
     Averaged over many random splits so it doesn't hinge on one lucky seed.

  3. LUCK BAND — under the null "nobody has finishing skill; every shot is a weighted coin
     that lands at its xG", simulate the whole shot set many times and measure how wide the
     players' goals-minus-xG spread gets by luck alone. The real spread is barely wider than
     pure luck -> almost all of finishing over/under-performance is chance.

Source: StatsBomb open data (WC 2022, Euro 2024, Copa America 2024, Ligue 1 2022/23,
Bundesliga 2023/24). Reads the raw event JSON under research/data/raw_statsbomb/events if
present; otherwise the slim snapshot in research/data/shot_luck_src.json (committed for repro).

Run:  python3 research/scripts/build_shot_luck.py
Out:  research/site/data/shot_luck.json   (+ research/data/shot_luck_src.json snapshot)
"""
import glob
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw_statsbomb" / "events"
SRC = ROOT / "data" / "shot_luck_src.json"
OUT = ROOT / "site" / "data" / "shot_luck.json"

COMPETITIONS = ["FIFA World Cup 2022", "UEFA Euro 2024", "Copa America 2024",
                "Ligue 1 2022/23", "Bundesliga 2023/24"]
N_BINS = 10          # calibration deciles
REL_MIN_SHOTS = 25   # a player needs this many non-pen shots to enter the split-half test
REL_SPLITS = 200     # random half-splits averaged over (kills single-seed luck)
LUCK_MIN_SHOTS = 20  # min shots to enter the luck-band spread
LUCK_SIMS = 400      # season re-simulations under the no-skill null


def load_shots():
    """Return list of (player_id, xg, goal) for every non-penalty shot; snapshot if raw absent."""
    if RAW.exists() and any(RAW.glob("*.json")):
        shots = []
        for f in glob.glob(str(RAW / "*.json")):
            for e in json.load(open(f)):
                if e.get("type", {}).get("name") != "Shot":
                    continue
                s = e["shot"]
                if s.get("type", {}).get("name") == "Penalty":
                    continue
                xg = s.get("statsbomb_xg")
                if xg is None:
                    continue
                goal = 1 if s.get("outcome", {}).get("name") == "Goal" else 0
                shots.append([e["player"]["id"], round(float(xg), 5), goal])
        shots.sort()  # deterministic order (by player_id, xg, goal)
        SRC.write_text(json.dumps({"competitions": COMPETITIONS, "shots": shots}))
        return shots
    return json.load(open(SRC))["shots"]


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    sy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return cov / (sx * sy) if sx * sy else 0.0


shots = load_shots()
by_player = defaultdict(list)
for pid, xg, goal in shots:
    by_player[pid].append((xg, goal))

n_shots = len(shots)
n_goals = sum(g for _, _, g in shots)
sum_xg = sum(x for _, x, _ in shots)

# 1 — calibration deciles (sorted by xg, equal-count bins)
allsh = sorted((x, g) for _, x, g in shots)
calibration = []
for i in range(N_BINS):
    seg = allsh[i * n_shots // N_BINS:(i + 1) * n_shots // N_BINS]
    calibration.append({"xg": round(sum(x for x, _ in seg) / len(seg), 4),
                        "scored": round(sum(g for _, g in seg) / len(seg), 4),
                        "n": len(seg)})

# 2 — split-half reliability, averaged over REL_SPLITS random halvings
elig = [v for v in by_player.values() if len(v) >= REL_MIN_SHOTS]
fin_rs, qual_rs = [], []
for seed in range(REL_SPLITS):
    random.seed(seed)
    fa, fb, qa, qb = [], [], [], []
    for v in elig:
        vv = v[:]
        random.shuffle(vv)
        h = len(vv) // 2
        A, B = vv[:h], vv[h:]
        fa.append(sum(g - x for x, g in A) / len(A)); fb.append(sum(g - x for x, g in B) / len(B))
        qa.append(sum(x for x, _ in A) / len(A));     qb.append(sum(x for x, _ in B) / len(B))
    fin_rs.append(corr(fa, fb)); qual_rs.append(corr(qa, qb))
reliability = {"finishing_r": round(sum(fin_rs) / len(fin_rs), 3),
               "quality_r": round(sum(qual_rs) / len(qual_rs), 3),
               "n_players": len(elig), "min_shots": REL_MIN_SHOTS, "n_splits": REL_SPLITS}

# 3 — luck band: real spread of goals-minus-xG vs pure-coin-flip spread
lucksh = [v for v in by_player.values() if len(v) >= LUCK_MIN_SHOTS]
real_sd = statistics.pstdev([sum(g - x for x, g in v) for v in lucksh])
sim_sds = []
for seed in range(LUCK_SIMS):
    random.seed(10_000 + seed)
    sim_sds.append(statistics.pstdev(
        [sum((1 if random.random() < x else 0) - x for x, _ in v) for v in lucksh]))
luck_sd = sum(sim_sds) / len(sim_sds)
luck = {"real_sd": round(real_sd, 2), "luck_sd": round(luck_sd, 2),
        "ratio": round(real_sd / luck_sd, 2), "n_players": len(lucksh), "min_shots": LUCK_MIN_SHOTS}

out = {
    "metric": "Finishing is (mostly) a chance event; xG is the predictive part",
    "source": "StatsBomb open data — non-penalty shots",
    "competitions": COMPETITIONS,
    "n_shots": n_shots, "n_goals": n_goals, "sum_xg": round(sum_xg, 1),
    "calibration": calibration,
    "reliability": reliability,
    "luck": luck,
}
OUT.write_text(json.dumps(out, indent=1))
print(f"wrote {OUT.name}: {n_shots} shots · {n_goals} goals vs {sum_xg:.0f} xG")
print(f"  calibration bins: {[(c['xg'], c['scored']) for c in calibration]}")
print(f"  reliability: finishing r={reliability['finishing_r']:+.3f}  "
      f"quality r={reliability['quality_r']:+.3f}  (n={reliability['n_players']}, {REL_SPLITS} splits)")
print(f"  luck band: real SD {luck['real_sd']} vs luck SD {luck['luck_sd']} "
      f"-> {luck['ratio']}x  (n={luck['n_players']})")
