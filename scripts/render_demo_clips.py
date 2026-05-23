"""Render the curated demo clips for the Interactive Plays page.

Each clip is a 25-40 second window around a key event (goal / big chance).
Runs `render_interactive_clip.py` for every clip in CLIPS, then writes the
site index at research/site/data/clips/index.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (match_id, period, start_s, end_s, label, title, summary)
CLIPS = [
    (
        "10517", 1, 2080, 2120,
        "argentina-france-di-maria",
        "Di María 36' (Argentina v France, final)",
        "Argentina's third goal in a 30-pass move starting from Tagliafico's interception. "
        "Watch the attention follow Mac Allister and Di María through the chain.",
    ),
    (
        "10517", 2, 4830, 4870,
        "argentina-france-mbappe-equalizer",
        "Mbappé 80' equalizer (France v Argentina, final)",
        "France's second goal in 97 seconds. P(concede) for Argentina spikes immediately "
        "before the goal as the model sees the attacking shape collapse.",
    ),
    (
        "10502", 1, 540, 580,
        "netherlands-usa-memphis",
        "Memphis 10' (Netherlands v USA, R16)",
        "Netherlands' opener. Memphis at the end of a 20-pass Dutch sequence.",
    ),
    (
        "10510", 1, 600, 640,
        "japan-spain-doan",
        "Doan 48' (Japan v Spain, group stage)",
        "Japan equalize from a press-and-recover sequence — Doan's strike that knocked "
        "Spain off top of the group.",
    ),
    (
        "10515", 1, 2400, 2440,
        "argentina-croatia-julian",
        "Álvarez 39' (Argentina v Croatia, semi-final)",
        "Julián Álvarez beats three defenders. Watch P(score) climb as he carries.",
    ),
]


def main() -> None:
    ckpt = REPO / "output" / "transformer_frame_vaep.ckpt"
    if not ckpt.exists():
        raise SystemExit(f"frame-vaep checkpoint not found: {ckpt}")
    index_path = REPO / "research" / "site" / "data" / "clips" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    success = []
    for match, period, start, end, label, title, summary in CLIPS:
        print(f"\n=== {label} ===")
        cmd = [
            "uv", "run", "python", "scripts/render_interactive_clip.py",
            "--match", match,
            "--period", str(period),
            "--start", str(start),
            "--end", str(end),
            "--label", label,
            "--title", title,
            "--ckpt", str(ckpt),
        ]
        try:
            subprocess.run(cmd, check=True, cwd=str(REPO),
                            env={**__import__("os").environ, "PYTHONPATH": "src"})
        except subprocess.CalledProcessError as e:
            print(f"  skip {label}: {e}")
            continue
        success.append({"label": label, "title": title, "summary": summary,
                        "match": match, "period": period})

    index_path.write_text(json.dumps(success, indent=2))
    print(f"\nWrote {len(success)} clips, index at {index_path}")


if __name__ == "__main__":
    main()
