"""Compare off-off attention share between shared model and score specialist
on the 5 featured Interactive Plays clips.

Reads each clip JSON (which after add_score_specialist_attention.py contains
BOTH ``attention`` (shared) and ``attention_score_specialist``). For each
frame, computes the fraction of ball→player attention mass that goes to
"offensive" players (FWD/MID), excluding DEF and GK. Reports per-clip
averages + the goal-frame snapshot + the 5-clip mean for each model.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLIPS_DIR = REPO / "research" / "site" / "data" / "clips"

OFF_POS = {"FWD", "MID", "CF", "ST", "LW", "RW", "AM", "CM", "DM", "LM", "RM"}
DEF_POS = {"DEF", "GK", "CB", "LB", "RB", "LCB", "RCB"}


def is_offensive(player: dict) -> bool:
    pos = (player.get("position") or "").upper()
    if not pos:
        return False
    if player.get("is_gk"):
        return False
    if pos in OFF_POS:
        return True
    if pos in DEF_POS:
        return False
    # Unknown / unmapped → don't count as offensive (conservative).
    return False


def off_share(attn: list[float], players: list[dict]) -> float:
    total = sum(attn)
    if total <= 0:
        return 0.0
    off_sum = 0.0
    by_slot = {p.get("slot"): p for p in players}
    for s, a in enumerate(attn):
        p = by_slot.get(s)
        if p and is_offensive(p):
            off_sum += a
    return off_sum / total


def top3(attn: list[float], players: list[dict]) -> list[tuple[str, str, float]]:
    by_slot = {p.get("slot"): p for p in players}
    ranked = sorted(enumerate(attn), key=lambda kv: -kv[1])[:3]
    out = []
    for slot, a in ranked:
        p = by_slot.get(slot) or {}
        out.append((p.get("name") or f"slot {slot}", p.get("position") or "?", float(a)))
    return out


def main() -> None:
    index = json.loads((CLIPS_DIR / "index.json").read_text())
    rows = []
    print(f"{'clip':<38} {'shared avg':>10} {'spec avg':>10} {'shared@goal':>12} {'spec@goal':>10}")
    for entry in index:
        label = entry["label"]
        clip = json.loads((CLIPS_DIR / f"{label}.json").read_text())
        frames = clip["frames"]
        if not frames or "attention_score_specialist" not in frames[0]:
            print(f"{label}: missing attention_score_specialist — skip")
            continue
        shared_shares = [off_share(f["attention"], f["players"]) for f in frames]
        spec_shares = [off_share(f["attention_score_specialist"], f["players"]) for f in frames]
        avg_shared = sum(shared_shares) / len(shared_shares)
        avg_spec = sum(spec_shares) / len(spec_shares)

        goal_idx = next((i for i, f in enumerate(frames) if f.get("is_goal_event")), -1)
        g_shared = shared_shares[goal_idx] if goal_idx >= 0 else float("nan")
        g_spec = spec_shares[goal_idx] if goal_idx >= 0 else float("nan")

        rows.append((label, avg_shared, avg_spec, g_shared, g_spec, goal_idx, frames))
        print(f"{label:<38} {avg_shared:>10.3f} {avg_spec:>10.3f} {g_shared:>12.3f} {g_spec:>10.3f}")

    if rows:
        mean_shared = sum(r[1] for r in rows) / len(rows)
        mean_spec = sum(r[2] for r in rows) / len(rows)
        print(f"{'mean':<38} {mean_shared:>10.3f} {mean_spec:>10.3f}")
        diff = mean_spec - mean_shared
        print(f"\nspecialist - shared = {diff:+.3f} ({diff*100:+.1f} pp)")
        if diff >= 0.05:
            print(">>> DECISION: REPLACE — specialist gains ≥ 5pp offense share")
        else:
            print(">>> DECISION: KEEP shared — specialist gain < 5pp")

    # Di María top-3 at goal frame for both models.
    for label, _, _, _, _, gidx, frames in rows:
        if label != "argentina-france-di-maria" or gidx < 0:
            continue
        f = frames[gidx]
        print(f"\nDi María goal frame (idx={gidx}):")
        print(" shared top-3:", top3(f["attention"], f["players"]))
        print(" spec   top-3:", top3(f["attention_score_specialist"], f["players"]))


if __name__ == "__main__":
    main()
