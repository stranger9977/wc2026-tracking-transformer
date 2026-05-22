"""Compute minutes-on-pitch per player, per pair, and per (pair, opponent).

PFF gives us:
  - roster (`Rosters/{match}.json`) with `started` flag and positionGroupType
  - SUB events in `Event Data/{match}.json` with playerOffId/playerOnId + clock

Time model
----------
Each period uses its own clock starting at 0 (PFF `gameClock`). We track an
absolute timeline `t in [0, P1+P2]` where P1, P2 are period lengths from
`endPeriodX - startPeriodX` in the metadata. A player who's on at absolute
seconds {a..b} contributes (b-a)/60 minutes.

For pair minutes we just intersect the per-player second-sets — small data,
exact, no edge-case bugs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from .pff_paths import event_path, roster_path
from .pff_spadl import MatchMeta, load_metadata


@dataclass
class PlayerSpan:
    player_id: int
    player_name: str
    team_id: str
    team_name: str
    position: str | None
    shirt: str | None
    started: bool
    intervals: list[tuple[int, int]] = field(default_factory=list)  # absolute (start, end) seconds

    def total_seconds(self) -> int:
        return sum(b - a for a, b in self.intervals)


def _period_lengths(meta: MatchMeta) -> tuple[int, int]:
    p1 = int(round(meta.period1_end - meta.period1_start))
    p2 = int(round(meta.period2_end - meta.period2_start))
    return max(p1, 45 * 60), max(p2, 45 * 60)


def build_spans(match_id: int | str) -> tuple[list[PlayerSpan], MatchMeta, tuple[int, int]]:
    meta = load_metadata(match_id)
    p1_len, p2_len = _period_lengths(meta)
    # PFF "startGameClock" is absolute *match clock* seconds: P1 starts at 0,
    # P2 starts at 2700 (45:00 on the clock). Total duration runs to roughly
    # 2700 + 45min + stoppage ≈ 5500–5800 seconds.
    total_len = 2700 + p2_len

    roster = json.loads(roster_path(match_id).read_text())

    spans: dict[int, PlayerSpan] = {}
    # Starters: on from 0 absolute
    for r in roster:
        p = r.get("player") or {}
        team = r.get("team") or {}
        pid = p.get("id")
        if pid is None:
            continue
        pid = int(pid)
        spans[pid] = PlayerSpan(
            player_id=pid,
            player_name=p.get("nickname") or f"{p.get('firstName','')} {p.get('lastName','')}".strip(),
            team_id=str(team.get("id")),
            team_name=team.get("name", ""),
            position=r.get("positionGroupType"),
            shirt=r.get("shirtNumber"),
            started=bool(r.get("started")),
        )

    # Active intervals: per starter, set [0, total) until subbed off
    current_on: dict[int, int] = {pid: 0 for pid, s in spans.items() if s.started}

    events = json.loads(event_path(match_id).read_text())
    for ev in events:
        ge = ev.get("gameEvents") or {}
        if ge.get("gameEventType") != "SUB":
            continue
        clock = float(ge.get("startGameClock") or 0)
        abs_t = int(clock)
        abs_t = max(0, min(total_len, abs_t))

        off_id = ge.get("playerOffId")
        on_id = ge.get("playerOnId")
        if off_id and off_id in current_on:
            start = current_on.pop(int(off_id))
            spans[int(off_id)].intervals.append((start, abs_t))
        if on_id and int(on_id) not in current_on:
            current_on[int(on_id)] = abs_t

    # Close anyone still on at end of match
    for pid, start in current_on.items():
        if pid in spans:
            spans[pid].intervals.append((start, total_len))

    return list(spans.values()), meta, (p1_len, p2_len)


def lineup_table(match_id: int | str) -> pd.DataFrame:
    spans, meta, (p1_len, p2_len) = build_spans(match_id)
    rows = []
    for s in spans:
        rows.append({
            "game_id": meta.match_id,
            "team_id": s.team_id,
            "team_name": s.team_name,
            "player_id": s.player_id,
            "player_name": s.player_name,
            "position": s.position,
            "shirt_number": s.shirt,
            "started": s.started,
            "on_seconds": s.total_seconds(),
            "p1_len": p1_len,
            "p2_len": p2_len,
        })
    return pd.DataFrame(rows)


def _spans_to_set(intervals: list[tuple[int, int]]) -> set[int]:
    out: set[int] = set()
    for a, b in intervals:
        out.update(range(a, b))
    return out


def pair_minutes(match_id: int | str) -> pd.DataFrame:
    spans, meta, _ = build_spans(match_id)
    sets = {s.player_id: _spans_to_set(s.intervals) for s in spans}
    teams = {s.player_id: s.team_id for s in spans}
    names = {s.player_id: s.player_name for s in spans}
    pids = sorted(p for p in sets if sets[p])

    rows = []
    for i, p in enumerate(pids):
        for q in pids[i + 1:]:
            inter = sets[p] & sets[q]
            if not inter:
                continue
            rows.append({
                "game_id": meta.match_id,
                "player_p": p,
                "name_p": names[p],
                "team_p": teams[p],
                "player_q": q,
                "name_q": names[q],
                "team_q": teams[q],
                "same_team": teams[p] == teams[q],
                "minutes_together": len(inter) / 60.0,
            })
    return pd.DataFrame(rows)


def pair_opponent_minutes(match_id: int | str) -> pd.DataFrame:
    spans, meta, _ = build_spans(match_id)
    sets = {s.player_id: _spans_to_set(s.intervals) for s in spans}
    teams = {s.player_id: s.team_id for s in spans}
    names = {s.player_id: s.player_name for s in spans}
    pids = sorted(p for p in sets if sets[p])

    rows = []
    for i, p in enumerate(pids):
        for q in pids[i + 1:]:
            if teams[p] != teams[q]:
                continue
            pq = sets[p] & sets[q]
            if not pq:
                continue
            for o in pids:
                if teams[o] == teams[p]:
                    continue
                pqo = pq & sets[o]
                if not pqo:
                    continue
                rows.append({
                    "game_id": meta.match_id,
                    "pair_team": teams[p],
                    "player_p": p,
                    "name_p": names[p],
                    "player_q": q,
                    "name_q": names[q],
                    "opp_team": teams[o],
                    "opponent": o,
                    "opp_name": names[o],
                    "minutes": len(pqo) / 60.0,
                })
    return pd.DataFrame(rows)
