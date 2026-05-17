"""Prepare PFF raw data into processed parquet for training.

This is the soccer equivalent of Sumer's ``src/prep_data.py``. It reads raw
PFF JSON / parquet from ``data/raw/pff_wc2022/``, normalizes it via the
kloppy loader, and writes:

    data/processed/frames.parquet
    data/processed/events.parquet
    data/processed/splits/{train,val,test}_match_ids.parquet

Usage::

    uv run python scripts/prepare_data.py [--sample 1]

NOTE: Implementation is a SKELETON.
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw" / "pff_wc2022"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def main(argv: list[str] | None = None) -> None:
    """Prepare data.

    Implementation plan:
        1. Discover matches via :func:`wc2026_tracking_transformer.data.list_pff_matches`.
        2. For each match, stream :class:`TrackingFrame` via
           :func:`wc2026_tracking_transformer.data.load_pff_match` and accumulate
           a long-format dataframe.
        3. Persist as a single ``frames.parquet`` plus a parallel
           ``events.parquet`` for label construction.
        4. Choose match-level train/val/test splits (default: 70/15/15 of the
           64 matches, stratified by tournament stage if feasible) and write
           the split assignments alongside.

    Args:
        argv: CLI args (defaults to ``sys.argv``).

    Raises:
        NotImplementedError: scaffolding only.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="If > 0, process only the first N matches (dev mode).",
    )
    parser.parse_args(argv)

    if not RAW_DIR.exists() or not any(RAW_DIR.iterdir()):
        raise FileNotFoundError(
            f"No PFF data found under {RAW_DIR}. See data/README.md for the "
            "registration + download steps."
        )

    raise NotImplementedError(
        "scripts/prepare_data.py is a scaffold. See docstring for the implementation plan."
    )


if __name__ == "__main__":
    main()
