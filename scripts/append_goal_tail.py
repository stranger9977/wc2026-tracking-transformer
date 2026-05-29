"""Append a short synthetic tail to a clip JSON so the ball is visibly in
the net at the end of playback.

PFF tracking data for the En-Nesyri clip ends ~1.7 s after the header strike,
so the actual ball-crossing-the-line never gets drawn. This script tacks on
N synthetic frames (default 10 = 2 s @ 5 Hz) where:

  • players are held at their last real position with a tiny drift toward
    their existing velocity (clamped — no teleports)
  • the ball moves on a straight line from its last real (x, y) to a point
    just past the chosen goal mouth (right or left), so the last few frames
    show it crossing into the net
  • p_score, p_concede, vaep, attention vectors, and pair_attention_*_top
    are all held at the last real frame's value so the UI keeps narrating
  • every synthetic frame carries ``is_synthetic: true`` for transparency

Usage:
    python scripts/append_goal_tail.py \\
        --label morocco-portugal-en-nesyri \\
        --goal-side right --n-frames 10
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--clips-dir", default="research/site/data/clips")
    ap.add_argument("--n-frames", type=int, default=10)
    ap.add_argument("--goal-side", choices=["right", "left"], required=True,
                    help="Which goal the ball is heading into.")
    ap.add_argument("--pitch-half-length", type=float, default=52.5,
                    help="Half of pitch length in metres (default 52.5 = 105/2).")
    args = ap.parse_args()

    path = Path(args.clips_dir) / f"{args.label}.json"
    payload = json.loads(path.read_text())
    frames = payload["frames"]
    last = frames[-1]
    if last.get("is_synthetic"):
        print(f"[{path.name}] tail already appended; skipping.")
        return

    goal_x = args.pitch_half_length + 1.0  # 1 m past the goal line
    if args.goal_side == "left":
        goal_x = -goal_x
    ball_start = (last["ball"]["x"], last["ball"]["y"])
    ball_end = (goal_x, 0.0)  # centre of the goal mouth
    n = args.n_frames
    dt_ms = 200  # 5 Hz

    added = []
    for k in range(1, n + 1):
        t = k / n
        bx = ball_start[0] + (ball_end[0] - ball_start[0]) * t
        by = ball_start[1] + (ball_end[1] - ball_start[1]) * t
        # ease-out: most of the ball motion happens in the first half so the
        # last 2-3 frames just show the ball settled past the line.
        ease_t = 1.0 - (1.0 - t) ** 2
        bx = ball_start[0] + (ball_end[0] - ball_start[0]) * ease_t
        by = ball_start[1] + (ball_end[1] - ball_start[1]) * ease_t

        f = copy.deepcopy(last)
        f["is_synthetic"] = True
        f["frame_idx"] = (last.get("frame_idx") or 0) + k
        f["frame_id"] = None
        f["timestamp_ms"] = (last.get("timestamp_ms") or 0) + k * dt_ms
        f["event_label"] = None
        f["is_goal_event"] = False
        # Carry attention + pair_top values from the last real frame so the
        # network keeps rendering through the tail.
        # (the deepcopy already did that)
        f["ball"] = {"x": float(bx), "y": float(by)}
        f["ball_xy"] = [float(bx), float(by)]
        # Players: nudge each by 0.5 * vx / vy * dt so the scene doesn't look
        # frozen. Clamped so nobody crosses the pitch in 2 s.
        new_players = []
        for p in f["players"]:
            np_ = dict(p)
            np_["x"] = float(p["x"]) + 0.5 * float(p.get("vx", 0.0)) * (k * dt_ms / 1000.0)
            np_["y"] = float(p["y"]) + 0.5 * float(p.get("vy", 0.0)) * (k * dt_ms / 1000.0)
            # Clamp to pitch + a small margin so nobody flies off-screen.
            np_["x"] = max(-args.pitch_half_length - 2.0,
                           min(args.pitch_half_length + 2.0, np_["x"]))
            np_["y"] = max(-35.0, min(35.0, np_["y"]))
            # Velocities go to 0 after the goal — everyone reacts/stops.
            np_["vx"] = 0.0
            np_["vy"] = 0.0
            new_players.append(np_)
        f["players"] = new_players
        added.append(f)

    payload["frames"].extend(added)
    payload["n_frames"] = len(payload["frames"])
    path.write_text(json.dumps(payload, indent=2))
    print(f"[{path.name}] appended {n} synthetic frames "
          f"({n * dt_ms / 1000.0:.1f} s) toward {args.goal_side} goal. "
          f"new n_frames={payload['n_frames']}.")


if __name__ == "__main__":
    main()
