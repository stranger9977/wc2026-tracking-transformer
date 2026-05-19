"""Space + chemistry attribution from a trained xT-regression model.

Loads a saved checkpoint, scores a match, and writes JSON artifacts + plots:

SPACE — per-player off-ball xT lift (goalkeepers excluded)
CHEMISTRY — per-pair attention from trained model

Usage:
    uv run python scripts/analyze_space_and_chemistry.py \
        --ckpt output/transformer_xt_regression.ckpt \
        --source pff --match 10502
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch

warnings.filterwarnings("ignore")

from kloppy import metrica  # noqa: E402

from wc2026_tracking_transformer.baselines.xt import xt_now
from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.metrica import load_metrica_match
from wc2026_tracking_transformer.data.loaders.pff import load_pff_match
from wc2026_tracking_transformer.data.loaders.skillcorner import load_skillcorner_match
from wc2026_tracking_transformer.data.team_colors import WC2022_TEAM_COLORS, team_color
from wc2026_tracking_transformer.model import XTRegressionLitModule

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
SPACE_JSON = OUT_DIR / "space_attribution.json"
SPACE_PNG = OUT_DIR / "space_top_players.png"
CHEM_JSON = OUT_DIR / "chemistry_pairs.json"
CHEM_PNG = OUT_DIR / "chemistry_heatmap.png"


def load_match(source: str, match_id: str, stride: int):
    if source == "metrica":
        return list(load_metrica_match(match_id, sampling_stride=stride))
    if source == "skillcorner":
        return list(load_skillcorner_match(match_id, sampling_stride=stride))
    if source == "pff":
        return list(load_pff_match(match_id, sampling_stride=stride))
    raise ValueError(source)


def get_player_metadata(source: str, match_id: str):
    """frame_id → list of dicts (one per outfield slot) with name/jersey/team/position.

    Returns:
        (frame_meta, team_names) tuple. ``frame_meta[frame_id]`` is a list of
        per-slot dicts; ``team_names`` maps team_id → display name.
    """
    if source == "metrica":
        raw = metrica.load_open_data(match_id=match_id)
    elif source == "skillcorner":
        from kloppy import skillcorner
        raw = skillcorner.load_open_data(match_id=match_id)
    elif source == "pff":
        from kloppy import pff
        from wc2026_tracking_transformer.data.loaders.pff import _resolve_match_paths
        meta_p, roster_p, tracking_p = _resolve_match_paths(match_id)
        raw = pff.load_tracking(
            meta_data=meta_p, roster_meta_data=roster_p, raw_data=tracking_p,
            only_alive=True,
        )
    else:
        raise ValueError(source)

    team_names: dict[str, str] = {}
    for t in raw.metadata.teams:
        team_names[t.team_id] = t.name or t.team_id

    frame_meta: dict[int, list[dict]] = {}
    for rf in raw.frames:
        items = list(rf.players_data.items())
        per_slot = []
        for p, _ in items:
            name = (
                getattr(p, "full_name", None)
                or getattr(p, "name", None)
                or f"#{p.jersey_no}"
            )
            per_slot.append({
                "player_id": p.player_id,
                "name": name,
                "jersey": p.jersey_no,
                "team_id": p.team.team_id,
                "team_name": team_names.get(p.team.team_id, p.team.team_id),
                "position": str(getattr(p, "starting_position", "") or ""),
            })
        frame_meta[int(rf.frame_id)] = per_slot
    return frame_meta, team_names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(OUT_DIR / "transformer_xt_regression.ckpt"))
    ap.add_argument("--source", default="pff", choices=("metrica", "skillcorner", "pff"))
    ap.add_argument("--match", default="10502")
    ap.add_argument("--stride", type=int, default=6)
    ap.add_argument("--top-n", type=int, default=15)
    ap.add_argument("--model-dim", type=int, default=96)
    args = ap.parse_args()

    print(f"[1/5] Loading checkpoint {args.ckpt} …")
    lit = XTRegressionLitModule(
        feature_len=7, model_dim=args.model_dim, num_heads=4, num_layers=2,
    )
    state = torch.load(args.ckpt, map_location="cpu")
    lit.load_state_dict(state)
    lit.eval()

    print(f"[2/5] Loading {args.source} match {args.match} (stride={args.stride}) …")
    frames = load_match(args.source, args.match, args.stride)
    print(f"      {len(frames)} frames")
    tensors = batch_frames(frames)
    x = torch.from_numpy(tensors)

    with torch.no_grad():
        encoded, attn = lit.backbone.encode_with_attention(x)
        preds = lit.head(encoded).numpy()
    lookup = xt_now(tensors)
    lift = preds - lookup
    print(f"      mean predicted future-xT = {preds.mean():.4f}, "
          f"mean lookup = {lookup.mean():.4f}, mean lift = {lift.mean():+.4f}")

    pair_attn = attn.mean(dim=(1, 2)).numpy()
    pair_attn = 0.5 * (pair_attn + np.transpose(pair_attn, (0, 2, 1)))

    print(f"[3/5] Pulling player metadata …")
    frame_meta, team_names = get_player_metadata(args.source, args.match)
    print(f"      teams: {team_names}")

    # GK mask comes straight from the features (col 5 = is_goalkeeper).
    # Shape (N, 22).
    is_gk = (tensors[:, :22, 5] > 0.5)

    # ---- SPACE: per-player off-ball xT contribution, GK excluded ----
    print(f"\n[4/5] SPACE attribution (GKs excluded) …")
    ball_to_players = pair_attn[:, 22, :22].copy()
    ball_to_players = np.clip(ball_to_players, 0, None)
    ball_to_players[is_gk] = 0.0
    row_sums = ball_to_players.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    ball_to_players /= row_sums
    per_frame_per_player = ball_to_players * lift[:, None]

    player_total: dict[str, float] = {}
    player_frames: dict[str, int] = {}
    player_info: dict[str, dict] = {}
    for i, tf in enumerate(frames):
        per_slot = frame_meta.get(tf.frame_id, [])
        for j in range(min(22, len(per_slot))):
            slot = per_slot[j]
            pid = slot["player_id"]
            player_total[pid] = player_total.get(pid, 0.0) + float(per_frame_per_player[i, j])
            player_frames[pid] = player_frames.get(pid, 0) + 1
            if pid not in player_info:
                player_info[pid] = slot

    ranking = sorted(player_total.items(), key=lambda kv: kv[1], reverse=True)
    space_top = []
    for pid, val in ranking[: args.top_n]:
        info = player_info[pid]
        space_top.append({
            "name": info["name"],
            "jersey": info["jersey"],
            "team_id": info["team_id"],
            "team_name": info["team_name"],
            "position": info["position"],
            "total_off_ball_xt": val,
            "per_frame_avg": val / max(1, player_frames[pid]),
            "frames_on_pitch": player_frames[pid],
        })

    SPACE_JSON.write_text(json.dumps({
        "source": args.source, "match": args.match,
        "teams": team_names,
        "n_frames": len(frames),
        "mean_lift_over_lookup": float(lift.mean()),
        "top_players": space_top,
    }, indent=2))
    print(f"      → {SPACE_JSON.name}")
    for r in space_top[:8]:
        print(f"        {r['team_name']:>14s} #{r['jersey']:>2}  {r['name']:<25s} "
              f"total {r['total_off_ball_xt']:+.3f}  pos={r['position']}")

    # Bar chart with WC team colors
    fig, ax = plt.subplots(figsize=(11, 6), facecolor="#0b1220")
    ax.set_facecolor("#0b1220")
    labels = [f"#{r['jersey']} {r['name']} ({r['team_name']})" for r in space_top]
    vals = [r["total_off_ball_xt"] for r in space_top]
    colors = [team_color(r["team_id"]) for r in space_top]
    ax.barh(range(len(labels)), vals, color=colors, edgecolor="white", lw=0.5)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, color="#e9f0ff", fontsize=9.5)
    ax.invert_yaxis()
    ax.set_xlabel("Total off-ball xT contribution (sum over match, GKs excluded)",
                  color="#94a3b8")
    title_teams = " vs ".join(team_names.values()) if team_names else f"{args.source} {args.match}"
    ax.set_title(f"SPACE: top off-ball xT contributors — {title_teams}",
                 color="#e9f0ff", fontsize=12)
    ax.tick_params(colors="#94a3b8")
    for s in ax.spines.values(): s.set_color("#94a3b8")
    fig.tight_layout()
    fig.savefig(SPACE_PNG, dpi=120, facecolor="#0b1220")
    plt.close(fig)
    print(f"      → {SPACE_PNG.name}")

    # ---- CHEMISTRY: per-pair attention (GKs excluded — same reason as space) ----
    print(f"\n[5/5] CHEMISTRY attribution (GKs excluded) …")
    outfield_attn = pair_attn[:, :22, :22]
    valid = (np.abs(tensors[:, :22, 0]) > 1e-6).astype(np.float32)
    not_gk = (~is_gk).astype(np.float32)        # (N, 22) — 1 if outfielder
    pair_valid = (valid * not_gk)[:, :, None] * (valid * not_gk)[:, None, :]
    weighted_attn = outfield_attn * pair_valid
    pair_sum = weighted_attn.sum(axis=0)
    pair_count = pair_valid.sum(axis=0)
    pair_count[pair_count == 0] = 1.0
    chem_matrix = pair_sum / pair_count
    np.fill_diagonal(chem_matrix, 0)

    # Use frame-0 (or median-frame) metadata for labels — exploratory; subs unhandled.
    f0_slots = frame_meta.get(frames[0].frame_id, [])
    pairs = []
    for i in range(22):
        for j in range(i + 1, 22):
            si = f0_slots[i] if i < len(f0_slots) else None
            sj = f0_slots[j] if j < len(f0_slots) else None
            if si is None or sj is None: continue
            pairs.append({
                "i_name": si["name"], "i_jersey": si["jersey"], "i_team": si["team_name"], "i_team_id": si["team_id"],
                "j_name": sj["name"], "j_jersey": sj["jersey"], "j_team": sj["team_name"], "j_team_id": sj["team_id"],
                "same_team": si["team_id"] == sj["team_id"],
                "chemistry": float(chem_matrix[i, j]),
            })
    pairs.sort(key=lambda p: p["chemistry"], reverse=True)

    chem_payload = {
        "source": args.source, "match": args.match,
        "teams": team_names,
        "top_pairs_overall": pairs[:20],
        "top_same_team_pairs": [p for p in pairs if p["same_team"]][:15],
        "top_cross_team_pairs": [p for p in pairs if not p["same_team"]][:15],
    }
    CHEM_JSON.write_text(json.dumps(chem_payload, indent=2))
    print(f"      → {CHEM_JSON.name}")
    print(f"      top 5 same-team chemistry pairs:")
    for p in chem_payload["top_same_team_pairs"][:5]:
        print(f"        {p['i_team']:>14s}  #{p['i_jersey']:>2} {p['i_name']:<22s} ↔ "
              f"#{p['j_jersey']:>2} {p['j_name']:<22s}  attn={p['chemistry']:.4f}")
    print(f"      top 3 cross-team marking pairs:")
    for p in chem_payload["top_cross_team_pairs"][:3]:
        print(f"        {p['i_team']:>14s} #{p['i_jersey']:>2} {p['i_name']:<22s} ↔ "
              f"{p['j_team']:>10s} #{p['j_jersey']:>2} {p['j_name']:<22s}  attn={p['chemistry']:.4f}")

    fig, ax = plt.subplots(figsize=(9, 7.5), facecolor="#0b1220")
    im = ax.imshow(chem_matrix, cmap="YlOrRd")
    # Tick labels: jersey numbers from frame 0
    tick_labels = [f"#{s['jersey']}" for s in f0_slots[:22]] if f0_slots else [str(i) for i in range(22)]
    ax.set_xticks(range(22)); ax.set_yticks(range(22))
    ax.set_xticklabels(tick_labels, color="#94a3b8", fontsize=7, rotation=90)
    ax.set_yticklabels(tick_labels, color="#94a3b8", fontsize=7)
    ax.set_title(f"CHEMISTRY: pair attention — {title_teams}",
                 color="#e9f0ff", fontsize=12, pad=10)
    for s in ax.spines.values(): s.set_color("#94a3b8")
    cbar = fig.colorbar(im, ax=ax)
    cbar.ax.tick_params(colors="#94a3b8")
    cbar.outline.set_edgecolor("#94a3b8")
    fig.tight_layout()
    fig.savefig(CHEM_PNG, dpi=120, facecolor="#0b1220")
    plt.close(fig)
    print(f"      → {CHEM_PNG.name}")

    print(f"\nDONE.")


if __name__ == "__main__":
    main()
