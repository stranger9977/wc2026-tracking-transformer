"""Extract final-third combination play (one-twos) per team from the frame cache.

A one-two = A->B->A ball exchange between two attackers: the ball-carrier sequence
(from has_possession, denoised by a min-hold filter on possessor spells) returns to the
first player after a brief middle touch, same team throughout, with the return in the
attacking final third. Structural — uses NO model value signal (non-circular vs xG).

Writes research/data/combo_metrics.parquet: team_id, n_combo (all), n_combo_f3 (final third),
spells (possession-spell count, the rate denominator).

    PYTHONPATH=src uv run python research/scripts/extract_combination_play.py
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "research" / "data" / "frame_vaep_cache"
OUT = REPO / "research" / "data" / "combo_metrics.parquet"

MIN_HOLD = 2   # frames @5Hz a possessor must hold to count as a real spell (drops contested blips)
MAX_GAP = 15   # max frames between linked spells (~3s)
MAX_MID = 15   # middle touch must be brief (a lay-off, not a dribble)
FINAL_THIRD = 1 / 3   # ball within the attacking third of the defending goal


def _spells(T: np.ndarray, ip: np.ndarray):
    """Possessor spells: (slot, team, t_start, t_end) for runs >= MIN_HOLD with stable team."""
    n = len(T)
    hp = T[:, :22, 6]
    poss = np.where(hp.max(1) > 0.5, hp.argmax(1), -1)
    sp = []
    t = 0
    while t < n:
        p = poss[t]
        if p < 0 or ip[t] == "":
            t += 1
            continue
        u = t
        while u < n and poss[u] == p and str(ip[u]) == str(ip[t]):
            u += 1
        if u - t >= MIN_HOLD:
            sp.append((int(p), str(ip[t]), t, u - 1))
        t = u
    return sp


def main() -> None:
    recs = []
    spell_ct: dict[str, int] = {}
    for f in sorted(glob.glob(str(CACHE / "*.npz"))):
        d = np.load(f, allow_pickle=True)
        T, ip, sid = d["tensors"], d["in_possession"], d["slot_ids"]
        sp = _spells(T, ip)
        for a in {str(x) for x in ip if x}:
            spell_ct[a] = spell_ct.get(a, 0) + sum(1 for s in sp if s[1] == a)
        for i in range(len(sp) - 2):
            s1, s2, s3 = sp[i], sp[i + 1], sp[i + 2]
            if not (s1[1] == s2[1] == s3[1]):
                continue                                  # same team throughout
            if s1[0] == s2[0] or s2[0] == s3[0] or s1[0] != s3[0]:
                continue                                  # X, Y, X slot pattern
            if (s2[3] - s2[2]) > MAX_MID:
                continue                                  # middle touch brief
            if (s2[2] - s1[3]) > MAX_GAP or (s3[2] - s2[3]) > MAX_GAP:
                continue
            t3 = s3[2]
            pid_x, pid_y = int(sid[t3, s1[0]]), int(sid[s2[2], s2[0]])
            if pid_x < 0 or pid_y < 0 or pid_x == pid_y:
                continue                                  # distinct real players
            fr = T[t3]
            defm, gk, ball = fr[:, 4] < -0.5, fr[:, 5] > 0.5, np.abs(fr[:, 4]) < 0.5
            dgk = defm & gk
            if dgk.sum() == 0:
                continue
            sgn = np.sign(fr[dgk, 0].mean()) or 1.0       # defending goal end
            bx = fr[ball, 0].mean()
            recs.append((s1[1], 1 if bx * sgn > FINAL_THIRD else 0))
        print(f"  {Path(f).name}: {len(recs)} cum one-twos", flush=True)

    df = pd.DataFrame(recs, columns=["team_id", "f3"])
    agg = (df.groupby("team_id")
             .agg(n_combo=("f3", "size"), n_combo_f3=("f3", "sum"))
             .reset_index())
    agg["team_id"] = agg.team_id.astype(str)
    agg["spells"] = agg.team_id.map(spell_ct)
    agg.to_parquet(OUT)
    print(f"wrote {OUT}  ({len(agg)} teams)")


if __name__ == "__main__":
    main()
