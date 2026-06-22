#!/usr/bin/env python3
"""Adapter: Eagle (broadcast->tracking CV) output -> our space_io.SpaceFrame stream.

Eagle (github.com/nreHieW/Eagle) turns a broadcast clip into per-frame player + ball
pitch coordinates in the UEFA system (corner origin, x in [0,105], y in [0,68], METERS).
This adapter maps one Eagle `processed_data.json` (+ `metadata.json`) into the same
SpaceFrame objects `space_io.read_match` yields, so the existing pitch-control / space
engine (pitch_control.control_surface, value_of_space_surface, player_space) and the
site's scrubber render an Eagle clip UNCHANGED.

Per-frame transform:
  * origin: corner -> centre  (x_c = X - 52.5, y_c = Y - 34); pitch is already 105x68, no rescale.
  * orientation: LOCK the attacking team to +x for the whole clip (a single attacking phase).
    Sign is chosen so the DEFENDING team's centroid lands at +x -- they sit deep in front of
    the goal being attacked. Applied to position AND ball (a pure sign flip on both axes,
    matching space_io.orient).
  * velocity: left 0 here; the renderer recomputes it from the SMOOTHED track (broadcast
    tracking jitters, exactly like the PFF clip path in clip_examples.export_window).
  * identity: Eagle gives anonymous-but-stable track ids, not names/jerseys. We synthesise a
    STABLE name per track ("FRA-12" / "MAR-7") so the scrubber's LERP-by-name works; is_gk
    comes from Eagle's Goalkeeper class.
  * ball: Eagle leaks pixel coords on frames where the projection fails; we reject out-of-pitch
    ball points and carry the last good ball position forward.

APPROXIMATE, broadcast-derived (~1-2 m, per-shot) -- a demo of the 2026 live pipeline, not a
metric source. The hard numbers stay on PFF tracking.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_REPO / "research" / "scripts")]
from space_io import HALF_LEN, HALF_WID, PlayerIdentity, SpaceFrame  # noqa: E402

PITCH_L, PITCH_W = 105.0, 68.0


def _abbr(name: str) -> str:
    return (name or "?")[:3].upper()


def read_eagle_clip(out_dir, *, attack_name="France", defend_name="Morocco",
                    true_fps=29.97, stride=3, min_players=8,
                    attack_bit=None, flip=None) -> list[SpaceFrame]:
    """Parse one Eagle output dir into a list of oriented SpaceFrame objects.

    out_dir       directory holding Eagle's processed_data.json + metadata.json.
    attack_name   team-name label for the team locked to +x (the attacking side).
    defend_name   team-name label for the other side.
    true_fps      real frame rate of the kept frames (Eagle stores the *requested* --fps
                  in metadata, which is wrong when skip collapses to 1; pass the video's
                  real rate so per-frame timestamps -> velocities are right).
    stride        keep every Nth frame (subsample: 29.97/3 ~ 10 Hz, plenty for the scrubber
                  and it tames jitter-amplified velocity).
    min_players   drop frames with fewer than this many projected players (the no-homography
                  lead-in frames).
    attack_bit    force which Eagle team id (0/1) is the attacker (else: majority nearest-to-ball).
    flip          force-invert the auto orientation sign if the attack renders the wrong way.
    """
    out_dir = Path(out_dir)
    frames_raw = json.load(open(out_dir / "processed_data.json"))
    meta = json.load(open(out_dir / "metadata.json"))
    team_map = {str(k): int(v) for k, v in meta.get("team_mapping", {}).items()}

    # ---- pass 1: parse entries; gather centroids + a nearest-to-ball possession vote ----
    parsed = []                       # (idx, [(id, team_bit|None, is_gk, X, Y)], ball|None)
    cent = {0: [], 1: []}             # corner-frame x per team (for centroid + unknown assignment)
    nearest = {0: 0, 1: 0}
    for idx, fr in enumerate(frames_raw):
        pls, ball = [], None
        for c in fr.get("Coordinates", []):
            cid = str(c.get("ID"))
            co = c.get("Coordinates")
            if cid == "Ball":
                if co and 0 <= co[0] <= PITCH_L and 0 <= co[1] <= PITCH_W:
                    ball = (float(co[0]), float(co[1]))   # reject pixel-leak / out-of-pitch
                continue
            if not co:
                continue
            X, Y = float(co[0]), float(co[1])
            if not (0 <= X <= PITCH_L and 0 <= Y <= PITCH_W):
                continue
            tb = team_map.get(cid)
            pls.append((cid, tb, c.get("Type") == "Goalkeeper", X, Y))
            if tb in (0, 1):
                cent[tb].append(X)
        parsed.append((idx, pls, ball))
        if ball:
            best, bestd = None, 1e18
            for (cid, tb, gk, X, Y) in pls:
                if gk or tb not in (0, 1):
                    continue
                d = (X - ball[0]) ** 2 + (Y - ball[1]) ** 2
                if d < bestd:
                    bestd, best = d, tb
            if best is not None:
                nearest[best] += 1

    # ---- decide attacking team + orientation sign ----
    if attack_bit is None:
        attack_bit = 0 if nearest[0] >= nearest[1] else 1
    defend_bit = 1 - attack_bit
    teamX = {b: (float(np.mean(cent[b])) if cent[b] else 52.5) for b in (0, 1)}
    # defenders sit deep in front of the goal being attacked -> orient so their centroid is at +x
    sign = 1.0 if (teamX[defend_bit] - 52.5) >= 0 else -1.0
    if flip:
        sign = -sign
    name_of = {attack_bit: attack_name, defend_bit: defend_name}
    abbr_of = {attack_bit: _abbr(attack_name), defend_bit: _abbr(defend_name)}

    # ---- pass 2: build SpaceFrames (subsampled, ball carried forward) ----
    frames: list[SpaceFrame] = []
    last_ball = None
    for idx, pls, ball in parsed:
        if ball is not None:
            last_ball = ball
        b = ball or last_ball
        if b is None or idx % stride != 0 or len(pls) < min_players:
            continue
        rows, idents = [], []
        for (cid, tb, is_gk, X, Y) in pls:
            xo, yo = (X - 52.5) * sign, (Y - 34.0) * sign
            if is_gk:
                # Eagle's colour-based team vote is unreliable for keepers (distinct kit). Assign
                # by goal half instead: the keeper by the attacked goal (+x) is the DEFENDING side;
                # one by the attacking team's own goal (-x) is the attacker's keeper.
                tb = defend_bit if xo > 0 else attack_bit
            elif tb not in (0, 1):   # untracked id -> nearest team centroid
                tb = 0 if abs(X - teamX[0]) <= abs(X - teamX[1]) else 1
            is_att = (tb == attack_bit)
            rows.append([xo / HALF_LEN, yo / HALF_WID, 0.0, 0.0,
                         1.0 if is_att else -1.0, 1.0 if is_gk else 0.0, 0.0])
            try:
                jersey = int(cid)
            except ValueError:
                jersey = 0
            idents.append(PlayerIdentity(
                team=name_of[tb], team_id=str(tb), name=f"{abbr_of[tb]}-{cid}",
                jersey=jersey, visibility="VISIBLE", confidence="EAGLE",
                is_gk=is_gk, is_attacking=is_att))
        frames.append(SpaceFrame(
            players=np.array(rows, dtype=np.float64),
            identities=idents,
            ball_m=np.array([(b[0] - 52.5) * sign, (b[1] - 34.0) * sign], dtype=np.float64),
            period=1,
            in_possession_team_id=str(attack_bit),
            in_possession_team=attack_name,
            timestamp_s=idx / true_fps,
            frame_num=idx))
    return frames


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--attack", default="France")
    ap.add_argument("--defend", default="Morocco")
    ap.add_argument("--flip", action="store_true")
    a = ap.parse_args()
    fr = read_eagle_clip(a.out_dir, attack_name=a.attack, defend_name=a.defend, flip=a.flip)
    print(f"{len(fr)} frames; first t={fr[0].timestamp_s:.2f}s last t={fr[-1].timestamp_s:.2f}s")
    f0 = fr[len(fr) // 2]
    print(f"mid frame: {len(f0.identities)} players, "
          f"{sum(1 for i in f0.identities if i.is_attacking)} attacking, "
          f"ball_m={f0.ball_m.round(1)}")
    axs = [p[0] * HALF_LEN for fr_ in fr for j, p in enumerate(fr_.players) if fr_.identities[j].is_attacking]
    dxs = [p[0] * HALF_LEN for fr_ in fr for j, p in enumerate(fr_.players) if not fr_.identities[j].is_attacking]
    print(f"attack mean x={np.mean(axs):.1f}  defend mean x={np.mean(dxs):.1f}  "
          f"(attack should be more +x if oriented right)")
