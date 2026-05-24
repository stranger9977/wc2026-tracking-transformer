"""Snapshot transformer features at every SPADL action.

For each row in ``research/data/spadl_vaep.parquet`` (PFF WC '22 actions),
locate the closest tracking frame from the matching PFF match, run the
trained ``XTRegressionLitModule`` (checkpoint ``output/transformer_xt_regression.ckpt``)
on that frame, and record a fixed set of per-action features built from the
forward prediction and the ball-token attention vector.

Output schema (one row per SPADL action, keyed by ``(game_id, action_id)``):

    game_id, action_id                       — join keys (int64)
    t_xt_pred                                — model forward(x).item()
    t_attn_top1                              — max ball→player attention weight
    t_attn_entropy                           — Shannon entropy of ball→players
    t_attn_to_actor                          — ball→player attention for the
                                               action's ``player_id`` (NaN if
                                               player not on the pitch in that
                                               frame's slot list)
    t_attn_to_teammates_sum                  — sum of ball→player for actor's teammates
    t_attn_to_opponents_sum                  — sum of ball→player for the other team
    t_state_value_proxy                      — head(ball_token).item() i.e. the
                                               regression head applied to just the
                                               ball-token embedding (a linear
                                               projection of that vector)
    t_matched                                — bool, did we find a nearby frame
    t_time_delta_s                           — seconds between action and matched frame
    t_period                                 — period of the matched frame

Multi-layer / multi-head attention is collapsed by averaging across (layers, heads)
to a single (T, T) attention matrix, then taking row 22 (the ball token) which
gives a length-22 vector of ball→player attention weights. We L1-renormalize
that 22-vector (drop the ball→ball self-attention component) before computing
entropy/sums so the metrics are interpretable as a probability distribution
over players.

Resumable: per-match shards land at
``research/data/transformer_features_shards/<game_id>.parquet``; a rerun
skips any game whose shard already exists. Final concat writes
``research/data/transformer_features.parquet``.

Usage:
    PYTHONPATH=research/src uv run python research/scripts/extract_transformer_features.py
"""
from __future__ import annotations

import argparse
import bisect
import math
import sys
import time
import traceback
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import torch

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wc2026_tracking_transformer.data.batching import batch_frames  # noqa: E402
from wc2026_tracking_transformer.data.loaders.pff import (  # noqa: E402
    DEFAULT_PFF_ROOT,
    GK_CALIBRATION_FRAMES,
    MAX_SPEED_MPS,
    _identify_goalkeepers,
    _resolve_match_paths,
)
from wc2026_tracking_transformer.data.schema import (  # noqa: E402
    FRAME_FEATURE_COLUMNS,
    NUM_PLAYERS_PER_FRAME,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    TrackingFrame,
)
from wc2026_tracking_transformer.model import XTRegressionLitModule  # noqa: E402

CKPT_PATH = REPO_ROOT / "output" / "transformer_xt_regression.ckpt"
SPADL_PATH = REPO_ROOT / "research" / "data" / "spadl_vaep.parquet"
SHARDS_DIR = REPO_ROOT / "research" / "data" / "transformer_features_shards"
OUTPUT_PATH = REPO_ROOT / "research" / "data" / "transformer_features.parquet"

# PFF SPADL convention: P1 starts at t=0, P2 starts at t=2700 (45min in seconds).
# Tracking-frame timestamps reset per period, so we compute absolute match seconds
# from (period - 1) * PERIOD_OFFSET_S + frame_ms / 1000.
PERIOD_OFFSET_S = 2700.0
ATTN_MATCH_TOL_S = 1.0  # mark t_matched=False if no frame within this window


def _load_model(ckpt_path: Path, device: torch.device) -> XTRegressionLitModule:
    """Load the regression module with the architecture used at train time."""
    lit = XTRegressionLitModule(
        feature_len=7, model_dim=96, num_heads=4, num_layers=2,
    )
    state = torch.load(ckpt_path, map_location="cpu")
    lit.load_state_dict(state)
    lit.eval().to(device)
    return lit


def _load_match_frames_and_slots(
    match_id: str | int,
    sampling_stride: int = 6,
) -> tuple[list[TrackingFrame], list[list[dict]]]:
    """Single-pass kloppy load returning (frames, per_frame_slots).

    Refactor of ``load_pff_match`` that ALSO emits the per-frame slot
    list (``{"player_id", "team_id"}`` per slot) in the same ordering as
    ``f.players_data.items()`` — i.e. lined up with the tensor produced
    by ``frame_to_tensor``. Doing this in one pass (instead of loading
    the tracking dataset twice) cuts per-match wall time roughly in half.
    """
    import bz2 as _bz2

    from kloppy import pff as _pff

    meta_path, roster_path, tracking_path = _resolve_match_paths(match_id)

    try:
        dataset = _pff.load_tracking(
            meta_data=meta_path,
            roster_meta_data=roster_path,
            raw_data=tracking_path,
            only_alive=False,
        )
    except Exception as exc:
        if any(t in str(exc).lower() for t in ("bz2", "decode", "json", "compression")):
            with _bz2.open(tracking_path, "rb") as fh:
                raw_bytes = fh.read()
            dataset = _pff.load_tracking(
                meta_data=meta_path,
                roster_meta_data=roster_path,
                raw_data=raw_bytes,
                only_alive=False,
            )
        else:
            raise

    half_len = PITCH_LENGTH_M / 2.0
    half_wid = PITCH_WIDTH_M / 2.0
    dt = float(sampling_stride) / float(dataset.frame_rate)
    gk_ids = _identify_goalkeepers(dataset, n_calib=GK_CALIBRATION_FRAMES)
    n_features = len(FRAME_FEATURE_COLUMNS)

    frames: list[TrackingFrame] = []
    per_frame_slots: list[list[dict]] = []
    prev_pos: dict[str, np.ndarray] = {}
    BALL_KEY = "__ball__"
    mid_str = str(match_id)

    for frame_idx, f in enumerate(dataset.frames):
        if frame_idx % sampling_stride != 0:
            continue
        items = list(f.players_data.items())
        if not items:
            continue
        if f.ball_coordinates is None:
            continue

        positions_m = np.array(
            [(pd_.coordinates.x * PITCH_LENGTH_M - half_len,
              pd_.coordinates.y * PITCH_WIDTH_M - half_wid)
             for _, pd_ in items],
            dtype=np.float32,
        )
        ball_m = np.array(
            [f.ball_coordinates.x * PITCH_LENGTH_M - half_len,
             f.ball_coordinates.y * PITCH_WIDTH_M - half_wid],
            dtype=np.float32,
        )

        velocities = np.zeros_like(positions_m)
        for i, (player, _) in enumerate(items):
            prev = prev_pos.get(player.player_id)
            if prev is not None:
                v = (positions_m[i] - prev) / dt
                velocities[i] = np.clip(v, -MAX_SPEED_MPS, MAX_SPEED_MPS)
            prev_pos[player.player_id] = positions_m[i]

        prev_b = prev_pos.get(BALL_KEY)
        ball_v = (
            np.clip((ball_m - prev_b) / dt, -MAX_SPEED_MPS, MAX_SPEED_MPS)
            if prev_b is not None
            else np.zeros(2, dtype=np.float32)
        )
        prev_pos[BALL_KEY] = ball_m

        dists = np.linalg.norm(positions_m - ball_m, axis=1)
        closest_idx = int(np.argmin(dists))
        in_possession_team = items[closest_idx][0].team

        players_feat = np.zeros((NUM_PLAYERS_PER_FRAME, n_features), dtype=np.float32)
        slots_this_frame: list[dict] = []
        for i, (player, _) in enumerate(items[:NUM_PLAYERS_PER_FRAME]):
            is_attacking = 1.0 if player.team == in_possession_team else -1.0
            is_gk = 1.0 if player.player_id in gk_ids else 0.0
            has_poss = 1.0 if i == closest_idx else 0.0
            players_feat[i, 0] = positions_m[i, 0] / half_len
            players_feat[i, 1] = positions_m[i, 1] / half_wid
            players_feat[i, 2] = velocities[i, 0]
            players_feat[i, 3] = velocities[i, 1]
            players_feat[i, 4] = is_attacking
            players_feat[i, 5] = is_gk
            players_feat[i, 6] = has_poss
            slots_this_frame.append({
                "player_id": player.player_id,
                "team_id": player.team.team_id,
            })

        ball_feat = np.zeros(n_features, dtype=np.float32)
        ball_feat[0] = ball_m[0] / half_len
        ball_feat[1] = ball_m[1] / half_wid
        ball_feat[2] = ball_v[0]
        ball_feat[3] = ball_v[1]

        frames.append(TrackingFrame(
            match_id=f"pff_{mid_str}",
            period=f.period.id,
            frame_id=int(f.frame_id),
            timestamp_ms=int(f.timestamp.total_seconds() * 1000),
            players=players_feat,
            ball=ball_feat,
            in_possession_team_id=in_possession_team.team_id if in_possession_team else None,
        ))
        per_frame_slots.append(slots_this_frame)

    return frames, per_frame_slots


def _attn_metrics_for_frame(
    attn_row: np.ndarray,
    slots: list[dict],
    actor_player_id: str | None,
) -> tuple[float, float, float, float, float]:
    """Compute attention-derived per-action metrics.

    Args:
        attn_row: Shape (22,) — ball-token attention to each of the 22 player
            slots (already with the ball→ball self-attention dropped, but NOT
            yet renormalized).
        slots: Per-slot metadata (player_id, team_id).
        actor_player_id: ``player_id`` of the SPADL actor (string).

    Returns:
        (top1, entropy, to_actor, to_teammates_sum, to_opponents_sum)
        — all on the renormalized distribution. to_actor is NaN if the player
        is not in the slot list for this frame.
    """
    # Use only the slots actually present (some frames may have <22 players if
    # a sub is mid-flight or kloppy lost a tracker). Pad with zeros so shape
    # stays (22,).
    n_slots = min(22, len(slots))
    valid_mask = np.zeros(22, dtype=bool)
    valid_mask[:n_slots] = True

    masked = np.where(valid_mask, attn_row, 0.0)
    total = float(masked.sum())
    if total <= 0:
        nan = float("nan")
        return nan, nan, nan, nan, nan
    probs = masked / total

    top1 = float(probs.max())
    # Shannon entropy in nats, restricted to nonzero entries.
    nz = probs[probs > 0]
    entropy = float(-(nz * np.log(nz)).sum())

    actor_slot = None
    actor_team_id = None
    if actor_player_id is not None:
        actor_str = str(actor_player_id)
        for j, s in enumerate(slots[:n_slots]):
            if str(s["player_id"]) == actor_str:
                actor_slot = j
                actor_team_id = s["team_id"]
                break

    if actor_slot is None:
        return top1, entropy, float("nan"), float("nan"), float("nan")

    to_actor = float(probs[actor_slot])
    teammates_sum = 0.0
    opponents_sum = 0.0
    for j, s in enumerate(slots[:n_slots]):
        if j == actor_slot:
            continue
        if s["team_id"] == actor_team_id:
            teammates_sum += float(probs[j])
        else:
            opponents_sum += float(probs[j])
    return top1, entropy, to_actor, teammates_sum, opponents_sum


def _process_match(
    game_id: int,
    spadl_match: pd.DataFrame,
    lit: XTRegressionLitModule,
    device: torch.device,
    sampling_stride: int = 6,
    batch_size: int = 256,
) -> pd.DataFrame:
    """Run the model for one match, return per-action features."""
    # 1) Load tracking frames + matching per-frame slot lists in a single
    # kloppy pass (saves ~50% of per-match wall time vs. loading twice).
    frames, per_frame_slots = _load_match_frames_and_slots(
        match_id=game_id, sampling_stride=sampling_stride,
    )
    if not frames:
        raise RuntimeError(f"loader produced 0 frames for game {game_id}")

    # 2) Tensorize and run the model in batches, collecting xT pred, ball-token
    # attention, and ball-token state value proxy per frame.
    tensors = batch_frames(frames)  # (N, 23, 7)
    n_frames = tensors.shape[0]

    xt_preds = np.zeros(n_frames, dtype=np.float32)
    state_proxies = np.zeros(n_frames, dtype=np.float32)
    ball_attn_per_player = np.zeros((n_frames, 22), dtype=np.float32)

    x_all = torch.from_numpy(tensors)
    with torch.no_grad():
        for start in range(0, n_frames, batch_size):
            end = min(start + batch_size, n_frames)
            xb = x_all[start:end].to(device)
            encoded, attn = lit.backbone.encode_with_attention(xb)
            # encoded: (b, 23, model_dim); attn: (b, num_layers, num_heads, 23, 23)
            mean_attn = attn.mean(dim=(1, 2))  # (b, 23, 23)
            # Ball is token index 22; outgoing attention row 22 -> player columns 0..21
            ball_to_players = mean_attn[:, 22, :22]  # (b, 22)

            # Forward xT scalar (same path as lit.forward).
            xt_b = lit.head(encoded)  # (b,)

            # State-value proxy: feed only the ball-token embedding through
            # the regression head's MLP (head expects (B, model_dim) after the
            # mean-pool inside its forward). The head sequential is stored at
            # ``lit.head.head`` and accepts any (B, model_dim) input.
            ball_token_emb = encoded[:, 22, :]  # (b, model_dim)
            state_proxy_b = lit.head.head(ball_token_emb).squeeze(-1)  # (b,)

            ball_attn_per_player[start:end] = ball_to_players.cpu().numpy()
            xt_preds[start:end] = xt_b.cpu().numpy()
            state_proxies[start:end] = state_proxy_b.cpu().numpy()

    # 3) Sorted timestamps + parallel frame indices for nearest-neighbor lookup.
    # Use absolute match-clock seconds = (period - 1) * PERIOD_OFFSET_S + ts_ms/1000
    # so we can binary-search against SPADL time_seconds.
    frame_times = np.array(
        [(tf.period - 1) * PERIOD_OFFSET_S + tf.timestamp_ms / 1000.0 for tf in frames],
        dtype=np.float64,
    )
    # frame_times may not be perfectly monotonic across period boundaries (period
    # 2 starts at 2700 but its timestamp_ms restarts), but since we offset by
    # period, the absolute clock is monotonic per period and concatenates cleanly.
    # Sort to be safe.
    sort_idx = np.argsort(frame_times)
    sorted_times = frame_times[sort_idx]

    rows = []
    for row in spadl_match.itertuples(index=False):
        action_id = int(row.action_id)
        t = float(row.time_seconds)
        # Locate the frame whose absolute time is closest to t via binary search.
        i = bisect.bisect_left(sorted_times, t)
        candidates = []
        if i > 0:
            candidates.append(i - 1)
        if i < len(sorted_times):
            candidates.append(i)
        best_idx_in_sorted = None
        best_dt = None
        for c in candidates:
            dt = abs(sorted_times[c] - t)
            if best_dt is None or dt < best_dt:
                best_dt = dt
                best_idx_in_sorted = c
        if best_idx_in_sorted is None or best_dt is None or best_dt > ATTN_MATCH_TOL_S:
            rows.append({
                "game_id": int(game_id),
                "action_id": action_id,
                "t_xt_pred": float("nan"),
                "t_attn_top1": float("nan"),
                "t_attn_entropy": float("nan"),
                "t_attn_to_actor": float("nan"),
                "t_attn_to_teammates_sum": float("nan"),
                "t_attn_to_opponents_sum": float("nan"),
                "t_state_value_proxy": float("nan"),
                "t_matched": False,
                "t_time_delta_s": float("nan") if best_dt is None else float(best_dt),
                "t_period": int(row.period_id),
            })
            continue

        frame_idx = int(sort_idx[best_idx_in_sorted])
        tf = frames[frame_idx]
        slots = per_frame_slots[frame_idx]
        top1, entropy, to_actor, tm_sum, op_sum = _attn_metrics_for_frame(
            ball_attn_per_player[frame_idx],
            slots,
            None if pd.isna(row.player_id) else row.player_id,
        )
        rows.append({
            "game_id": int(game_id),
            "action_id": action_id,
            "t_xt_pred": float(xt_preds[frame_idx]),
            "t_attn_top1": top1,
            "t_attn_entropy": entropy,
            "t_attn_to_actor": to_actor,
            "t_attn_to_teammates_sum": tm_sum,
            "t_attn_to_opponents_sum": op_sum,
            "t_state_value_proxy": float(state_proxies[frame_idx]),
            "t_matched": True,
            "t_time_delta_s": float(best_dt),
            "t_period": int(tf.period),
        })

    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(CKPT_PATH))
    ap.add_argument("--spadl", default=str(SPADL_PATH))
    ap.add_argument("--shards-dir", default=str(SHARDS_DIR))
    ap.add_argument("--output", default=str(OUTPUT_PATH))
    ap.add_argument("--stride", type=int, default=6,
                    help="PFF frame stride (6 -> 5 Hz at native 30 Hz)")
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--limit-matches", type=int, default=None,
                    help="Optional cap on number of matches (for debugging)")
    args = ap.parse_args()

    shards_dir = Path(args.shards_dir)
    shards_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output)

    spadl = pd.read_parquet(args.spadl)
    print(f"Loaded SPADL: {len(spadl):,} actions across {spadl.game_id.nunique()} matches")

    # Restrict to games for which PFF tracking exists on disk; for the rest,
    # we still emit NaN feature rows in the final parquet so the join shape
    # stays identical.
    tracking_dir = DEFAULT_PFF_ROOT / "Tracking Data"
    have_pff = set(
        int(p.stem.replace(".jsonl", "")) for p in tracking_dir.glob("*.jsonl.bz2")
    )
    all_game_ids = sorted(int(g) for g in spadl.game_id.unique())
    game_ids = [g for g in all_game_ids if g in have_pff]
    missing_ids = [g for g in all_game_ids if g not in have_pff]
    if args.limit_matches:
        game_ids = game_ids[: args.limit_matches]
    print(f"  PFF tracking available for {len(game_ids)} / {len(all_game_ids)} games "
          f"({len(missing_ids)} missing)")

    device = torch.device("cuda" if torch.cuda.is_available()
                          else "mps" if torch.backends.mps.is_available()
                          else "cpu")
    print(f"Device: {device}")
    print(f"Loading checkpoint: {args.ckpt}")
    lit = _load_model(Path(args.ckpt), device)

    t0 = time.time()
    failed: list[tuple[int, str]] = []
    n_processed = 0
    n_skipped_resume = 0

    for game_id in game_ids:
        shard_path = shards_dir / f"{game_id}.parquet"
        if shard_path.exists():
            n_skipped_resume += 1
            continue
        spadl_match = spadl[spadl.game_id == game_id].copy()
        if spadl_match.empty:
            continue
        try:
            df = _process_match(
                game_id=game_id,
                spadl_match=spadl_match,
                lit=lit,
                device=device,
                sampling_stride=args.stride,
                batch_size=args.batch_size,
            )
            df.to_parquet(shard_path, index=False)
            n_processed += 1
            dt = time.time() - t0
            matched = int(df["t_matched"].sum())
            print(f"  [{n_processed:>2}] game {game_id}: {len(df):>4} actions, "
                  f"{matched} matched ({100*matched/len(df):.1f}%), "
                  f"mean H={df['t_attn_entropy'].mean():.3f}, "
                  f"max xT={df['t_xt_pred'].max():.3f}  "
                  f"elapsed {dt:.1f}s")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            failed.append((game_id, msg))
            print(f"  [SKIP] game {game_id}: {msg}")
            traceback.print_exc(limit=2)

    print()
    print(f"Resume-skipped {n_skipped_resume} shards from disk.")

    # Aggregate: concat shards, then append NaN rows for games with no tracking
    # so the output covers every SPADL action.
    shard_paths = sorted(shards_dir.glob("*.parquet"))
    parts = [pd.read_parquet(p) for p in shard_paths]
    if parts:
        feat_df = pd.concat(parts, ignore_index=True)
    else:
        feat_df = pd.DataFrame(columns=[
            "game_id", "action_id", "t_xt_pred", "t_attn_top1", "t_attn_entropy",
            "t_attn_to_actor", "t_attn_to_teammates_sum", "t_attn_to_opponents_sum",
            "t_state_value_proxy", "t_matched", "t_time_delta_s", "t_period",
        ])

    # Build NaN rows for SPADL actions in the missing-PFF games.
    missing_actions = spadl[spadl.game_id.isin(missing_ids)][["game_id", "action_id", "period_id"]]
    if not missing_actions.empty:
        nan_rows = pd.DataFrame({
            "game_id": missing_actions["game_id"].astype("int64").values,
            "action_id": missing_actions["action_id"].astype("int64").values,
            "t_xt_pred": np.nan,
            "t_attn_top1": np.nan,
            "t_attn_entropy": np.nan,
            "t_attn_to_actor": np.nan,
            "t_attn_to_teammates_sum": np.nan,
            "t_attn_to_opponents_sum": np.nan,
            "t_state_value_proxy": np.nan,
            "t_matched": False,
            "t_time_delta_s": np.nan,
            "t_period": missing_actions["period_id"].astype("int64").values,
        })
        feat_df = pd.concat([feat_df, nan_rows], ignore_index=True)

    # Final canonical sort + cast.
    feat_df["game_id"] = feat_df["game_id"].astype("int64")
    feat_df["action_id"] = feat_df["action_id"].astype("int64")
    feat_df = feat_df.sort_values(["game_id", "action_id"]).reset_index(drop=True)
    feat_df.to_parquet(output_path, index=False)

    elapsed = time.time() - t0
    n_actions_total = len(feat_df)
    matched = int(feat_df["t_matched"].sum())
    unmatched = n_actions_total - matched
    mean_entropy = float(feat_df["t_attn_entropy"].mean()) if matched else float("nan")
    max_xt = float(feat_df["t_xt_pred"].max()) if matched else float("nan")

    print()
    print(f"Wrote {output_path} ({n_actions_total:,} rows)")
    print(
        f"Summary: {n_processed} matches processed (+{n_skipped_resume} resumed), "
        f"{matched} actions matched to a frame, {unmatched} actions with no nearby frame, "
        f"mean t_attn_entropy={mean_entropy:.4f}, max t_xt_pred={max_xt:.4f}."
    )
    if failed:
        print(f"Failures ({len(failed)}):")
        for gid, err in failed:
            print(f"  game {gid}: {err}")
    print(f"Total wall time: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
