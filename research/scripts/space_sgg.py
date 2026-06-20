"""SGG — Space Generation Gain (Fernandez & Bornn 2018, Eqs 10-11).

The fourth application: space a player creates FOR TEAMMATES by dragging a
defender off them. SOG (space_pobso) credits the space you win for YOURSELF;
SGG credits the space you free for SOMEONE ELSE.

F&B drag detection over a window [t, t+w], for generator i, receiver i', and
some opponent j:

    d(i', j, t)   <= delta      # j was MARKING the receiver at the start
    d(i,  j, t+w) <= delta      # j ends up near the GENERATOR
    d(i', j, t+w) >  delta      # j is no longer near the receiver (mark pulled)
    d(i,  j, t)   >  delta      # j was NOT already on the generator (a real move)

When a drag is detected, we attribute the RECEIVER's gain in owned dangerous
space over the window to the GENERATOR:

    SGG_i  +=  max(0,  Q(i', t+w) - Q(i', t))          (Q = control x xT, no reach,
                                                        the same per-player owned
                                                        dangerous space as SOG)

This reuses space_pobso.frame_obso for Q (per off-ball attacker owned control x
xT) and the shared opp_strength / stage machinery so the board has the SAME
schema as the SOG / passing / duel boards (stages group/ko/all, opponent-
weighted + raw, per-match + total).

Run (full 64, ~2 Hz):
    export PFF_ROOT="$HOME/pff_wc22_local"
    PYTHONPATH=src:research/scripts uv run python research/scripts/space_sgg.py
"""
from __future__ import annotations

import json
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
import space_pobso as sp  # noqa: E402
from opp_strength import OppStrength, stage_of, per_stage_block  # noqa: E402

HALF_LEN, HALF_WID = pc.HALF_LEN, pc.HALF_WID

# --- Drag-detection constants (F&B) ----------------------------------------
DELTA_M = 5.0          # "marking" distance (a defender within 5 m marks a player)
WINDOW_S = 3.0         # F&B drag window
EPS = 0.05             # min receiver Q-gain (xT-wtd m^2) to count a generation
SAMPLING_STRIDE = 15   # 30 Hz -> ~2 Hz
PERIODS = (1, 2)
COMPUTE_GRID = (26, 40)
SECS_PER_FRAME = SAMPLING_STRIDE / 30.0
WINDOW_FRAMES = max(1, round(WINDOW_S / SECS_PER_FRAME))   # 3 s -> 6 frames
EVAL_EVERY = 2         # evaluate a drag start every Nth kept frame (~1 s)
MIN_N = 30             # min generation events for a player to make the board

DATA_DIR = _REPO / "research" / "site" / "data"
SAMPLE_MATCHES = sp.SAMPLE_MATCHES


def _frame_record(fr, grid, xt_grid):
    """Per-frame record keyed by player IDENTITY (row index is NOT stable across
    frames — subs/occlusion change the count). Each player ->
    (x_m, y_m, is_att, is_gk, Q, name, team, team_id, jersey)."""
    _, _, attrib, _, _, _ = sp.frame_obso(fr, grid, xt_grid)
    px = fr.players[:, 0] * HALF_LEN
    py = fr.players[:, 1] * HALF_WID
    players = {}
    for row, ident in enumerate(fr.identities):
        x, y = float(px[row]), float(py[row])
        if x == 0 and y == 0 and fr.players[row, 2] == 0 and fr.players[row, 3] == 0:
            continue   # padding row
        key = (ident.team_id, ident.jersey)
        players[key] = {
            "x": x, "y": y,
            "is_att": bool(fr.players[row, 4] > 0),
            "is_gk": bool(fr.players[row, 5] > 0.5),
            "q": float(attrib.get(row, 0.0)),
            "name": ident.name, "team": ident.team,
            "team_id": ident.team_id, "jersey": ident.jersey,
        }
    return {"t": fr.timestamp_s, "players": players, "att_team": fr.in_possession_team}


def score_match(mid, grid, xt_grid, opp, meta):
    """Return {(team_id, jersey): {"gen_w": .., "gen_r": .., "n": ..,
    "name":.., "team":..}} of SGG accrued in this match."""
    teams = (meta["homeTeam"]["name"], meta["awayTeam"]["name"])
    recs = [_frame_record(fr, grid, xt_grid)
            for fr in space_io.read_match(mid, sampling_stride=SAMPLING_STRIDE,
                                          periods=PERIODS)]
    acc = defaultdict(lambda: {"gen_w": 0.0, "gen_r": 0.0, "n": 0,
                               "name": "", "team": "", "team_id": "", "jersey": 0})
    nF = len(recs)
    for s in range(0, nF - WINDOW_FRAMES, EVAL_EVERY):
        a, b = recs[s], recs[s + WINDOW_FRAMES]
        # possession must be stable + same attacking team across the window
        if a["att_team"] != b["att_team"]:
            continue
        att_team = a["att_team"]
        opp_team = teams[0] if att_team == teams[1] else teams[1]
        oppw = opp.weight(opp_team)
        pa, pb = a["players"], b["players"]
        # players present in BOTH frames (identity-aligned), split by role
        common = pa.keys() & pb.keys()
        atts = [k for k in common if pa[k]["is_att"] and not pa[k]["is_gk"]]
        dfns = [k for k in common if not pa[k]["is_att"] and not pa[k]["is_gk"]]
        if len(atts) < 2 or len(dfns) < 1:
            continue

        def dist(pl, ak, dk):
            return np.hypot(pl[ak]["x"] - pl[dk]["x"], pl[ak]["y"] - pl[dk]["y"])

        for dk in dfns:                                  # defender j
            recv, gen = [], []
            for ak in atts:
                d0 = dist(pa, ak, dk); d1 = dist(pb, ak, dk)
                if d0 <= DELTA_M and d1 > DELTA_M:       # marked then released
                    recv.append(ak)
                if d0 > DELTA_M and d1 <= DELTA_M:       # dragged ONTO at end
                    gen.append(ak)
            if not recv or not gen:
                continue
            for rk in recv:
                gain = pb[rk]["q"] - pa[rk]["q"]         # receiver's owned-danger gain
                if gain < EPS:
                    continue
                for gk in gen:
                    if gk == rk:
                        continue
                    e = acc[gk]
                    e["gen_w"] += gain * oppw
                    e["gen_r"] += gain
                    e["n"] += 1
                    e["name"] = pb[gk]["name"]; e["team"] = pb[gk]["team"]
                    e["team_id"] = pb[gk]["team_id"]; e["jersey"] = pb[gk]["jersey"]
    return acc, stage_of(mid)


def main():
    print("=" * 70)
    print("SGG — Space Generation Gain (F&B drag detection, Eqs 10-11)")
    print(f"sample: {len(SAMPLE_MATCHES)} matches, stride {SAMPLING_STRIDE} "
          f"(~{30.0/SAMPLING_STRIDE:.1f} Hz), w={WINDOW_S}s, delta={DELTA_M}m")
    print("=" * 70)
    grid = pc.make_grid(nx=COMPUTE_GRID[1], ny=COMPUTE_GRID[0])
    xt_grid = pc.xt_surface(grid)
    opp = OppStrength()

    # (team_id,jersey) -> stage -> {valw, valr, mids, n}
    pl_stage: dict = defaultdict(lambda: defaultdict(
        lambda: {"valw": 0.0, "valr": 0.0, "mids": set(), "n": 0}))
    pl_meta: dict = {}
    t0 = time.time()
    for mi, mid in enumerate(SAMPLE_MATCHES):
        meta = space_io.load_metadata(mid)
        tm = time.time()
        acc, stage = score_match(mid, grid, xt_grid, opp, meta)
        for key, e in acc.items():
            if e["n"] == 0:
                continue
            ps = pl_stage[key][stage]
            ps["valw"] += e["gen_w"]; ps["valr"] += e["gen_r"]
            ps["mids"].add(mid); ps["n"] += e["n"]
            pl_meta[key] = {"name": e["name"], "team": e["team"],
                            "team_id": e["team_id"], "jersey": e["jersey"]}
        nev = sum(v["n"] for v in acc.values())
        print(f"[{mi+1}/{len(SAMPLE_MATCHES)}] {mid} "
              f"{meta['homeTeam']['name']} v {meta['awayTeam']['name']}: "
              f"{nev} generation events [{time.time()-tm:.1f}s, "
              f"tot {time.time()-t0:.1f}s]", flush=True)

    # Build player board with the shared per-stage schema.
    players = []
    for key, stages in pl_stage.items():
        by_stage = {st: {"valw": s["valw"], "valr": s["valr"], "mids": s["mids"]}
                    for st, s in stages.items()}
        block = per_stage_block(by_stage)
        nall = sum(s["n"] for s in stages.values())
        if block["all"]["matches"] < 1 or nall < MIN_N:
            continue
        m = pl_meta[key]
        players.append({
            "name": m["name"], "team": m["team"], "jersey": m["jersey"],
            "stages": block, "n_events": nall,
            "sgg": block["all"]["per_match"],     # headline = opp-wtd per match
        })
    players.sort(key=lambda d: -d["sgg"])

    out = {
        "metric": "SGG",
        "title": "Space Generation Gain — space created for teammates",
        "definition": (
            "Fernandez & Bornn (2018) Eqs 10-11. A generation event is detected "
            "when a defender that was marking a teammate (within 5 m) is dragged "
            "onto the generator within a 3 s window, releasing the teammate; the "
            "teammate's gain in owned dangerous space (control x xT) is credited "
            "to the generator. Per-match opponent-weighted is the headline."),
        "params": {"delta_m": DELTA_M, "window_s": WINDOW_S, "eps": EPS,
                   "hz": round(30.0 / SAMPLING_STRIDE, 2)},
        "n_players": len(players),
        "players": players,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "space_sgg.json"
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"\n[export] SGG board -> {path} ({len(players)} players, {time.time()-t0:.0f}s)")
    print("[top-12 SGG (opp-weighted per match)]:")
    for p in players[:12]:
        print(f"   {p['name']:<22} {p['team']:<13} {p['sgg']:.3f}  "
              f"(n={p['n_events']}, {p['stages']['all']['matches']}m)")


if __name__ == "__main__":
    main()
