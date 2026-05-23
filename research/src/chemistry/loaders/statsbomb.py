"""StatsBomb open-data loader: fetch + convert to our SPADL schema.

Pitch convention used by StatsBomb:
- Pitch is 120 × 80 with the attacking team always moving toward x=120.
- Origin (0, 0) is the attacking team's *defensive corner*; y increases away
  from that corner so y=0 is one sideline, y=80 is the other.

For SPADL we normalize to 105 × 68 (attacker attacks toward x=105). Y direction
is preserved (we don't try to flip — both schemas place the attacker's right
on the same y side).
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .pff_spadl import ACTION_INDEX  # reuse the type list

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
DEFAULT_CACHE = Path(__file__).resolve().parents[3] / "data" / "raw_statsbomb"


def _cache_path(rel: str) -> Path:
    p = DEFAULT_CACHE / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _fetch_json(rel: str) -> object:
    """Fetch a JSON file from StatsBomb open-data with on-disk cache."""
    cp = _cache_path(rel)
    if cp.exists() and cp.stat().st_size > 0:
        return json.loads(cp.read_text())
    url = f"{BASE}/{rel}"
    req = urllib.request.Request(url, headers={"User-Agent": "wc2026-chemistry/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    cp.write_bytes(body)
    return json.loads(body)


def fetch_competitions() -> list[dict]:
    return _fetch_json("competitions.json")  # type: ignore[return-value]


def fetch_matches(competition_id: int, season_id: int) -> list[dict]:
    return _fetch_json(f"matches/{competition_id}/{season_id}.json")  # type: ignore[return-value]


def fetch_events(match_id: int) -> list[dict]:
    return _fetch_json(f"events/{match_id}.json")  # type: ignore[return-value]


def fetch_lineups(match_id: int) -> list[dict]:
    return _fetch_json(f"lineups/{match_id}.json")  # type: ignore[return-value]


# ---- Conversion -------------------------------------------------------------

PITCH_LEN_SB = 120.0
PITCH_WID_SB = 80.0
PITCH_LEN = 105.0
PITCH_WID = 68.0


def _to_spadl_xy(loc: list | None) -> tuple[float, float]:
    if not loc:
        return 52.5, 34.0
    x = float(loc[0]) * (PITCH_LEN / PITCH_LEN_SB)
    y = float(loc[1]) * (PITCH_WID / PITCH_WID_SB)
    return max(0.0, min(PITCH_LEN, x)), max(0.0, min(PITCH_WID, y))


_BODY_MAP = {"Right Foot": "foot", "Left Foot": "foot", "Foot": "foot",
             "Head": "head_other", "Other": "other", "No Touch": "other",
             "Drop Kick": "other", "Keeper Arm": "other"}


def _pass_action(p: dict) -> tuple[str, str]:
    """Return (action_name, result_name) for a StatsBomb pass."""
    pass_obj = p.get("pass", {})
    ptype = (pass_obj.get("type") or {}).get("name", "")
    is_cross = bool(pass_obj.get("cross"))
    if ptype == "Throw-in":
        name = "throw_in"
    elif ptype == "Goal Kick":
        name = "goalkick"
    elif ptype == "Corner":
        name = "corner_crossed" if is_cross else "corner_short"
    elif ptype == "Free Kick":
        name = "freekick_crossed" if is_cross else "freekick_short"
    elif is_cross:
        name = "cross"
    else:
        name = "pass"
    # outcome.name absent = completed; "Incomplete"/"Out"/"Pass Offside" = fail
    outcome = (pass_obj.get("outcome") or {}).get("name")
    result = "success" if outcome is None else "fail"
    return name, result


def _shot_action(p: dict) -> tuple[str, str]:
    s = p.get("shot", {})
    stype = (s.get("type") or {}).get("name", "")
    if stype == "Penalty":
        name = "shot_penalty"
    elif stype == "Free Kick":
        name = "shot_freekick"
    else:
        name = "shot"
    outcome = (s.get("outcome") or {}).get("name", "")
    result = "success" if outcome == "Goal" else "fail"
    return name, result


def events_to_spadl(events: list[dict], match_meta: dict | None = None) -> pd.DataFrame:
    """Convert StatsBomb match events to our SPADL DataFrame."""
    rows: list[dict] = []
    game_id = events[0].get("match_id") if events and events[0].get("match_id") else (
        match_meta.get("match_id") if match_meta else 0
    )
    for ev in events:
        et = (ev.get("type") or {}).get("name")
        if et not in {"Pass", "Shot", "Carry", "Dribble", "Clearance",
                      "Block", "Goal Keeper", "Duel", "Ball Recovery"}:
            continue
        player = ev.get("player") or {}
        team = ev.get("team") or {}
        pid = player.get("id")
        if pid is None:
            continue
        loc = ev.get("location")
        period = int(ev.get("period") or 1)
        if period not in (1, 2, 3, 4, 5):
            continue
        if period > 2:
            # Skip extra time / penalties for v1 (small population, complicates minutes math)
            continue
        minute = int(ev.get("minute") or 0)
        second = int(ev.get("second") or 0)
        time_s = minute * 60 + second  # absolute match-clock seconds

        body_name = ((ev.get(et.lower(), {}) or {}).get("body_part") or {}).get("name")
        bodypart = _BODY_MAP.get(body_name, "other")

        sx, sy = _to_spadl_xy(loc)

        if et == "Pass":
            name, result = _pass_action(ev)
            end = (ev.get("pass") or {}).get("end_location")
            ex, ey = _to_spadl_xy(end)
            receiver = ((ev.get("pass") or {}).get("recipient") or {}).get("id")
        elif et == "Shot":
            name, result = _shot_action(ev)
            end = (ev.get("shot") or {}).get("end_location")
            ex, ey = _to_spadl_xy(end[:2] if end and len(end) >= 2 else None)
            receiver = None
        elif et == "Carry":
            name = "dribble"
            end = (ev.get("carry") or {}).get("end_location")
            ex, ey = _to_spadl_xy(end)
            result = "success"
            receiver = None
        elif et == "Dribble":
            name = "take_on"
            ex, ey = sx, sy
            outcome = ((ev.get("dribble") or {}).get("outcome") or {}).get("name")
            result = "success" if outcome == "Complete" else "fail"
            receiver = None
        elif et == "Clearance":
            name = "clearance"
            ex, ey = sx, sy
            result = "success"
            receiver = None
        elif et == "Block":
            name = "tackle"
            ex, ey = sx, sy
            result = "success"
            receiver = None
        elif et == "Goal Keeper":
            gk_type = ((ev.get("goalkeeper") or {}).get("type") or {}).get("name", "")
            if "Save" in gk_type or "Punch" in gk_type:
                name = "keeper_save"
            else:
                name = "keeper_claim"
            ex, ey = sx, sy
            result = "success"
            receiver = None
        elif et == "Duel":
            name = "tackle"
            ex, ey = sx, sy
            outcome = ((ev.get("duel") or {}).get("outcome") or {}).get("name", "")
            result = "success" if "Won" in outcome else "fail"
            receiver = None
        elif et == "Ball Recovery":
            name = "interception"
            ex, ey = sx, sy
            result = "success"
            receiver = None
        else:
            continue

        rows.append({
            "game_id": int(game_id) if game_id else None,
            "original_event_id": ev.get("id"),
            "period_id": period,
            "time_seconds": float(time_s),
            "team_id": str(team.get("id")) if team.get("id") else None,
            "team_name": team.get("name"),
            "player_id": int(pid),
            "player_name": player.get("name"),
            "type_name": name,
            "result_name": result,
            "bodypart_name": bodypart,
            "start_x": sx, "start_y": sy,
            "end_x": ex, "end_y": ey,
            "receiver_id": int(receiver) if receiver else None,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["period_id", "time_seconds"]).reset_index(drop=True)
        df["action_id"] = range(len(df))
    return df


# ---- Convenience: batch download a competition-season ----------------------

@dataclass
class CompetitionRequest:
    competition_id: int
    season_id: int
    label: str  # e.g. "euro_2024"


def download_competition(req: CompetitionRequest, *, max_workers: int = 8,
                          progress: bool = True) -> list[pd.DataFrame]:
    """Download every match in the comp-season and return a list of SPADL frames."""
    matches = fetch_matches(req.competition_id, req.season_id)
    out: list[pd.DataFrame] = []
    if progress:
        print(f"  {req.label}: {len(matches)} matches")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_events, int(m["match_id"])): m for m in matches}
        for i, fut in enumerate(concurrent.futures.as_completed(futures)):
            m = futures[fut]
            try:
                events = fut.result()
            except Exception as e:
                print(f"   skip match {m['match_id']}: {e}")
                continue
            df = events_to_spadl(events, m)
            if df.empty:
                continue
            df["competition_id"] = req.competition_id
            df["competition_label"] = req.label
            df["match_date"] = m.get("match_date")
            df["home_team"] = (m.get("home_team") or {}).get("home_team_name")
            df["away_team"] = (m.get("away_team") or {}).get("away_team_name")
            out.append(df)
            if progress and (i + 1) % 25 == 0:
                print(f"   {req.label}: {i + 1}/{len(matches)} done")
    if progress:
        print(f"   {req.label}: {len(out)} matches converted")
    return out
