"""Render chemistry pitch figures for every team and write a site index."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "research" / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from chemistry.viz.pitch_chemistry import render_all_teams

DATA_DIR = REPO_ROOT / "research" / "data"
FIG_DIR = REPO_ROOT / "research" / "site" / "assets" / "figures"
SITE_DATA_DIR = REPO_ROOT / "research" / "site" / "data"


def main() -> None:
    matches = pd.read_parquet(DATA_DIR / "matches.parquet")
    joi = pd.read_parquet(DATA_DIR / "joi.parquet")
    jdi = pd.read_parquet(DATA_DIR / "jdi.parquet")
    lineups = pd.read_parquet(DATA_DIR / "minutes" / "lineups.parquet")

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    metas = render_all_teams(
        FIG_DIR, joi=joi, jdi=jdi, lineups=lineups, matches=matches,
    )

    # Rewrite absolute out_path → site-relative for the JSON the site consumes.
    site_root = REPO_ROOT / "research" / "site"
    for m in metas:
        op = m.get("out_path") or ""
        try:
            rel = Path(op).resolve().relative_to(site_root.resolve())
            m["path"] = str(rel)
        except ValueError:
            m["path"] = op
    index_path = SITE_DATA_DIR / "team_figures_index.json"
    with index_path.open("w") as f:
        json.dump(metas, f, indent=2)

    teams = sorted({m["team_name"] for m in metas})
    print(f"Rendered {len(metas)} figures to {FIG_DIR}")
    print(f"Index: {index_path}")
    print(f"Teams covered ({len(teams)}): {', '.join(teams)}")


if __name__ == "__main__":
    main()
