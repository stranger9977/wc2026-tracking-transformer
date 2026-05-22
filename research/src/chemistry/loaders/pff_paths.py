"""Locate the PFF WC22 data root."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PFF_ROOT = Path("/Users/nick/Desktop/drive-download-20260518T234612Z-3-001")


def pff_root() -> Path:
    root = Path(os.environ.get("PFF_ROOT", DEFAULT_PFF_ROOT))
    if not root.exists():
        raise FileNotFoundError(
            f"PFF root not found at {root}. Set $PFF_ROOT to override."
        )
    return root


def event_files() -> list[Path]:
    root = pff_root() / "Event Data"
    return sorted(root.glob("*.json"))


def metadata_path(match_id: int | str) -> Path:
    return pff_root() / "Metadata" / f"{match_id}.json"


def event_path(match_id: int | str) -> Path:
    return pff_root() / "Event Data" / f"{match_id}.json"


def roster_path(match_id: int | str) -> Path:
    return pff_root() / "Rosters" / f"{match_id}.json"


def players_csv() -> Path:
    return pff_root() / "players.csv"
