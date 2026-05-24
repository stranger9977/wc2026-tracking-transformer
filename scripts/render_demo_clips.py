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
    # (match_id, period, start_s, end_s, label, title, summary)
    # IMPORTANT: start/end are PERIOD-RELATIVE seconds (P2 timestamps run 0-2700
    # from kickoff, NOT 2700-5400 in absolute gameClock). Always verify the goal
    # is INSIDE the window — keep a few seconds of cushion past the strike.
    (
        # Di María goal: P1-relative 2121s. Window centres on the strike.
        "10517", 1, 2090, 2135,
        "argentina-france-di-maria",
        "Di María 36' (Argentina v France, final)",
        "Argentina's third goal in a 30-pass move starting from Tagliafico's interception. "
        "Watch the attention follow Mac Allister and Di María through the chain.",
    ),
    (
        # The 80' Mbappé equalizer is a penalty — tracking goes dead for 29s after
        # the spot kick (ball out of play, restart from kickoff), leaving only ~5
        # usable frames. The 81' Mbappé volley is open play with 120+ continuous
        # frames of buildup. P2-relative 2158s = gameClock 4858.
        "10517", 2, 2118, 2165,
        "argentina-france-mbappe-volley",
        "Mbappé 81' volley (France v Argentina, final)",
        "Mbappé's second goal in 97 seconds, this one off the volley. Watch P(concede) "
        "for Argentina spike as France break in transition before the strike.",
    ),
    (
        # Memphis goal: P1-relative 571s.
        "10502", 1, 540, 585,
        "netherlands-usa-memphis",
        "Memphis 10' (Netherlands v USA, R16)",
        "Netherlands' opener. Memphis at the end of a 20-pass Dutch sequence.",
    ),
    (
        # Japan v Spain is match 3854 (not 10510 — that's Croatia v Brazil!).
        # Doan goal: P2-relative 168s (gameClock 2868, 48' of game).
        "3854", 2, 140, 185,
        "japan-spain-doan",
        "Doan 48' (Japan v Spain, group stage)",
        "Japan equalize from a press-and-recover sequence — Doan's strike that knocked "
        "Spain off top of the group.",
    ),
    (
        # Argentina v Croatia semi is match 10514 (not 10515 — that's France v Morocco!).
        # Álvarez first goal: P1-relative 2305s (gameClock 2305, 39' of game).
        "10514", 1, 2280, 2325,
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
