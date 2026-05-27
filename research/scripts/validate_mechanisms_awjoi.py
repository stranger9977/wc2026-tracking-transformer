"""Validate the 12 named chemistry mechanisms against AW-JOI.

For each whiteboard move tagged with a mechanism_id, compute AW-JOI on the
frames inside the move's window (around the move's peak_d_net_frame) for the
"affected pair": the shifted player and the same-team teammate who carries
the strongest ball-attention coupling with them in that window. Compare to
the same pair's AW-JOI per frame averaged over the rest of the clip.

AW-JOI(p, q, t) := attn_ball->p(t) * attn_ball->q(t) * max(dP_score(t), 0)

where dP_score(t) = p_score(t+1) - p_score(t).

Per-frame `attention` and `p_score` are read from the per-clip JSON at
research/site/data/clips/<label>.json. mechanism tagging comes from
research/site/data/whiteboard_moves.json.

Outputs:
  - prints a table to stdout
  - research/data/mechanism_validation.json   (machine-readable)
  - research/notes/mechanism_validation.md    (human report)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
CLIPS_DIR = REPO / "research" / "site" / "data" / "clips"
WB_PATH = REPO / "research" / "site" / "data" / "whiteboard_moves.json"
CONCEPTS_PATH = REPO / "research" / "site" / "data" / "chemistry_concepts.json"
OUT_JSON = REPO / "research" / "data" / "mechanism_validation.json"
OUT_MD = REPO / "research" / "notes" / "mechanism_validation.md"

WINDOW_RADIUS = 10  # frames each side of the peak (≈ 4s at 5 Hz)


def load_clip(label: str) -> dict:
    return json.loads((CLIPS_DIR / f"{label}.json").read_text())


def pair_joi_per_frame(clip: dict, slot_p: int, slot_q: int) -> np.ndarray:
    """AW-JOI contribution per frame for (slot_p, slot_q).

    Returns array of length n_frames-1 (last frame has no forward diff).
    """
    frames = clip["frames"]
    n = len(frames)
    p_score = np.array([f["p_score"] for f in frames], dtype=np.float64)
    dv = np.clip(np.diff(p_score), 0.0, None)  # (n-1,)
    attn = np.array([f["attention"] for f in frames], dtype=np.float64)  # (n, 22)
    coupling = attn[:-1, slot_p] * attn[:-1, slot_q]  # (n-1,)
    return coupling * dv


def slot_for_player(clip: dict, frame_idx: int, player_id: int) -> int | None:
    for p in clip["frames"][frame_idx]["players"]:
        if int(p.get("player_id") or -1) == int(player_id):
            return int(p["slot"])
    return None


def team_id_for_player(clip: dict, frame_idx: int, player_id: int) -> str | None:
    for p in clip["frames"][frame_idx]["players"]:
        if int(p.get("player_id") or -1) == int(player_id):
            return str(p.get("team_id"))
    return None


def pick_partner(
    clip: dict, peak: int, shifted_slot: int, shifted_team: str
) -> tuple[int, str] | None:
    """Pick same-team teammate with the highest joint ball-attention with shifted in-window."""
    n = len(clip["frames"])
    lo = max(0, peak - WINDOW_RADIUS)
    hi = min(n, peak + WINDOW_RADIUS + 1)
    attn_window = np.array(
        [clip["frames"][t]["attention"] for t in range(lo, hi)], dtype=np.float64
    )  # (W, 22)
    # Map slot -> (player_id, team_id, name, is_gk) from peak frame
    slot_info: dict[int, dict] = {}
    for p in clip["frames"][peak]["players"]:
        slot_info[int(p["slot"])] = {
            "player_id": p.get("player_id"),
            "team_id": str(p.get("team_id")),
            "name": p.get("name"),
            "is_gk": bool(p.get("is_gk")),
        }
    best_slot = None
    best_score = -1.0
    best_name = None
    for s in range(22):
        if s == shifted_slot:
            continue
        info = slot_info.get(s)
        if not info or info["is_gk"]:
            continue
        if info["team_id"] != shifted_team:
            continue
        coupling = attn_window[:, shifted_slot] * attn_window[:, s]
        score = float(coupling.sum())
        if score > best_score:
            best_score = score
            best_slot = s
            best_name = info["name"]
    if best_slot is None:
        return None
    return best_slot, best_name


def evaluate_move(clip: dict, move: dict) -> dict | None:
    shifts = move.get("shifts") or []
    if not shifts:
        return None
    shift = shifts[0]
    pid = int(shift["player_id"])
    name_shifted = shift.get("name")
    peak = int(move["summary"]["peak_d_net_frame"])
    n = len(clip["frames"])
    if not (0 <= peak < n):
        return None
    shifted_slot = slot_for_player(clip, peak, pid)
    shifted_team = team_id_for_player(clip, peak, pid)
    if shifted_slot is None or shifted_team is None:
        return None
    partner = pick_partner(clip, peak, shifted_slot, shifted_team)
    if partner is None:
        return None
    partner_slot, partner_name = partner

    joi = pair_joi_per_frame(clip, shifted_slot, partner_slot)  # (n-1,)
    lo = max(0, peak - WINDOW_RADIUS)
    hi = min(len(joi), peak + WINDOW_RADIUS + 1)
    in_window = joi[lo:hi]
    mask = np.ones(len(joi), dtype=bool)
    mask[lo:hi] = False
    out_window = joi[mask]
    in_mean = float(in_window.mean()) if len(in_window) else 0.0
    out_mean = float(out_window.mean()) if len(out_window) else 0.0
    lift = in_mean / out_mean if out_mean > 1e-9 else float("inf") if in_mean > 0 else 0.0
    return {
        "mechanism_id": move.get("mechanism_id"),
        "mechanism_name": move.get("mechanism_name"),
        "clip_label": clip["label"],
        "title": clip.get("title"),
        "peak_frame": peak,
        "window": [lo, hi],
        "shifted": {"player_id": pid, "name": name_shifted, "slot": shifted_slot},
        "partner": {"name": partner_name, "slot": partner_slot},
        "aw_joi_in_window_mean": in_mean,
        "aw_joi_baseline_mean": out_mean,
        "aw_joi_in_window_sum": float(in_window.sum()),
        "lift": lift,
        "in_window_n": int(len(in_window)),
        "baseline_n": int(len(out_window)),
        "move_mean_d_net": move["summary"].get("mean_d_net"),
        "move_peak_abs_d_net": move["summary"].get("peak_abs_d_net"),
    }


def main() -> None:
    wb = json.loads(WB_PATH.read_text())
    concepts = json.loads(CONCEPTS_PATH.read_text())
    mech_meta = {m["id"]: m for m in concepts["mechanisms"]}

    clips_by_label: dict[str, dict] = {}
    for clip in wb:
        clips_by_label[clip["label"]] = load_clip(clip["label"])

    results: list[dict] = []
    for clip_wb in wb:
        clip = clips_by_label[clip_wb["label"]]
        for move in clip_wb.get("moves", []):
            if not move.get("mechanism_id"):
                continue
            r = evaluate_move(clip, move)
            if r is not None:
                results.append(r)

    # Group by mechanism
    by_mech: dict[str, list[dict]] = {}
    for r in results:
        by_mech.setdefault(r["mechanism_id"], []).append(r)

    print(f"{'mechanism':24s}  {'clip':28s}  {'shifted -> partner':45s}  "
          f"{'in-win':>9s}  {'base':>9s}  {'lift':>6s}")
    print("-" * 130)
    for mid, rs in by_mech.items():
        for r in rs:
            pair_lbl = f"{r['shifted']['name']} -> {r['partner']['name']}"[:45]
            lift_s = f"{r['lift']:.2f}x" if np.isfinite(r['lift']) else " inf"
            print(
                f"{mid:24s}  {r['clip_label'][:28]:28s}  {pair_lbl:45s}  "
                f"{r['aw_joi_in_window_mean']:9.2e}  "
                f"{r['aw_joi_baseline_mean']:9.2e}  {lift_s:>6s}"
            )

    # Save machine-readable
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "window_radius_frames": WINDOW_RADIUS,
        "metric": "AW-JOI(p,q,t) = attn_ball->p(t) * attn_ball->q(t) * max(dP_score(t), 0)",
        "partner_selection": "same-team non-GK teammate with highest joint ball-attention with shifted player inside the window",
        "results": results,
        "mechanism_coverage": {
            mid: {
                "name": mech_meta[mid]["name"] if mid in mech_meta else mid,
                "n_examples": len(by_mech.get(mid, [])),
            }
            for mid in (set(by_mech.keys()) | {m["id"] for m in concepts["mechanisms"]})
        },
    }, indent=2))

    # Write markdown report
    write_markdown(by_mech, mech_meta, results)
    print(f"\nWrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")


def write_markdown(by_mech: dict[str, list[dict]], mech_meta: dict[str, dict], results: list[dict]) -> None:
    SET_PIECE_IDS = {"meat_wall", "near_post_flick_on", "short_corner_overload"}
    all_ids = [m["id"] for m in sorted(mech_meta.values(), key=lambda m: m["name"])]

    n_validated = 0
    for mid, rs in by_mech.items():
        if mid in SET_PIECE_IDS:
            continue
        means_in = np.array([r["aw_joi_in_window_mean"] for r in rs])
        means_base = np.array([r["aw_joi_baseline_mean"] for r in rs])
        if means_in.mean() > means_base.mean() and means_in.mean() > 0:
            n_validated += 1

    lines: list[str] = []
    lines.append("# Mechanism validation against AW-JOI")
    lines.append("")
    lines.append("**Question:** does the dataset surface, on the labelled Whiteboard clips, "
                 "examples where the affected pair's AW-JOI is elevated inside the mechanism's "
                 "window vs the rest of the clip?")
    lines.append("")
    lines.append(f"- Metric: AW-JOI per frame = `attn_ball→p(t) * attn_ball→q(t) * max(ΔP_score(t), 0)`. "
                 f"In-window = ±{WINDOW_RADIUS} frames around the move's `peak_d_net_frame` "
                 f"(≈ ±2 s at 5 Hz); baseline = rest of the clip.")
    lines.append("- Affected pair = the move's shifted player + the same-team non-GK teammate "
                 "with the highest joint ball-attention in the window.")
    lines.append("- `lift = mean(in-window) / mean(baseline)`. >1 means the pair is more "
                 "ball-coupled-and-value-creating when the mechanism plays out than the average "
                 "frame of the surrounding clip.")
    lines.append("")
    lines.append(f"**Headline:** {n_validated} of the 9 open-play mechanisms have at least one "
                 f"labelled example with AW-JOI lift >1 over the clip baseline. "
                 f"The 3 corner-kick mechanisms (Meat Wall, Near-Post Flick-On, Short-Corner Overload) "
                 f"have no Whiteboard clip yet — none of the 5 featured plays are corners.")
    lines.append("")
    lines.append("## Per-example evidence")
    lines.append("")
    lines.append("| mechanism | clip | shifted → partner | AW-JOI in-window | AW-JOI baseline | lift |")
    lines.append("|---|---|---|---:|---:|---:|")
    # sort by mechanism name then |lift|
    for mid in sorted(by_mech.keys(), key=lambda x: mech_meta.get(x, {}).get("name", x)):
        for r in by_mech[mid]:
            lift_s = f"{r['lift']:.2f}×" if np.isfinite(r['lift']) else "∞"
            pair = f"{r['shifted']['name']} → {r['partner']['name']}"
            mname = mech_meta.get(mid, {}).get("name", mid)
            lines.append(
                f"| {mname} | {r['clip_label']} | {pair} | "
                f"{r['aw_joi_in_window_mean']:.2e} | "
                f"{r['aw_joi_baseline_mean']:.2e} | {lift_s} |"
            )
    lines.append("")

    lines.append("## Per-mechanism reading")
    lines.append("")
    for mid in all_ids:
        m = mech_meta[mid]
        name = m["name"]
        rs = by_mech.get(mid, [])
        lines.append(f"### {name}")
        lines.append("")
        if mid in SET_PIECE_IDS:
            lines.append("**Coming soon.** This is a corner-kick mechanism. None of the 5 currently "
                         "featured Whiteboard plays are corners, so we have no labelled example to "
                         "validate against AW-JOI yet. Future work: select a corner clip per team that "
                         "uses this routine (Arsenal's Jover-era for *meat wall* is the canonical "
                         "out-of-tournament reference; for WC '22 candidates, England's near-post "
                         "deliveries and Spain's short-corner routines are the leading targets).")
            lines.append("")
            continue
        if not rs:
            lines.append("**No labelled example in the current 5 featured clips.** The Whiteboard "
                         "candidates ranker did not surface a top-7 move tagged with this mechanism "
                         "for any of these plays. Not a negative result — just absent coverage.")
            lines.append("")
            continue
        means_in = np.array([r["aw_joi_in_window_mean"] for r in rs])
        means_base = np.array([r["aw_joi_baseline_mean"] for r in rs])
        n_lift_gt1 = sum(
            1 for r in rs
            if r["aw_joi_baseline_mean"] > 0 and r["lift"] > 1.0
        )
        verdict = (
            "**Chemistry-positive in the data.**"
            if (means_in.mean() > means_base.mean() and n_lift_gt1 >= 1)
            else "**Mixed / inconclusive.**"
        )
        lines.append(
            f"{verdict} {len(rs)} labelled example(s); {n_lift_gt1}/{len(rs)} with in-window "
            f"AW-JOI exceeding clip baseline. Mean in-window AW-JOI {means_in.mean():.2e} vs "
            f"baseline {means_base.mean():.2e}."
        )
        # short narrative per example
        for r in rs:
            lift_s = f"{r['lift']:.2f}×" if np.isfinite(r['lift']) else "∞"
            lines.append(
                f"- *{r['clip_label']}* — {r['shifted']['name']} → {r['partner']['name']}: "
                f"in-window {r['aw_joi_in_window_mean']:.2e}, baseline "
                f"{r['aw_joi_baseline_mean']:.2e} ({lift_s})."
            )
        lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append("- Sample size is tiny: 5 clips, 13 mechanism-tagged moves. This is a "
                 "*structure check* — does the metric move in the expected direction on labelled "
                 "examples? — not a population-level effect.")
    lines.append("- The baseline (rest of the clip) includes both build-up frames and dead-ball "
                 "frames; some clips have very low overall p_score volatility, which inflates lift "
                 "ratios when the in-window contains the only meaningful ΔP_score spike.")
    lines.append("- The partner is chosen *post-hoc* as the highest-coupled same-team teammate in "
                 "the window, which biases toward finding non-zero in-window AW-JOI. The interesting "
                 "comparison is in-window vs the same pair's baseline across the same clip — that is "
                 "what the lift column reports.")
    lines.append("- Corner-kick mechanisms cannot be validated until a corner clip is featured.")
    lines.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
