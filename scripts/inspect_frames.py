"""Sanity-check that loaded frames look right.

Renders summary statistics (frame counts, player counts per frame, velocity
distributions, pitch-coordinate ranges) over a sample of matches. Use this
after wiring the loader to confirm the schema matches expectations before
spending compute on training.

Usage::

    uv run python scripts/inspect_frames.py --match <PFF_MATCH_ID>

NOTE: Implementation is a SKELETON.
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw" / "pff_wc2022"


def main(argv: list[str] | None = None) -> None:
    """Print a sanity-check summary for one match.

    Implementation plan:
        1. Resolve ``--match`` to a directory under :data:`RAW_DIR`.
        2. Call :func:`wc2026_tracking_transformer.data.load_pff_match` and
           collect the first N frames.
        3. Print:
            - frame count per period
            - mean # of players seen per frame (should be ~22)
            - x/y coordinate min/max/mean
            - velocity histogram percentiles
            - share of frames with possession assigned

    Raises:
        NotImplementedError: scaffolding only.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--match",
        type=str,
        required=False,
        help="PFF match id (or directory name under data/raw/pff_wc2022/).",
    )
    parser.add_argument("--limit-frames", type=int, default=1000)
    parser.parse_args(argv)

    raise NotImplementedError("scripts/inspect_frames.py is a scaffold.")


if __name__ == "__main__":
    main()
