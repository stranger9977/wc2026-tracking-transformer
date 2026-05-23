"""Pre-cache PFF tracking → (tensors, y_score, y_concede) on disk.

Decompressing PFF bz2 JSONL is the bottleneck. This script loads each
match once, runs the label builder, and pickles `(tensors, y_score,
y_concede)` to `research/data/frame_vaep_cache/<match_id>.npz`. Future
training runs load from cache (instant) instead of streaming the
bz2 jsonl again.

Usage:
    PYTHONPATH=src uv run python scripts/precache_pff_tensors.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.pff import (load_pff_match,
                                                            list_pff_matches)
from wc2026_tracking_transformer.tasks.frame_vaep_labels import (build_labels,
                                                                   goals_from_pff_events)

PFF_STRIDE = 6


def _events_path(match_id: str) -> Path:
    root = Path(os.environ.get(
        "PFF_ROOT", "/Users/nick/Desktop/drive-download-20260518T234612Z-3-001"
    ))
    return root / "Event Data" / f"{match_id}.json"


def cache_match(match_id: str, cache_dir: Path, *, k_seconds: float = 10.0) -> bool:
    out = cache_dir / f"{match_id}.npz"
    if out.exists():
        return False  # already cached
    t0 = time.time()
    try:
        frames = list(load_pff_match(match_id, sampling_stride=PFF_STRIDE))
    except Exception as e:
        print(f"  skip {match_id}: load failed: {e}")
        return False
    if not frames:
        print(f"  skip {match_id}: no frames")
        return False
    events = json.loads(_events_path(match_id).read_text())
    goals = goals_from_pff_events(events)
    y_score, y_concede = build_labels(frames, goals, k_seconds=k_seconds)
    tensors = batch_frames(frames)
    n = min(tensors.shape[0], y_score.shape[0])
    np.savez_compressed(
        out,
        tensors=tensors[:n],
        y_score=y_score[:n],
        y_concede=y_concede[:n],
        timestamps_ms=np.asarray([f.timestamp_ms for f in frames[:n]], dtype=np.int64),
        periods=np.asarray([f.period for f in frames[:n]], dtype=np.int8),
        in_possession=np.asarray(
            [f.in_possession_team_id or "" for f in frames[:n]], dtype=object),
    )
    print(f"  {match_id}: cached n={n}, goals={len(goals)}, "
          f"pos_score={int(y_score.sum())}, pos_concede={int(y_concede.sum())} "
          f"({time.time() - t0:.1f}s)")
    return True


def main() -> None:
    cache_dir = REPO / "research" / "data" / "frame_vaep_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    matches = list_pff_matches()
    print(f"Caching {len(matches)} PFF matches → {cache_dir}")
    n_new = 0
    for i, m in enumerate(matches):
        mid = m.name
        print(f"[{i+1}/{len(matches)}] {mid}")
        if cache_match(mid, cache_dir):
            n_new += 1
    print(f"Cached {n_new} new matches, {len(matches) - n_new} already present.")


if __name__ == "__main__":
    main()
