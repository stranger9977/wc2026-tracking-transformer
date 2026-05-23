#!/usr/bin/env bash
# Overnight full training + clip rendering for frame-level VAEP.
# Usage:
#   bash scripts/train_frame_vaep_full.sh > /tmp/frame_vaep_full.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== precache all PFF matches ==="
PYTHONPATH=src uv run python -u scripts/precache_pff_tensors.py

echo "=== full training ==="
PYTHONPATH=src uv run python -u scripts/train_frame_vaep.py \
    --pff-n 64 --val-n 8 --epochs 6 --batch-size 256

echo "=== render demo clips ==="
PYTHONPATH=src uv run python -u scripts/render_demo_clips.py

echo "=== DONE ==="
