"""ID-native raw-tracking reader for the PFF WC22 "space" metrics.

The pitch-control x xT engine (``research/scripts/pitch_control.py``) consumes
anonymous, oriented frames. The space metrics ALSO need to know WHICH NAMED
PLAYER owns a claimed pocket of space. The kloppy-based ``load_pff_match``
loader drops jersey/name identity, so this module is a parallel, pure-parsing
reader that goes straight to the raw PFF tracking JSONL and yields, per kept
frame, exactly the inputs the engine consumes PLUS the identity sidecar:

    SpaceFrame:
      players      (n, 7)  engine-ready, schema order
                           [x_norm, y_norm, vx, vy, is_attacking, is_gk, has_poss]
                           oriented so the IN-POSSESSION team attacks +x.
      identities   list[PlayerIdentity] aligned ROW-FOR-ROW with ``players``
                           {team, name, jersey, visibility, is_gk, is_attacking}
      ball_m       (2,)    [x_m, y_m] oriented to match ``players``
      period       int     1/2 (/3/4 for ET)
      in_possession_team_id  str  team id of the attacking (+x) team
      timestamp_s  float   period-elapsed seconds

Coordinate convention matches the engine: METERS, origin = pitch center, and we
orient so the in-possession team attacks +x (opponent goal at +52.5). x_norm =
x_m / 52.5, y_norm = y_m / 34.0.

This module reuses the engine for NOTHING; it only PRODUCES the engine's inputs.

Confirmed plumbing (see CLAUDE.md / task brief):
  * Raw frames are 30 Hz (fps 29.97), positions in meters, center origin,
    ORIGINAL (un-flipped) orientation.
  * Orientation sign: home attacks +1 if homeTeamStartLeft else -1 in P1; flips
    in P2; P3 uses homeTeamStartLeftExtraTime; P4 flips that.
  * Possession heuristic (no event join): the team whose nearest player is
    closest to the ball is attacking for that frame.
  * Velocity is finite-differenced per (team, jersey) vs the previous KEPT
    frame; clamped to +-12 m/s; 0-fallback when no prior frame.

Run the bounded validation on one match:
    export PFF_ROOT="$HOME/pff_wc22_local"
    PYTHONPATH=src uv run python research/scripts/space_io.py
"""
from __future__ import annotations

import bz2
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Pitch geometry (must match the engine's normalization). Origin = center.
HALF_LEN = 52.5  # m, x in [-52.5, 52.5]
HALF_WID = 34.0  # m, y in [-34, 34]

# Velocity finite-diff clamp (m/s).
VEL_CLAMP = 12.0

# Number of players each side fields on the pitch at once.
N_PER_SIDE = 11


@dataclass(frozen=True)
class PlayerIdentity:
    """Identity sidecar for one row of the engine ``players`` array."""

    team: str            # team name (e.g. "Argentina")
    team_id: str         # PFF team id
    name: str            # player nickname (e.g. "Lionel Messi")
    jersey: int          # shirt number
    visibility: str      # "VISIBLE" | "ESTIMATED"
    confidence: str      # "HIGH" | ... (PFF per-position confidence)
    is_gk: bool
    is_attacking: bool   # True if this player's team is in possession this frame


@dataclass
class SpaceFrame:
    """One kept frame: engine inputs + identity sidecar, oriented attacking-+x."""

    players: np.ndarray                 # (n, 7) engine-ready
    identities: list[PlayerIdentity]    # len n, row-aligned with players
    ball_m: np.ndarray                  # (2,) [x_m, y_m] oriented
    period: int
    in_possession_team_id: str
    in_possession_team: str
    timestamp_s: float
    frame_num: int


# ---------------------------------------------------------------------------
# Paths / loading helpers
# ---------------------------------------------------------------------------
def _pff_root(root: str | Path | None = None) -> Path:
    r = root or os.environ.get("PFF_ROOT")
    if not r:
        raise RuntimeError("PFF_ROOT not set; export PFF_ROOT=$HOME/pff_wc22_local")
    return Path(r)


def load_metadata(match_id: str | int, root: str | Path | None = None) -> dict:
    """Return the single metadata record (the file is a 1-element list)."""
    p = _pff_root(root) / "Metadata" / f"{match_id}.json"
    m = json.load(open(p))
    return m[0] if isinstance(m, list) else m


def load_roster(match_id: str | int, root: str | Path | None = None) -> dict:
    """Build a (team_id, jersey:int) -> {name, is_gk, team_name, team_id} map.

    The roster lists full squads (started True/False); we key by team+jersey so
    any player who appears in tracking resolves, including subs. Within a team
    shirt numbers are unique, so (team_id, jersey) is a safe key.
    """
    p = _pff_root(root) / "Rosters" / f"{match_id}.json"
    roster = json.load(open(p))
    lut: dict[tuple[str, int], dict] = {}
    for e in roster:
        team_id = str(e["team"]["id"])
        try:
            jersey = int(e["shirtNumber"])
        except (TypeError, ValueError):
            continue
        lut[(team_id, jersey)] = {
            "name": e.get("player", {}).get("nickname")
            or e.get("player", {}).get("name")
            or f"#{jersey}",
            "is_gk": e.get("positionGroupType") == "GK",
            "team_name": e["team"]["name"],
            "team_id": team_id,
        }
    return lut


def attacking_sign_for_home(meta: dict, period: int) -> int:
    """Sign that maps RAW x to HOME-attacking-+x for the given period.

    home attacks +x when homeTeamStartLeft is True in P1 (the team starting on
    the left attacks toward +x). P2 flips. P3 uses the ExtraTime flag; P4 flips.
    orient(x, sign) = x * sign.
    """
    start_left = bool(meta.get("homeTeamStartLeft"))
    start_left_et = meta.get("homeTeamStartLeftExtraTime")
    if period in (1, 2):
        base = 1 if start_left else -1
        return base if period == 1 else -base
    # Extra time (P3/P4). Fall back to regulation flag if ET flag absent.
    if start_left_et is None:
        start_left_et = start_left
    base_et = 1 if start_left_et else -1
    return base_et if period == 3 else -base_et


# ---------------------------------------------------------------------------
# Possession heuristic (no event join)
# ---------------------------------------------------------------------------
def _possession_team(home_xy: np.ndarray, away_xy: np.ndarray,
                     ball_xy: np.ndarray) -> str:
    """Return 'home' or 'away' — whichever side's nearest player is closest."""
    bh = np.hypot(home_xy[:, 0] - ball_xy[0], home_xy[:, 1] - ball_xy[1])
    ba = np.hypot(away_xy[:, 0] - ball_xy[0], away_xy[:, 1] - ball_xy[1])
    hmin = bh.min() if len(bh) else np.inf
    amin = ba.min() if len(ba) else np.inf
    return "home" if hmin <= amin else "away"


# ---------------------------------------------------------------------------
# Main reader
# ---------------------------------------------------------------------------
def read_match(
    match_id: str | int,
    *,
    sampling_stride: int = 6,
    limit: int | None = None,
    periods: tuple[int, ...] | None = None,
    require_ball: bool = True,
    root: str | Path | None = None,
    lock_attack_team_id: str | int | None = None,
):
    """Yield :class:`SpaceFrame` per kept frame, oriented so possession -> +x.

    Args:
        match_id: PFF match id (e.g. "10503").
        sampling_stride: keep every Nth raw frame. 30 Hz raw; stride 6 -> 5 Hz,
            stride 15 -> ~2 Hz (use a larger stride for bounded validation).
        limit: stop after reading this many RAW lines (bounding for speed).
        periods: keep only these periods (e.g. (1,)); None keeps all.
        require_ball: skip frames whose ball is not present/visible enough to
            locate (needed for the possession heuristic and ball_m).
        root: PFF root override.

    Velocity is finite-differenced per (team, jersey) against the previous KEPT
    frame (so dt respects the stride). Players missing from the prior kept frame
    get vx=vy=0 (position-only fallback). Velocity is computed in RAW (unoriented)
    coordinates then sign-flipped with the orientation, which is correct because
    orientation is a pure sign flip on both axes.
    """
    fpath = _pff_root(root) / "Tracking Data" / f"{match_id}.jsonl.bz2"
    meta = load_metadata(match_id, root)
    roster = load_roster(match_id, root)
    home_id = str(meta["homeTeam"]["id"])
    away_id = str(meta["awayTeam"]["id"])
    home_name = meta["homeTeam"]["name"]
    away_name = meta["awayTeam"]["name"]

    # Per-(team, jersey) previous kept-frame state for finite-diff velocity.
    # key -> (raw_x, raw_y, timestamp_s)
    prev: dict[tuple[str, int], tuple[float, float, float]] = {}

    def _roster_lookup(team_id: str, jersey: int) -> dict:
        info = roster.get((team_id, jersey))
        if info is None:
            tname = home_name if team_id == home_id else away_name
            return {"name": f"#{jersey}", "is_gk": False,
                    "team_name": tname, "team_id": team_id}
        return info

    n_lines = 0
    with bz2.open(fpath, "rt") as fh:
        for line in fh:
            n_lines += 1
            if limit is not None and n_lines > limit:
                break
            if (n_lines - 1) % sampling_stride != 0:
                continue
            rec = json.loads(line)
            period = int(rec.get("period", 0))
            if periods is not None and period not in periods:
                continue
            ts = float(rec.get("periodElapsedTime", 0.0))
            frame_num = int(rec.get("frameNum", n_lines))

            balls = rec.get("balls") or []
            if not balls:
                if require_ball:
                    continue
                ball_raw = None
            else:
                b = balls[0]
                if b.get("x") is None or b.get("y") is None:
                    if require_ball:
                        continue
                    ball_raw = None
                else:
                    ball_raw = np.array([float(b["x"]), float(b["y"])])
            if ball_raw is None:
                continue

            home_players = rec.get("homePlayers") or []
            away_players = rec.get("awayPlayers") or []
            if len(home_players) == 0 or len(away_players) == 0:
                continue

            sign = attacking_sign_for_home(meta, period)  # raw -> home-attacks-+x

            # Collect raw positions for the possession heuristic (raw frame; sign
            # does not affect nearest-to-ball distances).
            def _stack(plist):
                if not plist:
                    return np.zeros((0, 2))
                return np.array([[float(p.get("x", 0.0)), float(p.get("y", 0.0))]
                                 for p in plist])

            home_xy = _stack(home_players)
            away_xy = _stack(away_players)
            poss_side = _possession_team(home_xy, away_xy, ball_raw)

            # Orientation + attacker designation.
            # Default: the IN-POSSESSION team attacks +x (`sign` makes HOME attack
            # +x; flip if away has the ball). For a HERO CLIP we instead LOCK both
            # to a chosen team for the whole window, so the noisy nearest-to-ball
            # possession heuristic can't mirror the field or invert the surface.
            if lock_attack_team_id is not None:
                lock_home = str(lock_attack_team_id) == home_id
                orient_sign = sign if lock_home else -sign
                home_attacking = lock_home
            else:
                orient_sign = sign if poss_side == "home" else -sign
                home_attacking = poss_side == "home"
            in_poss_team_id = home_id if home_attacking else away_id
            in_poss_team = home_name if home_attacking else away_name

            rows: list[np.ndarray] = []
            idents: list[PlayerIdentity] = []

            for plist, team_id, team_attacking in (
                (home_players, home_id, home_attacking),
                (away_players, away_id, not home_attacking),
            ):
                for p in plist:
                    try:
                        jersey = int(p["jerseyNum"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    rx = float(p.get("x", 0.0))
                    ry = float(p.get("y", 0.0))
                    key = (team_id, jersey)

                    # finite-diff velocity in RAW coords vs previous kept frame
                    pv = prev.get(key)
                    if pv is not None:
                        dt = ts - pv[2]
                        # Guard against period rollover / non-positive dt.
                        if dt > 1e-3:
                            vx_raw = (rx - pv[0]) / dt
                            vy_raw = (ry - pv[1]) / dt
                        else:
                            vx_raw = vy_raw = 0.0
                    else:
                        vx_raw = vy_raw = 0.0
                    vx_raw = float(np.clip(vx_raw, -VEL_CLAMP, VEL_CLAMP))
                    vy_raw = float(np.clip(vy_raw, -VEL_CLAMP, VEL_CLAMP))
                    prev[key] = (rx, ry, ts)

                    # Orient position + velocity (pure sign flip on both axes).
                    ox = rx * orient_sign
                    oy = ry * orient_sign
                    ovx = vx_raw * orient_sign
                    ovy = vy_raw * orient_sign

                    info = _roster_lookup(team_id, jersey)
                    is_gk = bool(info["is_gk"])
                    is_att = bool(team_attacking)

                    rows.append(np.array([
                        ox / HALF_LEN,   # x_norm
                        oy / HALF_WID,   # y_norm
                        ovx,             # vx (m/s)
                        ovy,             # vy (m/s)
                        1.0 if is_att else -1.0,  # is_attacking_side
                        1.0 if is_gk else 0.0,    # is_goalkeeper
                        0.0,             # has_possession (per-player; left 0)
                    ], dtype=np.float64))
                    idents.append(PlayerIdentity(
                        team=info["team_name"],
                        team_id=team_id,
                        name=info["name"],
                        jersey=jersey,
                        visibility=str(p.get("visibility", "")),
                        confidence=str(p.get("confidence", "")),
                        is_gk=is_gk,
                        is_attacking=is_att,
                    ))

            if not rows:
                continue
            players = np.vstack(rows)
            ball_m = np.array([ball_raw[0] * orient_sign,
                               ball_raw[1] * orient_sign])

            yield SpaceFrame(
                players=players,
                identities=idents,
                ball_m=ball_m,
                period=period,
                in_possession_team_id=in_poss_team_id,
                in_possession_team=in_poss_team,
                timestamp_s=ts,
                frame_num=frame_num,
            )


# ---------------------------------------------------------------------------
# Bounded validation / self-test
# ---------------------------------------------------------------------------
def _validate(match_id: str = "10503"):
    import time

    print("=" * 70)
    print(f"space_io READER VALIDATION — match {match_id} (BOUNDED)")
    print("=" * 70)

    meta = load_metadata(match_id)
    print(f"[meta] home={meta['homeTeam']['name']} ({meta['homeTeam']['id']})  "
          f"away={meta['awayTeam']['name']} ({meta['awayTeam']['id']})  "
          f"homeTeamStartLeft={meta['homeTeamStartLeft']}  fps={meta.get('fps')}")
    print(f"[meta] P1 home attacking sign = {attacking_sign_for_home(meta, 1)}  "
          f"P2 = {attacking_sign_for_home(meta, 2)}")

    # Bounded: stride 15 (~2 Hz), cap raw lines, period 1 only. ~80s budget.
    STRIDE = 15
    RAW_LIMIT = 9000  # ~5 min of raw frames; with stride 15 -> ~600 kept
    t0 = time.time()
    frames: list[SpaceFrame] = []
    n = 0
    for fr in read_match(match_id, sampling_stride=STRIDE, limit=RAW_LIMIT,
                         periods=(1,)):
        frames.append(fr)
        n += 1
        if n % 100 == 0:
            print(f"  ... kept {n} frames (t={fr.timestamp_s:.1f}s) "
                  f"[{time.time()-t0:.1f}s]", flush=True)
    dt = time.time() - t0
    print(f"[read] kept {len(frames)} frames in {dt:.1f}s "
          f"(stride={STRIDE}, raw_limit={RAW_LIMIT})", flush=True)

    if not frames:
        print("[FAIL] no frames read")
        return False, {}

    # --- pick a settled-possession mid frame ------------------------------
    fr = frames[len(frames) // 2]
    n_players = fr.players.shape[0]
    print(f"\n[frame] t={fr.timestamp_s:.1f}s period={fr.period} "
          f"in_possession={fr.in_possession_team} ({fr.in_possession_team_id})  "
          f"n_players={n_players}  ball_m=({fr.ball_m[0]:.1f},{fr.ball_m[1]:.1f})")

    # --- (a) names resolve via roster -------------------------------------
    unresolved = [idn for idn in fr.identities if idn.name.startswith("#")]
    names_ok = len(unresolved) == 0
    print(f"\n[check-names] unresolved (#jersey) identities: {len(unresolved)} "
          f"-> OK={names_ok}")

    # --- print 3-5 named players with oriented positions ------------------
    print("\n[sample] named players (oriented; +x = attacking direction):")
    sample_named: list[str] = []
    # Prefer attacking outfield players, sorted by x (most advanced first).
    att_rows = [(i, idn) for i, idn in enumerate(fr.identities)
                if idn.is_attacking and not idn.is_gk]
    att_rows.sort(key=lambda t: -fr.players[t[0], 0])
    for i, idn in att_rows[:5]:
        xm = fr.players[i, 0] * HALF_LEN
        ym = fr.players[i, 1] * HALF_WID
        spd = float(np.hypot(fr.players[i, 2], fr.players[i, 3]))
        print(f"   {idn.name:<22} {idn.team:<10} #{idn.jersey:<3} "
              f"x={xm:+6.1f} y={ym:+6.1f}  spd={spd:4.1f} m/s  "
              f"vis={idn.visibility:<9} gk={idn.is_gk}")
        sample_named.append(idn.name)

    # --- (b) possession sensible: nearest player to ball is in-possession --
    px = fr.players[:, 0] * HALF_LEN
    py = fr.players[:, 1] * HALF_WID
    d = np.hypot(px - fr.ball_m[0], py - fr.ball_m[1])
    nearest = int(np.argmin(d))
    nearest_att = fr.players[nearest, 4] > 0
    nearest_name = fr.identities[nearest].name
    print(f"\n[check-poss] nearest-to-ball: {nearest_name} "
          f"({fr.identities[nearest].team}) dist={d[nearest]:.2f}m "
          f"is_attacking={nearest_att} -> OK={bool(nearest_att)}")
    poss_ok = bool(nearest_att)

    # --- (c) orientation: the UNAMBIGUOUS signal is GK x. With possession
    # oriented attacking-+x, the DEFENDING team's goal (and thus its GK) sits at
    # +x (the target the attacker drives toward), and the ATTACKING team's own
    # GK sits at -x. (Outfield mean-x is a poor signal: in build-up the
    # in-possession team plays out from its own half at -x while the defending
    # block camps near its own goal at +x, so defending outfield mean-x can
    # legitimately exceed attacking outfield mean-x — informational only.)
    att_gk_means, def_gk_means = [], []
    att_out_means, def_out_means = [], []
    for f2 in frames:
        a = f2.players[:, 4] > 0
        g2 = f2.players[:, 5] > 0.5
        xx = f2.players[:, 0] * HALF_LEN
        if (a & g2).any():
            att_gk_means.append(float(xx[a & g2].mean()))
        if ((~a) & g2).any():
            def_gk_means.append(float(xx[(~a) & g2].mean()))
        o2 = ~g2
        if (a & o2).any():
            att_out_means.append(float(xx[a & o2].mean()))
        if ((~a) & o2).any():
            def_out_means.append(float(xx[(~a) & o2].mean()))
    agg_att_gk = float(np.mean(att_gk_means))
    agg_def_gk = float(np.mean(def_gk_means))
    agg_att = float(np.mean(att_out_means))
    agg_def = float(np.mean(def_out_means))
    print(f"\n[check-orient] AGGREGATE GK x over {len(frames)} frames: "
          f"ATTACKING GK mean-x={agg_att_gk:+.1f} (own goal, expect < 0)  "
          f"DEFENDING GK mean-x={agg_def_gk:+.1f} (attack target, expect > 0)")
    print(f"[check-orient] (info) outfield mean-x: attacking={agg_att:+.1f} "
          f"defending={agg_def:+.1f}")
    # Pass when the GKs straddle midfield in the right direction.
    orient_ok = agg_att_gk < 0.0 < agg_def_gk and (agg_def_gk - agg_att_gk) > 30.0

    # --- occlusion disclosure ---------------------------------------------
    vis_counts = {"VISIBLE": 0, "ESTIMATED": 0, "OTHER": 0}
    tot = 0
    for f2 in frames:
        for idn in f2.identities:
            tot += 1
            vis_counts[idn.visibility if idn.visibility in vis_counts else "OTHER"] += 1
    est_pct = 100.0 * vis_counts["ESTIMATED"] / max(tot, 1)
    print(f"\n[occlusion] over {tot} player-rows: "
          f"VISIBLE={vis_counts['VISIBLE']} "
          f"ESTIMATED={vis_counts['ESTIMATED']} ({est_pct:.1f}%) "
          f"OTHER={vis_counts['OTHER']}  (brief notes ~40.9% ESTIMATED)")

    # --- possession split sanity ------------------------------------------
    from collections import Counter
    pc = Counter(f2.in_possession_team for f2 in frames)
    print(f"[poss-split] frames by in-possession team: {dict(pc)}")

    all_ok = names_ok and poss_ok and orient_ok
    print("\n" + "=" * 70)
    print(f"VALIDATION: names={names_ok} poss={poss_ok} orient={orient_ok} "
          f"-> ALL OK={all_ok}")
    print("=" * 70)
    return all_ok, {
        "sample_named": sample_named,
        "names_ok": names_ok,
        "poss_ok": poss_ok,
        "orient_ok": orient_ok,
        "agg_att_x": agg_att,
        "agg_def_x": agg_def,
        "est_pct": est_pct,
        "n_frames": len(frames),
        "in_possession_sample": fr.in_possession_team,
    }


if __name__ == "__main__":
    mid = sys.argv[1] if len(sys.argv) > 1 else "10503"
    ok, _ = _validate(mid)
    sys.exit(0 if ok else 1)
