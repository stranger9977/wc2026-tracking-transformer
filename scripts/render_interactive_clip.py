"""Render a step-throughable interactive play clip.

Given a PFF match and a (period, start_s, end_s) window:

1. Load the tracking frames at 5 Hz inside the window.
2. Run the frame-level VAEP transformer to get per-frame
   (p_score, p_concede, ball-token attention vector).
3. Match each tracking-frame slot to a player_id using the nearest-in-time PFF
   event's `homePlayers`/`awayPlayers` (x,y) snapshot — so we can label players
   by name + position and color them by their actual national team.
4. Annotate each frame with any PFF event(s) that occurred at that timestamp
   (pass, shot, GOAL, take_on, …) so the site can call out moments.
5. Render per-frame PNGs + per-frame JSON.

Usage:
    PYTHONPATH=src uv run python scripts/render_interactive_clip.py \
        --match 10517 --period 1 --start 2080 --end 2110 --label argentina-france-di-maria
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.pff import load_pff_match
from wc2026_tracking_transformer.data.schema import PITCH_LENGTH_M, PITCH_WIDTH_M
from wc2026_tracking_transformer.model.frame_vaep import FrameVaepLitModule

PITCH_COLOR = "#0d4d2c"
LINE_COLOR = "#dceadb"
DEFAULT_HOME = "#5eead4"
DEFAULT_AWAY = "#f87171"
GK_RING = "#00d68f"
PFF_ROOT_DEFAULT = "/Users/nick/Desktop/drive-download-20260518T234612Z-3-001"

# Themes: "dark" is the current video-deliverable look; "print" is paper-grey
# for figures embedded in static articles / decks (Tufte preference).
THEMES = {
    "dark": {
        "fig_bg": "#0b1220",
        "pitch_color": "#0d4d2c",
        "line_color": "#dceadb",
        "text_main": "#e6edf3",
        "text_dim": "#9aa5b1",
        "title_color": "white",
        "event_color": "#a3c1ff",
        "event_goal": "#ffd166",
        "label_bg": "#0b1220",
        "label_text": "white",
        "saturation": 1.0,  # team colours unmodified in dark mode
    },
    "print": {
        "fig_bg": "#f7f5ef",
        "pitch_color": "#dbe2dc",
        "line_color": "#7d8a8a",
        "text_main": "#111111",
        "text_dim": "#555b62",
        "title_color": "#111111",
        "event_color": "#444444",
        "event_goal": "#8a5a00",
        "label_bg": "#f7f5ef",
        "label_text": "#111111",
        "saturation": 0.6,  # mute team colours for print
    },
}


def _mute_hex(hex_color: str, saturation: float) -> str:
    """Pull a hex colour toward neutral grey by (1 - saturation)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return hex_color
    grey = (r + g + b) / 3.0
    r2 = int(grey + (r - grey) * saturation)
    g2 = int(grey + (g - grey) * saturation)
    b2 = int(grey + (b - grey) * saturation)
    return f"#{r2:02x}{g2:02x}{b2:02x}"


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _pff_root() -> Path:
    return Path(os.environ.get("PFF_ROOT", PFF_ROOT_DEFAULT))


def _load_match_meta(match_id: str) -> dict:
    raw = json.loads((_pff_root() / "Metadata" / f"{match_id}.json").read_text())
    if isinstance(raw, list):
        raw = raw[0]
    return raw


def _load_events(match_id: str) -> list[dict]:
    return json.loads((_pff_root() / "Event Data" / f"{match_id}.json").read_text())


def draw_pitch(ax: plt.Axes, theme: dict | None = None) -> None:
    pitch_color = (theme or THEMES["dark"])["pitch_color"]
    line_color = (theme or THEMES["dark"])["line_color"]
    ax.set_facecolor(pitch_color)
    L, W = PITCH_LENGTH_M, PITCH_WIDTH_M
    HL, HW = L / 2, W / 2
    ax.set_xlim(-HL - 2, HL + 2)
    ax.set_ylim(-HW - 2, HW + 2)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.add_patch(mpatches.Rectangle((-HL, -HW), L, W, fill=False,
                                    edgecolor=line_color, linewidth=1.4))
    ax.plot([0, 0], [-HW, HW], color=line_color, linewidth=1.2)
    ax.add_patch(mpatches.Circle((0, 0), 9.15, fill=False,
                                  edgecolor=line_color, linewidth=1.2))
    pen_w, pen_d = 40.32, 16.5
    ax.add_patch(mpatches.Rectangle((-HL, -pen_w / 2), pen_d, pen_w, fill=False,
                                    edgecolor=line_color, linewidth=1.2))
    ax.add_patch(mpatches.Rectangle((HL - pen_d, -pen_w / 2), pen_d, pen_w, fill=False,
                                    edgecolor=line_color, linewidth=1.2))


def _build_event_index(events: list[dict]) -> list[dict]:
    """Compact list of events with their absolute timestamps + player snapshots.

    Each entry: {abs_ms, period, gameClock, homePlayers, awayPlayers, ball,
                  type_label, actor_id, actor_name, position_at_event, is_goal}.
    """
    out = []
    for ev in events:
        ge = ev.get("gameEvents") or {}
        pe = ev.get("possessionEvents") or {}
        period = int(ge.get("period") or 1)
        clock = float(pe.get("gameClock") or ge.get("startGameClock") or 0)
        # gameClock is match-absolute; for our per-frame matching we want
        # period-relative seconds since the tracking frames use that.
        # P1 frame ts is ms-since-period-start; gameClock in P1 == seconds-since-start.
        # P2 frame ts is ms-since-P2-start; gameClock in P2 == 2700 + seconds-into-P2.
        if period == 1:
            period_rel_ms = int(clock * 1000)
        else:
            period_rel_ms = int((clock - 2700) * 1000)
        pe_type = pe.get("possessionEventType")
        actor = None; actor_name = None; type_label = None
        if pe_type == "PA":
            actor = pe.get("passerPlayerId"); actor_name = pe.get("passerPlayerName")
            type_label = "pass"
        elif pe_type == "CR":
            actor = pe.get("crosserPlayerId"); actor_name = pe.get("crosserPlayerName")
            type_label = "cross"
        elif pe_type == "BC":
            actor = pe.get("ballCarrierPlayerId") or pe.get("carrierPlayerId")
            actor_name = pe.get("ballCarrierPlayerName") or pe.get("carrierPlayerName")
            type_label = "carry"
        elif pe_type == "SH":
            actor = pe.get("shooterPlayerId"); actor_name = pe.get("shooterPlayerName")
            is_goal = pe.get("shotOutcomeType") == "G"
            type_label = "GOAL" if is_goal else "shot"
        elif pe_type == "CH":
            actor = pe.get("challengerPlayerId"); actor_name = pe.get("challengerPlayerName")
            type_label = "tackle"
        elif pe_type == "CL":
            actor = pe.get("clearerPlayerId"); actor_name = pe.get("clearerPlayerName")
            type_label = "clearance"
        elif pe_type == "TC":
            actor = pe.get("touchPlayerId") or pe.get("ballCarrierPlayerId")
            actor_name = pe.get("touchPlayerName") or pe.get("ballCarrierPlayerName")
            type_label = "touch"
        out.append({
            "period": period,
            "period_rel_ms": period_rel_ms,
            "gameClock": clock,
            "type_label": type_label,
            "type_raw": pe_type,
            "actor_id": int(actor) if actor else None,
            "actor_name": actor_name,
            "is_goal": pe_type == "SH" and pe.get("shotOutcomeType") == "G",
            "outcome": (pe.get("shotOutcomeType") if pe_type == "SH"
                         else pe.get("passOutcomeType") if pe_type == "PA"
                         else pe.get("challengeOutcomeType")),
            "homePlayers": ev.get("homePlayers") or [],
            "awayPlayers": ev.get("awayPlayers") or [],
            "ball": (ev.get("ball") or [{}])[0],
        })
    return out


def _build_player_directory(rosters_data: list[dict], home_id: str, away_id: str
                            ) -> dict[int, dict]:
    """player_id → {name, position, team_id, jersey} for a match."""
    out: dict[int, dict] = {}
    for r in rosters_data:
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
            "name": p.get("nickname") or f"{p.get('firstName','')} {p.get('lastName','')}".strip(),
            "position": r.get("positionGroupType"),
            "team_id": str(team.get("id")),
            "jersey": r.get("shirtNumber"),
        }
    return out


def _slot_to_player_id_for_frame(frame_tensor: np.ndarray,
                                  event_snapshot: dict,
                                  ) -> list[int | None]:
    """Match each of the 22 player slots in our tensor to a PFF event-snapshot player.

    Strategy: take per-slot (x_norm, y_norm), denormalize to meters, then for each
    slot find the nearest player in the event_snapshot's home+away arrays.
    """
    HL, HW = PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2
    slot_xy = frame_tensor[:22, :2].copy()
    slot_xy[:, 0] *= HL
    slot_xy[:, 1] *= HW

    all_players = []
    for p in event_snapshot.get("homePlayers") or []:
        if p.get("x") is None or p.get("y") is None or not p.get("playerId"):
            continue
        all_players.append((float(p["x"]), float(p["y"]), int(p["playerId"])))
    for p in event_snapshot.get("awayPlayers") or []:
        if p.get("x") is None or p.get("y") is None or not p.get("playerId"):
            continue
        all_players.append((float(p["x"]), float(p["y"]), int(p["playerId"])))

    out: list[int | None] = [None] * 22
    used: set[int] = set()
    for slot in range(22):
        sx, sy = slot_xy[slot]
        best = None; best_d = 1e9
        for px, py, pid in all_players:
            if pid in used:
                continue
            d = (px - sx) ** 2 + (py - sy) ** 2
            if d < best_d:
                best = pid; best_d = d
        if best is not None:
            out[slot] = best
            used.add(best)
    return out


def _events_in_window(events_idx: list[dict], period: int,
                      start_ms: int, end_ms: int) -> list[dict]:
    """All events whose period_rel_ms falls in [start_ms, end_ms]."""
    return [e for e in events_idx
            if e["period"] == period and start_ms <= e["period_rel_ms"] <= end_ms]


def render_frame(
    out_path: Path,
    frame_tensor: np.ndarray,
    attn_ball: np.ndarray,
    p_score: float, p_concede: float,
    title: str,
    home_color: str, away_color: str,
    home_team_name: str, away_team_name: str,
    home_short: str, away_short: str,
    slot_player_ids: list[int | None],
    player_dir: dict[int, dict],
    home_team_id: str,
    in_possession_team_id: str | None,
    frame_idx: int, n_total: int,
    event_label: str | None = None,
    is_goal_event: bool = False,
    theme: dict | None = None,
    top_slots: list[int] | None = None,
) -> dict:
    th = theme or THEMES["dark"]
    fig, ax = plt.subplots(figsize=(8.8, 5.6), dpi=130, facecolor=th["fig_bg"])
    draw_pitch(ax, th)
    HL, HW = PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2

    # Mute team colours per theme saturation (60% in print mode).
    home_color = _mute_hex(home_color, th["saturation"])
    away_color = _mute_hex(away_color, th["saturation"])
    xy = frame_tensor[:22, :2].copy()
    xy[:, 0] *= HL; xy[:, 1] *= HW
    is_gk = frame_tensor[:22, 5] > 0.5

    # Color each slot by team (resolved from player_id → team_id)
    colors = []
    for slot in range(22):
        pid = slot_player_ids[slot]
        team = player_dir.get(pid, {}).get("team_id") if pid else None
        if team == home_team_id:
            colors.append(home_color)
        else:
            colors.append(away_color)

    ax.scatter(xy[:, 0], xy[:, 1], c=colors, s=190, edgecolor="white",
               linewidth=1.0, zorder=3, alpha=0.95)
    if is_gk.any():
        ax.scatter(xy[is_gk, 0], xy[is_gk, 1], s=440, facecolors="none",
                   edgecolor=GK_RING, linewidth=2.0, zorder=2)

    # Player labels: surname + position chip text
    for slot in range(22):
        pid = slot_player_ids[slot]
        if not pid:
            continue
        info = player_dir.get(pid, {})
        name = (info.get("name") or "").split()
        surname = name[-1] if name else "?"
        pos = info.get("position") or ""
        label = f"{surname}" if not pos else f"{surname} · {pos}"
        ax.annotate(label, (xy[slot, 0], xy[slot, 1]),
                    xytext=(5, 4), textcoords="offset points",
                    fontsize=6.5, color=th["label_text"], zorder=5,
                    bbox=dict(facecolor=th["label_bg"], edgecolor="none",
                              boxstyle="round,pad=0.18", alpha=0.62))

    # Ball
    bx = frame_tensor[22, 0] * HL
    by = frame_tensor[22, 1] * HW
    ax.scatter([bx], [by], c="#ffd166", s=110, edgecolor="white",
               linewidth=1.0, zorder=4)

    # Top-k attended slots — caller passes them in via `top_slots` so we can
    # apply temporal smoothing or sticky-follow at the caller level instead of
    # picking fresh each frame (which causes jitter).
    top_idx = top_slots if top_slots is not None else np.argsort(-attn_ball)[:3].tolist()
    top_players = []
    for slot in top_idx:
        px, py = xy[slot]
        ax.add_patch(mpatches.Circle((px, py), 2.8, fill=False,
                                     edgecolor="#ffd166", linewidth=2.2, zorder=5))
        ax.plot([bx, px], [by, py], color="#fde047", linewidth=2.0, alpha=0.7, zorder=4)
        pid = slot_player_ids[slot]
        top_players.append({
            "slot": int(slot),
            "player_id": int(pid) if pid else None,
            "name": (player_dir.get(pid, {}) or {}).get("name") if pid else None,
            "position": (player_dir.get(pid, {}) or {}).get("position") if pid else None,
            "attention": float(attn_ball[slot]),
        })

    # Title bar (single line, team colours muted per theme)
    ax.text(0, HW + 1.4, title, ha="center", va="bottom",
            color=th["title_color"], fontsize=13, fontweight="bold")
    ax.text(-HL, HW + 1.4, f"● {home_short}", ha="left", va="bottom",
            color=home_color, fontsize=11, fontweight="bold")
    ax.text(HL, HW + 1.4, f"{away_short} ●", ha="right", va="bottom",
            color=away_color, fontsize=11, fontweight="bold")

    # Per-frame stat strip: one line, tabular-nums, units always present.
    # Left: frame counter. Right: probabilities with explicit units.
    mono = {"family": "monospace"}
    ax.text(-HL, -HW - 0.4, f"frame {frame_idx+1:03d} / {n_total:03d}",
            ha="left", va="top", color=th["text_dim"], fontsize=10, **mono)
    stat_line = (
        f"P(score, next 10 s) = {p_score:6.3f}     "
        f"P(concede, next 10 s) = {p_concede:6.3f}     "
        f"net = {p_score - p_concede:+6.3f}"
    )
    ax.text(HL, -HW - 0.4, stat_line,
            ha="right", va="top", color=th["text_main"], fontsize=9.5, **mono)

    # Event label: clean horizontal bar at the bottom (not a pill).
    if event_label:
        is_goal = is_goal_event
        color = th["event_goal"] if is_goal else th["event_color"]
        weight = "bold" if is_goal else "regular"
        # Single full-width rule + centred text. No box-stroke.
        bar_y = -HW - 2.6
        ax.plot([-HL, HL], [bar_y + 0.6, bar_y + 0.6],
                color=color, linewidth=0.8, alpha=0.6, zorder=1)
        ax.text(0, bar_y, event_label, ha="center", va="top",
                color=color, fontsize=10.5, fontweight=weight,
                fontfamily="monospace")
    fig.tight_layout()
    fig.savefig(out_path, facecolor=th["fig_bg"], bbox_inches="tight")
    plt.close(fig)
    return {
        "top_attended": top_players,
        "ball_xy": [float(bx), float(by)],
        "event_label": event_label,
        "is_goal_event": is_goal_event,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", required=True)
    ap.add_argument("--period", type=int, default=1)
    ap.add_argument("--start", type=float, required=True,
                    help="Period-relative seconds at the start of the clip")
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--ckpt", default="output/transformer_frame_vaep.ckpt")
    ap.add_argument("--stride", type=int, default=6)
    ap.add_argument(
        "--smooth-alpha", type=float, default=0.55,
        help="EMA smoothing weight on the ball-attention vector. 0 disables "
             "smoothing (per-frame argmax — jitters). 1 means no decay "
             "(carry the whole history). 0.55 is a usable default.",
    )
    ap.add_argument(
        "--follow", default="auto",
        help="Which players to highlight per frame. "
             "'auto' = current top-K after smoothing (default). "
             "'sticky' = lock to the smoothed top-K from the first frame. "
             "'actor' = follow the player nearest the ball each frame. "
             "'team:home' / 'team:away' = top-K from one team. "
             "'role:DEF' / 'role:MID' / 'role:FWD' / 'role:GK' = top-K of that role.",
    )
    ap.add_argument(
        "--top-k", type=int, default=3,
        help="How many attended players to highlight.",
    )
    ap.add_argument(
        "--theme",
        choices=list(THEMES.keys()),
        default="dark",
        help=(
            "Render theme. 'dark' is the current screen/video deliverable; "
            "'print' is paper-grey with muted team colours for static figures."
        ),
    )
    args = ap.parse_args()
    theme = THEMES[args.theme]

    title = args.title or args.label.replace("-", " ").title()
    device = _device()
    lit = FrameVaepLitModule.load_from_checkpoint(args.ckpt, map_location=device)
    lit.eval().to(device)

    # Match metadata + events + roster
    meta = _load_match_meta(args.match)
    home_color = (meta.get("homeTeamKit") or {}).get("primaryColor") or DEFAULT_HOME
    away_color = (meta.get("awayTeamKit") or {}).get("primaryColor") or DEFAULT_AWAY
    home_name = meta.get("homeTeam", {}).get("name", "Home")
    away_name = meta.get("awayTeam", {}).get("name", "Away")
    home_short = meta.get("homeTeam", {}).get("shortName", home_name[:3].upper())
    away_short = meta.get("awayTeam", {}).get("shortName", away_name[:3].upper())
    home_team_id = str(meta.get("homeTeam", {}).get("id", ""))

    events = _load_events(args.match)
    events_idx = _build_event_index(events)

    roster_path = _pff_root() / "Rosters" / f"{args.match}.json"
    roster_raw = json.loads(roster_path.read_text())
    player_dir = _build_player_directory(roster_raw, home_team_id, "")

    frames_all = list(load_pff_match(args.match, sampling_stride=args.stride))
    clip_frames = [f for f in frames_all
                   if f.period == args.period
                   and args.start <= f.timestamp_ms / 1000.0 <= args.end]
    if not clip_frames:
        raise SystemExit(f"no frames in window: period {args.period} {args.start}-{args.end}s")
    print(f"clip: {len(clip_frames)} frames")

    # Events overlapping the window (for annotation per-frame)
    win_start_ms = int(args.start * 1000)
    win_end_ms = int(args.end * 1000)
    in_window = _events_in_window(events_idx, args.period, win_start_ms, win_end_ms)
    print(f"events in window: {len(in_window)} ({sum(1 for e in in_window if e['is_goal'])} goals)")

    tensors = batch_frames(clip_frames)
    x = torch.from_numpy(tensors).to(device)
    with torch.no_grad():
        enc, attn = lit.encode_with_attention(x)
        ps = torch.sigmoid(lit.score_head(enc)).cpu().numpy()
        pc = torch.sigmoid(lit.concede_head(enc)).cpu().numpy()
        attn_mean = attn.mean(dim=(1, 2)).cpu().numpy()
        attn_ball = attn_mean[:, 22, :22]
        attn_ball = attn_ball / np.maximum(attn_ball.sum(axis=1, keepdims=True), 1e-9)

    clip_dir = REPO / "research" / "site" / "assets" / "clips" / args.label
    clip_dir.mkdir(parents=True, exist_ok=True)
    site_data_dir = REPO / "research" / "site" / "data" / "clips"
    site_data_dir.mkdir(parents=True, exist_ok=True)

    # Temporal smoothing on the attention vector — Exponential Moving Average.
    # Reduces jitter; lets the eye actually follow which players the model is on.
    alpha = float(args.smooth_alpha)
    attn_ball_smooth = np.zeros_like(attn_ball)
    attn_ball_smooth[0] = attn_ball[0]
    for i in range(1, attn_ball.shape[0]):
        attn_ball_smooth[i] = alpha * attn_ball[i] + (1 - alpha) * attn_ball_smooth[i - 1]
    attn_ball = attn_ball_smooth  # use the smoothed signal everywhere downstream

    # For each tracking frame, find the nearest event for slot→pid mapping AND
    # to know whether an event "happens" on this frame.
    in_window_periods = [e["period_rel_ms"] for e in in_window]

    def _pick_top_slots(i: int, attn: np.ndarray, slot_pid: list[int | None],
                        ball_xy: tuple[float, float]) -> list[int]:
        """Resolve which slot indices to highlight on frame i."""
        mode = (args.follow or "auto").lower()
        K = max(1, int(args.top_k))
        if mode == "auto":
            return list(np.argsort(-attn)[:K])
        if mode == "sticky":
            return list(_pick_top_slots.sticky_initial)
        if mode == "actor":
            # Player nearest the ball, then top-(K-1) by attention
            HL, HW = PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2
            xy = tensors[i, :22, :2].copy()
            xy[:, 0] *= HL; xy[:, 1] *= HW
            dx = xy[:, 0] - ball_xy[0]; dy = xy[:, 1] - ball_xy[1]
            d = np.hypot(dx, dy)
            actor = int(np.argmin(d))
            others = [s for s in np.argsort(-attn) if s != actor][: K - 1]
            return [actor, *others]
        if mode.startswith("team:"):
            target = mode.split(":", 1)[1].strip().lower()
            want_home = target in ("home", "h")
            mask = np.zeros(22, dtype=bool)
            for s in range(22):
                pid = slot_pid[s]
                if not pid:
                    continue
                tid = (player_dir.get(pid, {}) or {}).get("team_id")
                if (tid == home_team_id) == want_home:
                    mask[s] = True
            if not mask.any():
                return list(np.argsort(-attn)[:K])
            return list(np.argsort(-(attn * mask))[:K])
        if mode.startswith("role:"):
            want_role = mode.split(":", 1)[1].strip().upper()
            mask = np.zeros(22, dtype=bool)
            from chemistry.joint.grid import grid_role  # type: ignore
            for s in range(22):
                pid = slot_pid[s]
                if not pid:
                    continue
                pos = (player_dir.get(pid, {}) or {}).get("position")
                if grid_role(pos) == want_role:
                    mask[s] = True
            if not mask.any():
                return list(np.argsort(-attn)[:K])
            return list(np.argsort(-(attn * mask))[:K])
        return list(np.argsort(-attn)[:K])

    # Pre-seed the sticky locked top-K from frame 0
    _pick_top_slots.sticky_initial = list(np.argsort(-attn_ball[0])[: max(1, int(args.top_k))])

    per_frame: list[dict] = []
    for i, f in enumerate(clip_frames):
        # Nearest event in time within +/- 1s (any event in match — better proximity)
        # Walk events sorted by period_rel_ms; binary search is overkill for 60 events.
        best_ev = None; best_dt = 10**9
        for ev in events_idx:
            if ev["period"] != f.period:
                continue
            dt = abs(ev["period_rel_ms"] - f.timestamp_ms)
            if dt < best_dt:
                best_dt = dt; best_ev = ev
        if best_ev is None:
            slot_pid = [None] * 22
        else:
            slot_pid = _slot_to_player_id_for_frame(tensors[i], best_ev)

        # Event annotation: only when an event lies within 200 ms of this frame
        ev_in_frame = None
        is_goal = False
        for ev in in_window:
            if ev["period"] != f.period:
                continue
            dt = abs(ev["period_rel_ms"] - f.timestamp_ms)
            if dt <= 200:
                ev_in_frame = ev
                if ev["is_goal"]:
                    is_goal = True
                break
        event_label = None
        if ev_in_frame:
            actor = ev_in_frame.get("actor_name") or ""
            t = ev_in_frame.get("type_label") or ev_in_frame.get("type_raw")
            if t == "GOAL":
                event_label = f"⚽ GOAL — {actor}"
            elif t == "shot":
                event_label = f"shot — {actor}"
            elif t in ("pass", "cross", "carry", "touch"):
                event_label = f"{t} — {actor}"
            else:
                event_label = f"{t}"

        png_path = clip_dir / f"frame_{i:03d}.png"
        # Ball position for the actor-follow mode
        HL_, HW_ = PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2
        ball_xy = (float(tensors[i, 22, 0]) * HL_, float(tensors[i, 22, 1]) * HW_)
        top_slots = _pick_top_slots(i, attn_ball[i], slot_pid, ball_xy)
        meta_row = render_frame(
            png_path,
            tensors[i], attn_ball[i],
            float(ps[i]), float(pc[i]),
            title, home_color, away_color, home_name, away_name,
            home_short, away_short,
            slot_pid, player_dir, home_team_id,
            f.in_possession_team_id, i, len(clip_frames),
            event_label=event_label, is_goal_event=is_goal,
            theme=theme, top_slots=top_slots,
        )
        meta_row.update({
            "frame_idx": i,
            "frame_id": f.frame_id,
            "period": f.period,
            "timestamp_ms": int(f.timestamp_ms),
            "in_possession_team_id": f.in_possession_team_id,
            "p_score": float(ps[i]),
            "p_concede": float(pc[i]),
            "vaep": float(ps[i]) - float(pc[i]),
        })
        per_frame.append(meta_row)

    out = {
        "label": args.label, "title": title,
        "match_id": args.match, "period": args.period,
        "start_s": args.start, "end_s": args.end,
        "n_frames": len(per_frame),
        "home_team": {"id": home_team_id, "name": home_name,
                       "short": home_short, "color": home_color},
        "away_team": {"name": away_name, "short": away_short, "color": away_color},
        "events_in_window": [
            {"period_rel_ms": e["period_rel_ms"],
             "type": e.get("type_label"),
             "actor_name": e.get("actor_name"),
             "is_goal": e["is_goal"]}
            for e in in_window if e.get("type_label")
        ],
        "frames": per_frame,
        "image_pattern": f"assets/clips/{args.label}/frame_{{idx:03d}}.png",
    }
    (site_data_dir / f"{args.label}.json").write_text(json.dumps(out, indent=2))
    print(f"wrote {len(per_frame)} frame PNGs + {site_data_dir / f'{args.label}.json'}")


if __name__ == "__main__":
    main()
