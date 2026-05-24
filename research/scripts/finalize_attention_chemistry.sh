#!/bin/bash
# Run after extract_attention_chemistry_frame_vaep.py workers finish.
# Combines shards, builds per-team figures, refreshes pairs JSON.
set -e
cd "$(dirname "$0")/../.."

n_shards=$(ls research/data/attention_chemistry_shards/*.parquet 2>/dev/null | wc -l | tr -d ' ')
echo "shards available: $n_shards"
if [ "$n_shards" -lt 40 ]; then
  echo "fewer than 40 shards — workers may still be running. abort."
  exit 1
fi

# 1. Combine shards into one parquet
PYTHONPATH="src:research/src:research/scripts" \
  uv run python research/scripts/extract_attention_chemistry_frame_vaep.py --combine

# 2. Render per-team figures + attention_pairs.json
PYTHONPATH="src:research/src" \
  uv run python research/scripts/render_attention_figures.py

# 3. Show what got produced
echo "---"
echo "team figures:"
ls research/site/assets/figures/ 2>/dev/null | head -10
echo "site data:"
ls -lh research/site/data/attention_figures_index.json research/site/data/attention_pairs.json 2>&1
