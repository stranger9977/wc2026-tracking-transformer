"""Pre-compute curated "chemistry moves" for the Whiteboard tab.

For each featured Interactive Plays clip we already have rendered in
``research/site/data/clips/*.json``:

1. Re-load the PFF tracking frames for the clip window (the on-disk clip JSONs
   carry summaries — top-attended + p_score/p_concede — but NOT the raw
   per-player tensor we need to perturb).
2. Match each tensor slot to a real PFF ``playerId`` so candidate moves can
   refer to actual people ("Mac Allister drops in the half-space"), not slot
   indices.
3. Generate candidate counterfactual moves anchored to the named chemistry
   mechanisms in ``research/site/data/chemistry_concepts.json`` (Meat Wall,
   Third-Man Triangle, Decoy Run, Pin the Fullback, …). For each featured
   play we pick the 2-3 mechanisms that fit and instantiate them as
   concrete drags, then supplement with a small systematic sweep on the
   most-attended off-ball players in case a mechanism move doesn't fire.
4. Run the frame-VAEP transformer on the perturbed tensors and compute
   per-frame Δ P(score) and Δ P(concede) vs the baseline.
5. Rank candidates with a preference for mechanism-tagged moves and keep
   the 5-8 most narratively interesting per play. Write everything to
   ``research/site/data/whiteboard_moves.json``.

The browser-side Whiteboard UI replays these pre-computed traces so users can
"feel" what chemistry is, even without ONNX runtime in the loop.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.pff import load_pff_match
from wc2026_tracking_transformer.data.schema import PITCH_LENGTH_M, PITCH_WIDTH_M
from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule

PFF_ROOT_DEFAULT = "/Users/nick/Desktop/drive-download-20260518T234612Z-3-001"
HL = PITCH_LENGTH_M / 2.0
HW = PITCH_WIDTH_M / 2.0


# ----------------------------------------------------------------------------
# PFF metadata helpers
# ----------------------------------------------------------------------------


def _pff_root() -> Path:
    return Path(os.environ.get("PFF_ROOT", PFF_ROOT_DEFAULT))


def _load_meta(match_id: str) -> dict:
    raw = json.loads((_pff_root() / "Metadata" / f"{match_id}.json").read_text())
    if isinstance(raw, list):
        raw = raw[0]
    return raw


def _load_events(match_id: str) -> list[dict]:
    return json.loads((_pff_root() / "Event Data" / f"{match_id}.json").read_text())


def _load_rosters(match_id: str) -> list[dict]:
    return json.loads((_pff_root() / "Rosters" / f"{match_id}.json").read_text())


def _player_directory(rosters: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for r in rosters:
        p = r.get("player") or {}
        team = r.get("team") or {}
        pid = p.get("id")
        if not pid:
            continue
        try:
            pid_i = int(pid)
        except Exception:
            continue
        out[pid_i] = {
            "name": p.get("nickname")
            or f"{p.get('firstName','')} {p.get('lastName','')}".strip(),
            "position": r.get("positionGroupType"),
            "team_id": str(team.get("id")),
            "jersey": r.get("shirtNumber"),
        }
    return out


def _build_event_index(events: list[dict]) -> list[dict]:
    out = []
    for ev in events:
        ge = ev.get("gameEvents") or {}
        pe = ev.get("possessionEvents") or {}
        period = int(ge.get("period") or 1)
        clock = float(pe.get("gameClock") or ge.get("startGameClock") or 0)
        if period == 1:
            period_rel_ms = int(clock * 1000)
        else:
            period_rel_ms = int((clock - 2700) * 1000)
        out.append(
            {
                "period": period,
                "period_rel_ms": period_rel_ms,
                "homePlayers": ev.get("homePlayers") or [],
                "awayPlayers": ev.get("awayPlayers") or [],
            }
        )
    return out


def _slot_to_player_id(frame_tensor: np.ndarray, event_snapshot: dict) -> list[int | None]:
    """Greedy nearest-neighbour match: each slot (in metre coords) to a PFF playerId."""
    slot_xy = frame_tensor[:22, :2].copy()
    slot_xy[:, 0] *= HL
    slot_xy[:, 1] *= HW
    all_players = []
    for p in (event_snapshot.get("homePlayers") or []) + (event_snapshot.get("awayPlayers") or []):
        if p.get("x") is None or p.get("y") is None or not p.get("playerId"):
            continue
        all_players.append((float(p["x"]), float(p["y"]), int(p["playerId"])))
    out: list[int | None] = [None] * 22
    used: set[int] = set()
    for slot in range(22):
        sx, sy = slot_xy[slot]
        best = None
        best_d = 1e18
        for px, py, pid in all_players:
            if pid in used:
                continue
            d = (px - sx) ** 2 + (py - sy) ** 2
            if d < best_d:
                best = pid
                best_d = d
        if best is not None:
            out[slot] = best
            used.add(best)
    return out


# ----------------------------------------------------------------------------
# Clip bundle (per-play state)
# ----------------------------------------------------------------------------


@dataclass
class ClipBundle:
    label: str
    match_id: str
    period: int
    start_s: float
    end_s: float
    home_team_id: str
    home_short: str
    away_short: str
    home_color: str
    away_color: str
    home_team_name: str
    away_team_name: str
    player_dir: dict[int, dict]
    tensors: np.ndarray  # (T, 23, 7)
    slot_pid_per_frame: list[list[int | None]]  # T × 22
    timestamps_ms: list[int]
    p_score_base: np.ndarray
    p_concede_base: np.ndarray
    attn_ball_base: np.ndarray  # (T, 22) — mean over layers/heads, ball→player
    in_possession_team_id_per_frame: list[str | None]


def _device() -> torch.device:
    # CPU is plenty fast (~0.2 ms/frame at this scale) and avoids MPS edge
    # cases when stitching repeated forward calls of slightly different shapes.
    return torch.device("cpu")


def load_clip_bundle(*, clip_meta: dict, lit: FrameVaepLitModule, stride: int = 6) -> ClipBundle:
    label = clip_meta["label"]
    period = int(clip_meta.get("period") or 1)

    detail = json.loads(
        (REPO / "research" / "site" / "data" / "clips" / f"{label}.json").read_text()
    )
    # Prefer the per-clip detail JSON's match_id over the index — the index has a
    # couple of legacy mismatches (e.g. japan-spain-doan in index says 10510 but
    # the actual rendered clip is from match 3854; argentina-croatia-julian
    # index says 10515 but is from 10514).
    match_id = str(detail.get("match_id") or clip_meta["match"])
    start_s = float(detail["start_s"])
    end_s = float(detail["end_s"])
    home = detail["home_team"]
    away = detail["away_team"]

    meta = _load_meta(match_id)
    home_team_id = str(meta.get("homeTeam", {}).get("id", ""))
    home_team_name = meta.get("homeTeam", {}).get("name", "Home")
    away_team_name = meta.get("awayTeam", {}).get("name", "Away")

    rosters = _load_rosters(match_id)
    player_dir = _player_directory(rosters)

    events = _load_events(match_id)
    ev_idx = _build_event_index(events)

    frames_all = list(load_pff_match(match_id, sampling_stride=stride))
    clip_frames = [
        f for f in frames_all if f.period == period and start_s <= f.timestamp_ms / 1000.0 <= end_s
    ]
    if not clip_frames:
        raise SystemExit(f"no frames in window for {label}")

    tensors = batch_frames(clip_frames)
    timestamps = [int(f.timestamp_ms) for f in clip_frames]
    in_poss = [f.in_possession_team_id for f in clip_frames]

    # Slot→pid per-frame: nearest event in time within this match/period.
    slot_pid_per_frame: list[list[int | None]] = []
    for i, f in enumerate(clip_frames):
        best_ev = None
        best_dt = 10**9
        for ev in ev_idx:
            if ev["period"] != f.period:
                continue
            dt = abs(ev["period_rel_ms"] - f.timestamp_ms)
            if dt < best_dt:
                best_dt = dt
                best_ev = ev
        slot_pid_per_frame.append(_slot_to_player_id(tensors[i], best_ev or {}))

    # Baseline inference
    device = _device()
    lit_dev = lit.to(device).eval()
    x = torch.from_numpy(tensors).to(device)
    with torch.no_grad():
        enc, attn = lit_dev.encode_with_attention(x)
        ps = torch.sigmoid(lit_dev.score_head(enc)).cpu().numpy()
        pc = torch.sigmoid(lit_dev.concede_head(enc)).cpu().numpy()
        attn_mean = attn.mean(dim=(1, 2)).cpu().numpy()  # (T, 23, 23)
        attn_ball = attn_mean[:, 22, :22]
        attn_ball = attn_ball / np.maximum(attn_ball.sum(axis=1, keepdims=True), 1e-9)

    return ClipBundle(
        label=label,
        match_id=match_id,
        period=period,
        start_s=start_s,
        end_s=end_s,
        home_team_id=home_team_id,
        home_short=home.get("short", "HOM"),
        away_short=away.get("short", "AWA"),
        home_color=home.get("color", "#5eead4"),
        away_color=away.get("color", "#f87171"),
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        player_dir=player_dir,
        tensors=tensors,
        slot_pid_per_frame=slot_pid_per_frame,
        timestamps_ms=timestamps,
        p_score_base=ps,
        p_concede_base=pc,
        attn_ball_base=attn_ball,
        in_possession_team_id_per_frame=in_poss,
    )


# ----------------------------------------------------------------------------
# Counterfactual application
# ----------------------------------------------------------------------------


def _slot_index_each_frame(bundle: ClipBundle, pid: int) -> list[int | None]:
    """Per-frame slot index for a given player_id."""
    out: list[int | None] = []
    for frame_pids in bundle.slot_pid_per_frame:
        s_match = None
        for s, p in enumerate(frame_pids):
            if p == pid:
                s_match = s
                break
        out.append(s_match)
    return out


def apply_move(bundle: ClipBundle, shifts: list[dict]) -> np.ndarray:
    """Return a copy of the tensor stack with the given shifts applied.

    Each shift is {"player_id": int, "dx_m": float, "dy_m": float}.

    The shift is applied identically on every frame the player is present
    (step-function from the start of the clip). dx is in metres along the
    long axis (positive = attacking direction in the "attacking-left-to-right"
    normalization the loader produces); dy is in metres across the short axis.
    """
    tensors = bundle.tensors.copy()
    T = tensors.shape[0]
    for shift in shifts:
        pid = shift["player_id"]
        dx_m = float(shift["dx_m"])
        dy_m = float(shift["dy_m"])
        dx_n = dx_m / HL
        dy_n = dy_m / HW
        slots = _slot_index_each_frame(bundle, pid)
        for t in range(T):
            s = slots[t]
            if s is None:
                continue
            tensors[t, s, 0] = float(np.clip(tensors[t, s, 0] + dx_n, -1.05, 1.05))
            tensors[t, s, 1] = float(np.clip(tensors[t, s, 1] + dy_n, -1.05, 1.05))
    return tensors


def run_inference(lit: FrameVaepLitModule, tensors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    device = _device()
    x = torch.from_numpy(tensors.astype(np.float32)).to(device)
    with torch.no_grad():
        enc = lit.backbone(x)
        ps = torch.sigmoid(lit.score_head(enc)).cpu().numpy()
        pc = torch.sigmoid(lit.concede_head(enc)).cpu().numpy()
    return ps, pc


# ----------------------------------------------------------------------------
# Mechanism-driven move generation
# ----------------------------------------------------------------------------


def _peak_frame(bundle: ClipBundle) -> int:
    return int(np.argmax(bundle.p_score_base))


def _player_xy(bundle: ClipBundle, pid: int, t: int) -> tuple[float, float] | None:
    slots = _slot_index_each_frame(bundle, pid)
    s = slots[t]
    if s is None:
        return None
    return (
        float(bundle.tensors[t, s, 0]) * HL,
        float(bundle.tensors[t, s, 1]) * HW,
    )


def _ranked_offball_players(bundle: ClipBundle, *, team: str = "any", k: int = 8) -> list[int]:
    """Top players (by attention in a window around peak), GK excluded.

    team: "home", "away", or "any" — relative to bundle.home_team_id.
    """
    T = bundle.tensors.shape[0]
    if T == 0:
        return []
    peak = _peak_frame(bundle)
    lo = max(0, peak - 12)
    hi = min(T, peak + 12)
    attn = bundle.attn_ball_base[lo:hi].mean(axis=0)
    slot_pids_peak = bundle.slot_pid_per_frame[peak]
    is_gk = bundle.tensors[peak, :22, 5] > 0.5
    order = np.argsort(-attn).tolist()
    out: list[int] = []
    for s in order:
        if is_gk[s]:
            continue
        pid = slot_pids_peak[s]
        if pid is None:
            continue
        info = bundle.player_dir.get(pid) or {}
        tid = info.get("team_id")
        if team == "home" and tid != bundle.home_team_id:
            continue
        if team == "away" and tid == bundle.home_team_id:
            continue
        if pid in out:
            continue
        out.append(pid)
        if len(out) >= k:
            break
    return out


def _player_by_position(bundle: ClipBundle, *, position: str, team: str = "any") -> list[int]:
    """All player_ids matching a positionGroupType prefix (e.g. 'D', 'M', 'F', 'GK').

    Position groups in PFF rosters: GK, D (defender), M (midfielder), F (forward).
    Returns all players matching plus the lone GK if requested.
    """
    out: list[int] = []
    for pid, info in bundle.player_dir.items():
        tid = info.get("team_id")
        if team == "home" and tid != bundle.home_team_id:
            continue
        if team == "away" and tid == bundle.home_team_id:
            continue
        pos = info.get("position") or ""
        if pos.upper().startswith(position.upper()):
            out.append(pid)
    return out


def _surname(bundle: ClipBundle, pid: int) -> str:
    info = bundle.player_dir.get(pid) or {}
    name = (info.get("name") or "").strip()
    return name.split()[-1] if name else f"#{pid}"


def _name(bundle: ClipBundle, pid: int) -> str:
    info = bundle.player_dir.get(pid) or {}
    return (info.get("name") or f"player {pid}").strip()


def _which_team_in_possession(bundle: ClipBundle) -> str:
    """Pick the team holding possession on most frames in the second half of the clip.

    Returns "home" or "away".
    """
    T = bundle.tensors.shape[0]
    lo = max(0, T // 2)
    home = 0
    away = 0
    for t in range(lo, T):
        tid = bundle.in_possession_team_id_per_frame[t]
        if tid is None:
            continue
        if tid == bundle.home_team_id:
            home += 1
        else:
            away += 1
    return "home" if home >= away else "away"


@dataclass
class Mechanism:
    id: str
    name: str
    narrative_template: str


def _load_mechanism_index() -> dict[str, Mechanism]:
    path = REPO / "research" / "site" / "data" / "chemistry_concepts.json"
    raw = json.loads(path.read_text())
    out: dict[str, Mechanism] = {}
    for m in raw.get("mechanisms", []):
        out[m["id"]] = Mechanism(
            id=m["id"],
            name=m["name"],
            narrative_template=m.get("whiteboard_counterfactual") or m.get("what_it_is") or "",
        )
    return out


# ----------------------------------------------------------------------------
# Per-play mechanism plans
# ----------------------------------------------------------------------------
#
# Each plan returns a list of candidate moves. A candidate dict has:
#   {
#     "mechanism_id": str | None,
#     "key":          str (unique within the play),
#     "label":        str (short headline for the card),
#     "narrative":    str (1-2 sentence prose),
#     "shifts":       list[{player_id, dx_m, dy_m}],
#   }
# Candidates may use functions like `_ranked_offball_players` to pick concrete
# pids at runtime, so they're robust to per-match roster variation.
# ----------------------------------------------------------------------------


def _plan_third_man_triangle(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """The third-man triangle: A passes to B, B's first-time pass releases C.

    Operationalization: take the top-3 attended in-possession players (these
    are the model's A/B/C in time-attention order). Test two perturbations:
      (i)  Pull C 5 m onto the A→B line — does P(score) drop?
      (ii) Push B 3 m further from A — does the through-ball lane close?
    """
    poss = _which_team_in_possession(bundle)
    targets = _ranked_offball_players(bundle, team=poss, k=4)
    if len(targets) < 3:
        return []
    A, B, C = targets[0], targets[1], targets[2]
    peak = _peak_frame(bundle)
    a_xy = _player_xy(bundle, A, peak)
    b_xy = _player_xy(bundle, B, peak)
    c_xy = _player_xy(bundle, C, peak)
    out: list[dict] = []
    if a_xy and b_xy and c_xy:
        # (i) project C onto AB line, take 5m of that delta
        ax, ay = a_xy
        bx, by = b_xy
        cx, cy = c_xy
        dx, dy = bx - ax, by - ay
        L = max(1e-6, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / L, dy / L
        # Foot of perpendicular from C onto AB
        t_along = (cx - ax) * ux + (cy - ay) * uy
        fx, fy = ax + t_along * ux, ay + t_along * uy
        toward_x, toward_y = fx - cx, fy - cy
        d_to_line = max(1e-3, (toward_x * toward_x + toward_y * toward_y) ** 0.5)
        scale = min(5.0, d_to_line) / d_to_line
        out.append(
            {
                "mechanism_id": mech.id,
                "key": "triangle_C_on_line",
                "label": f"{_surname(bundle, C)} drifts onto the {_surname(bundle, A)}–{_surname(bundle, B)} line",
                "narrative": (
                    f"The third-man triangle says C's value is in being behind the "
                    f"defenders' eye-line. Pull {_surname(bundle, C)} 5 m onto the "
                    f"{_surname(bundle, A)}–{_surname(bundle, B)} passing lane and the "
                    "first-time release disappears — the off-ball geometry is doing the work."
                ),
                "shifts": [
                    {
                        "player_id": C,
                        "dx_m": float(toward_x * scale),
                        "dy_m": float(toward_y * scale),
                    }
                ],
            }
        )
    out.append(
        {
            "mechanism_id": mech.id,
            "key": "triangle_B_further",
            "label": f"{_surname(bundle, B)} drops 4 m further from {_surname(bundle, A)}",
            "narrative": (
                f"If {_surname(bundle, B)} is too far, the bounce loses pace and the "
                f"third-man release to {_surname(bundle, C)} never happens. "
                "The model's P(score) tells you how tight the triangle has to be."
            ),
            "shifts": [{"player_id": B, "dx_m": -4.0, "dy_m": 0.0}],
        }
    )
    return out


def _plan_decoy_run(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """The decoy run: freeze a likely off-ball runner in place.

    We can't literally stop motion frame-by-frame here without rewriting
    velocity, but we approximate "freeze in place" by snapping the chosen
    decoy back to their start-of-clip position throughout the play. Pick
    the top-attended forward / wide attacker on the in-possession team.
    """
    poss = _which_team_in_possession(bundle)
    forwards = _player_by_position(bundle, position="F", team=poss)
    attended = _ranked_offball_players(bundle, team=poss, k=8)
    decoys = [p for p in attended if p in forwards]
    if not decoys:
        decoys = attended[:1]
    if not decoys:
        return []
    decoy = decoys[0]
    # Approximation: shift the decoy 12 m back toward the centre circle. This
    # blunts the run's downstream stretch on the defence.
    return [
        {
            "mechanism_id": mech.id,
            "key": f"decoy_freeze_{decoy}",
            "label": f"{_surname(bundle, decoy)} doesn't make the run",
            "narrative": (
                f"Hold {_surname(bundle, decoy)} 12 m back instead of sprinting "
                "into the channel. The cleanest off-ball chemistry test we have: "
                "if the lane closes for everyone else, the run was load-bearing."
            ),
            "shifts": [{"player_id": decoy, "dx_m": -12.0, "dy_m": 0.0}],
        }
    ]


def _plan_the_pin(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """The Pin: wide attacker pinches narrow → fullback steps out → channel reopens.

    Pull the in-possession team's most-attended wide forward 6 m central.
    """
    poss = _which_team_in_possession(bundle)
    attended = _ranked_offball_players(bundle, team=poss, k=6)
    if not attended:
        return []
    peak = _peak_frame(bundle)
    # Pick the most attended player who is wide (|y| > 12 m) at the peak frame.
    wide_pick = None
    for pid in attended:
        xy = _player_xy(bundle, pid, peak)
        if xy and abs(xy[1]) > 12.0:
            wide_pick = pid
            break
    if wide_pick is None:
        wide_pick = attended[0]
    xy = _player_xy(bundle, wide_pick, peak)
    if xy is None:
        return []
    pinch = -np.sign(xy[1]) * 6.0 if abs(xy[1]) > 0.5 else 6.0
    return [
        {
            "mechanism_id": mech.id,
            "key": f"pin_pinch_{wide_pick}",
            "label": f"{_surname(bundle, wide_pick)} pinches narrow",
            "narrative": (
                f"The pin says {_surname(bundle, wide_pick)}'s threat is fixing the "
                f"fullback wide. Pinch them 6 m central and the fullback no longer "
                "has a reason to stay outside — the channel reopens for the opposite side."
            ),
            "shifts": [{"player_id": wide_pick, "dx_m": 0.0, "dy_m": float(pinch)}],
        }
    ]


def _plan_overlap_handoff(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """Overlap handoff: toggle the fullback from outside-run to inside-run.

    Take the in-possession team's wide defender (FB) and the wide forward;
    swap their lateral position by pulling FB outside +5 m and winger inside −5 m.
    """
    poss = _which_team_in_possession(bundle)
    defs = _player_by_position(bundle, position="D", team=poss)
    fwds = _player_by_position(bundle, position="F", team=poss)
    if not defs or not fwds:
        return []
    peak = _peak_frame(bundle)
    # Pick the FB with largest |y| at peak (most wide); pick the wide FW similarly.
    def _widest(pids: list[int]) -> int | None:
        best = None
        best_y = -1
        for pid in pids:
            xy = _player_xy(bundle, pid, peak)
            if xy and abs(xy[1]) > best_y:
                best_y = abs(xy[1])
                best = pid
        return best

    fb = _widest(defs)
    fw = _widest(fwds)
    if fb is None or fw is None or fb == fw:
        return []
    fb_xy = _player_xy(bundle, fb, peak)
    fw_xy = _player_xy(bundle, fw, peak)
    if fb_xy is None or fw_xy is None:
        return []
    if np.sign(fb_xy[1]) != np.sign(fw_xy[1]):
        # Pick a forward on the same side as fb
        for fcand in fwds:
            xy = _player_xy(bundle, fcand, peak)
            if xy and np.sign(xy[1]) == np.sign(fb_xy[1]):
                fw = fcand
                fw_xy = xy
                break
    side = float(np.sign(fb_xy[1] or 1.0))
    return [
        {
            "mechanism_id": mech.id,
            "key": f"overlap_{fb}_{fw}",
            "label": f"{_surname(bundle, fb)} overlaps outside {_surname(bundle, fw)}",
            "narrative": (
                f"Push {_surname(bundle, fb)} 6 m higher and 4 m wider — a true overlap. "
                f"{_surname(bundle, fw)} can underlap inside. Does the cross-or-cutback "
                "shape change the predicted xT? That is the handoff doing its work."
            ),
            "shifts": [
                {"player_id": fb, "dx_m": 6.0, "dy_m": 4.0 * side},
                {"player_id": fw, "dx_m": 0.0, "dy_m": -3.0 * side},
            ],
        }
    ]


def _plan_press_trap(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """Press trap: pull the bait CB further from the box → press commits less."""
    poss = _which_team_in_possession(bundle)
    defs = _player_by_position(bundle, position="D", team=poss)
    if not defs:
        return []
    peak = _peak_frame(bundle)
    # Pick the CB with the smallest x at peak (i.e. furthest from attacking goal — the bait).
    best = None
    best_x = 1e9
    for pid in defs:
        xy = _player_xy(bundle, pid, peak)
        if xy and xy[0] < best_x:
            best_x = xy[0]
            best = pid
    if best is None:
        return []
    return [
        {
            "mechanism_id": mech.id,
            "key": f"press_trap_{best}",
            "label": f"{_surname(bundle, best)} steps 8 m further from the box",
            "narrative": (
                "Press traps need the bait close to danger. Move "
                f"{_surname(bundle, best)} 8 m further up — the press commits less, the "
                "vertical option closes. Tests whether geometry of the bait is "
                "load-bearing or it's just the player's skill."
            ),
            "shifts": [{"player_id": best, "dx_m": 8.0, "dy_m": 0.0}],
        }
    ]


def _plan_gegenpress_swarm(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """Gegenpress swarm: pull one of the off-ball pressers 10 m away.

    We approximate this from the *opposite* team's perspective (the side
    that just lost the ball / is pressing) — pick their top-attended player
    near the ball and slide them away.
    """
    poss = _which_team_in_possession(bundle)
    other = "home" if poss == "away" else "away"
    attended = _ranked_offball_players(bundle, team=other, k=4)
    if not attended:
        return []
    presser = attended[0]
    return [
        {
            "mechanism_id": mech.id,
            "key": f"gegenpress_break_{presser}",
            "label": f"{_surname(bundle, presser)} arrives 10 m late to the press",
            "narrative": (
                f"Move {_surname(bundle, presser)} 10 m further from the ball at the "
                "turnover. If the opponent's escape probability jumps, swarm compactness "
                "was the chemistry — not any one tackler."
            ),
            "shifts": [{"player_id": presser, "dx_m": -7.0, "dy_m": 7.0}],
        }
    ]


def _plan_positional_rotations(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """Positional rotations: force inside-FB to stay wide."""
    poss = _which_team_in_possession(bundle)
    defs = _player_by_position(bundle, position="D", team=poss)
    if not defs:
        return []
    peak = _peak_frame(bundle)
    # Pick the FB closest to the centre at peak (most likely already inverted)
    best = None
    best_y = 1e9
    for pid in defs:
        xy = _player_xy(bundle, pid, peak)
        if xy and abs(xy[1]) < best_y:
            best_y = abs(xy[1])
            best = pid
    if best is None:
        return []
    xy = _player_xy(bundle, best, peak)
    if xy is None:
        return []
    side = float(np.sign(xy[1] or 1.0))
    return [
        {
            "mechanism_id": mech.id,
            "key": f"rotation_{best}",
            "label": f"{_surname(bundle, best)} stays wide instead of rotating in",
            "narrative": (
                f"Force {_surname(bundle, best)} 10 m wider — refuse the inversion. "
                "Does the central midfielder step into the half-space anyway, or does "
                "the channel sit empty? Tests the rotation rule vs. pure habit."
            ),
            "shifts": [{"player_id": best, "dx_m": 0.0, "dy_m": 10.0 * side}],
        }
    ]


def _plan_meat_wall(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """Meat wall (corner only): drag the keeper-screener 5m wide.

    We don't actually have corner-kick clips in this set, but we still
    expose the move plumbing so future clips can drop in.
    """
    # No corner among the current featured clips — return [].
    return []


def _plan_near_post_flick(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    return []  # ditto


def _plan_short_corner(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    return []  # ditto


def _plan_blind_pass(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """Move the receiver 5m → does the through-ball still work?"""
    poss = _which_team_in_possession(bundle)
    attended = _ranked_offball_players(bundle, team=poss, k=5)
    if not attended:
        return []
    receiver = attended[0]
    return [
        {
            "mechanism_id": mech.id,
            "key": f"blind_pass_{receiver}",
            "label": f"{_surname(bundle, receiver)} starts 5 m off the pre-scanned position",
            "narrative": (
                f"Slide {_surname(bundle, receiver)} 5 m sideways at the start of the "
                "sequence. If the passer pre-scanned where the receiver *was* about to "
                "be, breaking that geometry should kill the through-ball."
            ),
            "shifts": [{"player_id": receiver, "dx_m": 0.0, "dy_m": 5.0}],
        }
    ]


def _plan_rest_defense(bundle: ClipBundle, mech: Mechanism) -> list[dict]:
    """Push the rest-defense holding midfielder 8m forward → counter risk rises."""
    poss = _which_team_in_possession(bundle)
    mids = _player_by_position(bundle, position="M", team=poss)
    if not mids:
        return []
    peak = _peak_frame(bundle)
    # Deepest midfielder = smallest x at peak.
    best = None
    best_x = 1e9
    for pid in mids:
        xy = _player_xy(bundle, pid, peak)
        if xy and xy[0] < best_x:
            best_x = xy[0]
            best = pid
    if best is None:
        return []
    return [
        {
            "mechanism_id": mech.id,
            "key": f"rest_defense_{best}",
            "label": f"{_surname(bundle, best)} pushes 10 m higher (no rest-defense anchor)",
            "narrative": (
                f"Pull {_surname(bundle, best)} out of the rest-defense slot, 10 m higher. "
                "Watch P(concede) climb — the anchor was deterring a counter even without "
                "touching the ball. That's chemistry as *prevention*."
            ),
            "shifts": [{"player_id": best, "dx_m": 10.0, "dy_m": 0.0}],
        }
    ]


# Mechanism dispatch.
PLANNERS = {
    "third_man_triangle": _plan_third_man_triangle,
    "decoy_run": _plan_decoy_run,
    "the_pin": _plan_the_pin,
    "overlap_underlap": _plan_overlap_handoff,
    "press_trap": _plan_press_trap,
    "gegenpress_swarm": _plan_gegenpress_swarm,
    "positional_rotations": _plan_positional_rotations,
    "meat_wall": _plan_meat_wall,
    "near_post_flick_on": _plan_near_post_flick,
    "short_corner_overload": _plan_short_corner,
    "blind_pass": _plan_blind_pass,
    "rest_defense": _plan_rest_defense,
}


# Editorial: which mechanisms fit each clip. Order is preference order
# (we'll trim if the inference rankings let us; otherwise keep the first few).
PLAY_MECHANISM_PLANS: dict[str, list[str]] = {
    # Argentina build-up Mac Allister → Messi → Di María on the third goal.
    "argentina-france-di-maria": [
        "third_man_triangle",
        "decoy_run",
        "the_pin",
        "rest_defense",
        "overlap_underlap",
    ],
    # Mbappé's volley off a fast France break. Defensive/counter mechanisms.
    "argentina-france-mbappe-volley": [
        "rest_defense",
        "gegenpress_swarm",
        "the_pin",
        "decoy_run",
    ],
    # 20-pass Dutch build → Memphis goal. Rotations + third-man.
    "netherlands-usa-memphis": [
        "positional_rotations",
        "third_man_triangle",
        "blind_pass",
        "rest_defense",
        "overlap_underlap",
    ],
    # Spain's press, Japan's recover — Doan's strike. Press dynamics.
    "japan-spain-doan": [
        "press_trap",
        "gegenpress_swarm",
        "decoy_run",
        "rest_defense",
    ],
    # Álvarez beats three on a long carry. Decoy + pin + overlap.
    "argentina-croatia-julian": [
        "decoy_run",
        "the_pin",
        "overlap_underlap",
        "rest_defense",
    ],
}


# ----------------------------------------------------------------------------
# Systematic supplement (only used to fill out cards when mechanisms don't fire)
# ----------------------------------------------------------------------------


SHIFT_PRIMITIVES = [
    ("push_higher", (10.0, 0.0), "pushes 10 m higher"),
    ("drop_deeper", (-10.0, 0.0), "drops 10 m deeper"),
    ("drift_wide", (0.0, 8.0), "drifts 8 m wider"),
    ("pinch_in", (0.0, -8.0), "pinches 8 m central"),
]


def _supplement_moves(bundle: ClipBundle, n_each: int = 1) -> list[dict]:
    """For the top 3 off-ball attended players, propose a small systematic sweep."""
    out: list[dict] = []
    poss = _which_team_in_possession(bundle)
    targets = _ranked_offball_players(bundle, team=poss, k=3)
    for pid in targets:
        for key, (dx, dy), copy in SHIFT_PRIMITIVES[: n_each * 2]:
            out.append(
                {
                    "mechanism_id": None,
                    "key": f"sup_{pid}_{key}",
                    "label": f"{_surname(bundle, pid)} {copy}",
                    "narrative": (
                        f"Free-form perturbation (no named mechanism). Surface this if "
                        "the curated mechanism moves all fall below the |Δ net| floor."
                    ),
                    "shifts": [{"player_id": pid, "dx_m": dx, "dy_m": dy}],
                }
            )
    return out


# ----------------------------------------------------------------------------
# Scoring + selection
# ----------------------------------------------------------------------------


def evaluate_candidates(
    bundle: ClipBundle,
    lit: FrameVaepLitModule,
    mech_index: dict[str, Mechanism],
    top_k_keep: int = 7,
) -> list[dict]:
    plan_ids = PLAY_MECHANISM_PLANS.get(bundle.label, [])
    candidates: list[dict] = []
    for mid in plan_ids:
        mech = mech_index.get(mid)
        planner = PLANNERS.get(mid)
        if not mech or not planner:
            continue
        try:
            generated = planner(bundle, mech)
        except Exception as exc:  # noqa: BLE001
            print(f"  planner {mid} failed: {exc}")
            generated = []
        for g in generated:
            g["mechanism_name"] = mech.name
        candidates.extend(generated)

    # Supplement so we always have at least 8 to choose from
    candidates.extend(_supplement_moves(bundle, n_each=1))

    # Score them all
    print(f"  scoring {len(candidates)} candidates …")
    scored: list[dict] = []
    seen_keys: set[str] = set()
    for cand in candidates:
        if cand["key"] in seen_keys:
            continue
        if not cand["shifts"]:
            continue
        seen_keys.add(cand["key"])
        perturbed = apply_move(bundle, cand["shifts"])
        ps, pc = run_inference(lit, perturbed)
        d_score = ps - bundle.p_score_base
        d_concede = pc - bundle.p_concede_base
        d_net = d_score - d_concede
        scored.append(
            {
                "cand": cand,
                "ps": ps,
                "pc": pc,
                "d_score": d_score,
                "d_concede": d_concede,
                "d_net": d_net,
                "summary_d_score": float(d_score.mean()),
                "summary_d_concede": float(d_concede.mean()),
                "summary_d_net": float(d_net.mean()),
                "abs_net": float(np.abs(d_net.mean())),
            }
        )

    # Selection: prefer mechanism-tagged moves, then by |Δ net|.
    # Cap at 2 moves per (mechanism_id, primary_player) combo for diversity.
    def _selection_key(r: dict) -> tuple:
        is_mech = r["cand"].get("mechanism_id") is not None
        # Sort by (mechanism first, then by |abs_net| desc)
        return (0 if is_mech else 1, -r["abs_net"])

    scored.sort(key=_selection_key)

    chosen: list[dict] = []
    mech_seen: dict[str, int] = {}
    for r in scored:
        mid = r["cand"].get("mechanism_id") or "_none"
        if mech_seen.get(mid, 0) >= 2:
            continue
        # If no mechanism, require a meaningful effect
        if mid == "_none" and r["abs_net"] < 0.005:
            continue
        mech_seen[mid] = mech_seen.get(mid, 0) + 1
        chosen.append(r)
        if len(chosen) >= top_k_keep:
            break

    # If we still don't have enough, fall back to top |Δ net| from the pool
    if len(chosen) < 5:
        for r in scored:
            if r in chosen:
                continue
            chosen.append(r)
            if len(chosen) >= top_k_keep:
                break

    # Build output records
    out_moves: list[dict] = []
    for i, r in enumerate(chosen):
        cand = r["cand"]
        shift_meta = []
        for s in cand["shifts"]:
            pid = s["player_id"]
            info = bundle.player_dir.get(pid) or {}
            shift_meta.append(
                {
                    "player_id": pid,
                    "name": info.get("name") or f"player {pid}",
                    "position": info.get("position"),
                    "team_id": info.get("team_id"),
                    "dx_m": s["dx_m"],
                    "dy_m": s["dy_m"],
                }
            )
        out_moves.append(
            {
                "move_id": f"{bundle.label}__{cand['key']}",
                "rank": i + 1,
                "mechanism_id": cand.get("mechanism_id"),
                "mechanism_name": cand.get("mechanism_name"),
                "label": cand["label"],
                "narrative": cand["narrative"],
                "shifts": shift_meta,
                "summary": {
                    "mean_d_score": r["summary_d_score"],
                    "mean_d_concede": r["summary_d_concede"],
                    "mean_d_net": r["summary_d_net"],
                    "peak_abs_d_net": float(np.max(np.abs(r["d_net"]))),
                    "peak_d_net_frame": int(np.argmax(np.abs(r["d_net"]))),
                },
                "per_frame": {
                    "p_score": [round(float(v), 5) for v in r["ps"].tolist()],
                    "p_concede": [round(float(v), 5) for v in r["pc"].tolist()],
                    "d_score": [round(float(v), 5) for v in r["d_score"].tolist()],
                    "d_concede": [round(float(v), 5) for v in r["d_concede"].tolist()],
                    "d_net": [round(float(v), 5) for v in r["d_net"].tolist()],
                },
            }
        )
    return out_moves


def export_play_frames(bundle: ClipBundle) -> list[dict]:
    """Per-frame player+ball positions in metres, plus the baseline curves."""
    T = bundle.tensors.shape[0]
    out = []
    for t in range(T):
        players = []
        for s in range(22):
            x_m = float(bundle.tensors[t, s, 0]) * HL
            y_m = float(bundle.tensors[t, s, 1]) * HW
            pid = bundle.slot_pid_per_frame[t][s]
            info = bundle.player_dir.get(pid) if pid else None
            players.append(
                {
                    "slot": s,
                    "x": round(x_m, 2),
                    "y": round(y_m, 2),
                    "is_gk": bool(bundle.tensors[t, s, 5] > 0.5),
                    "player_id": pid,
                    "name": (info or {}).get("name") if info else None,
                    "position": (info or {}).get("position") if info else None,
                    "team_id": (info or {}).get("team_id") if info else None,
                }
            )
        ball_x_m = float(bundle.tensors[t, 22, 0]) * HL
        ball_y_m = float(bundle.tensors[t, 22, 1]) * HW
        out.append(
            {
                "t": t,
                "ts_ms": bundle.timestamps_ms[t],
                "players": players,
                "ball": {"x": round(ball_x_m, 2), "y": round(ball_y_m, 2)},
                "p_score": round(float(bundle.p_score_base[t]), 5),
                "p_concede": round(float(bundle.p_concede_base[t]), 5),
                "in_possession_team_id": bundle.in_possession_team_id_per_frame[t],
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="output/transformer_frame_vaep.ckpt")
    ap.add_argument("--out", default="research/site/data/whiteboard_moves.json")
    ap.add_argument("--top-k", type=int, default=7)
    args = ap.parse_args()

    idx = json.loads((REPO / "research" / "site" / "data" / "clips" / "index.json").read_text())
    mech_index = _load_mechanism_index()
    print(f"loaded {len(mech_index)} mechanisms from chemistry_concepts.json")

    lit = FrameVaepLitModule.load_from_checkpoint(args.ckpt, map_location="cpu").eval()

    plays_out: list[dict] = []
    for clip_meta in idx:
        print(f"\n[{clip_meta['label']}] loading frames …")
        bundle = load_clip_bundle(clip_meta=clip_meta, lit=lit)
        print(
            f"  {bundle.tensors.shape[0]} frames; "
            f"baseline P(score) [{bundle.p_score_base.min():.3f}, {bundle.p_score_base.max():.3f}], "
            f"P(concede) [{bundle.p_concede_base.min():.3f}, {bundle.p_concede_base.max():.3f}]"
        )
        moves = evaluate_candidates(bundle, lit, mech_index, top_k_keep=args.top_k)
        frames_payload = export_play_frames(bundle)
        plays_out.append(
            {
                "label": clip_meta["label"],
                "title": clip_meta["title"],
                "summary": clip_meta.get("summary"),
                "match_id": bundle.match_id,
                "period": bundle.period,
                "home": {
                    "short": bundle.home_short,
                    "color": bundle.home_color,
                    "team_id": bundle.home_team_id,
                    "name": bundle.home_team_name,
                },
                "away": {
                    "short": bundle.away_short,
                    "color": bundle.away_color,
                    "name": bundle.away_team_name,
                },
                "frames": frames_payload,
                "moves": moves,
            }
        )
        for m in moves:
            mtag = m.get("mechanism_id") or "—"
            print(
                f"  · [{mtag:>22}]  {m['label'][:46]:46s}  "
                f"net Δ {m['summary']['mean_d_net']:+.3f}  "
                f"score {m['summary']['mean_d_score']:+.3f}  "
                f"concede {m['summary']['mean_d_concede']:+.3f}"
            )

    out_path = REPO / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plays_out, separators=(",", ":")))
    print(f"\nwrote {out_path}  ({out_path.stat().st_size/1024:.1f} KiB, {len(plays_out)} plays)")


if __name__ == "__main__":
    main()
