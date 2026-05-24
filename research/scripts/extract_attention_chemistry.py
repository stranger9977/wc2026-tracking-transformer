"""Per-match player-pair attention chemistry extraction.

For every PFF World Cup '22 match available under ``PFF_ROOT``, run the
trained xT-regression transformer over all (stride=6, 5 Hz) tracking
frames and accumulate per-pair attention. Symmetrize, drop the ball
token, and emit one row per unordered player pair per match.

Output schema (``research/data/attention_chemistry.parquet``):

    game_id (int)
    team_id (str)        # the team_id used to derive same_team — set to
                         # player_p's team_id; same as player_q's when
                         # ``same_team`` is True
    player_p (int)
    name_p (str)
    player_q (int)
    name_q (str)
    same_team (bool)
    pair_attention (float)  # sum over frames of symmetrized attention

Usage:
    PYTHONPATH=research/src uv run python research/scripts/extract_attention_chemistry.py
"""

from __future__ import annotations

import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "research" / "src"))

from kloppy import pff as kloppy_pff  # noqa: E402

from wc2026_tracking_transformer.data.batching import batch_frames  # noqa: E402
from wc2026_tracking_transformer.data.loaders.pff import (  # noqa: E402
    _resolve_match_paths,
    load_pff_match,
)
from wc2026_tracking_transformer.data.schema import (  # noqa: E402
    FRAME_FEATURE_COLUMNS,
    NUM_PLAYERS_PER_FRAME,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    TrackingFrame,
)
from wc2026_tracking_transformer.model import XTRegressionLitModule  # noqa: E402

from chemistry.loaders.pff_paths import event_files  # noqa: E402

MAX_SPEED_MPS = 25.0

OUT_PATH = REPO_ROOT / "research" / "data" / "attention_chemistry.parquet"
CKPT_PATH = REPO_ROOT / "output" / "transformer_xt_regression.ckpt"
LINEUPS_PATH = REPO_ROOT / "research" / "data" / "minutes" / "lineups.parquet"

# Match the trained checkpoint architecture (see train_xt_regression.py: model_dim=96).
MODEL_DIM = 96
NUM_HEADS = 4
NUM_LAYERS = 2
SAMPLING_STRIDE = 6  # 5 Hz from PFF's 30 Hz native
BATCH_SIZE = 256
NUM_PLAYER_SLOTS = 22  # ball is token 22


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_model(device: torch.device) -> XTRegressionLitModule:
    lit = XTRegressionLitModule(
        feature_len=7,
        model_dim=MODEL_DIM,
        num_heads=NUM_HEADS,
        num_layers=NUM_LAYERS,
    )
    state = torch.load(CKPT_PATH, map_location="cpu", weights_only=True)
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    lit.load_state_dict(state)
    lit.eval()
    lit.to(device)
    return lit


def _stream_match_combined(match_id: str):
    """Single-pass kloppy load that yields per-stride (tensor_row, slot_ids).

    Returns:
        (gen, player_info) where gen yields tuples
        ``(frame_tensor (23,7), ids (n_slots,) np.int64, team_names map)``
        on every accepted (stride-sampled, ball-present) frame, and
        ``player_info`` is incrementally populated as a dict
        player_id -> {name, team_id}.

    Mirrors the normalization logic in ``data/loaders/pff.py::load_pff_match``
    but extracts per-slot ids in the same loop to avoid loading kloppy twice.
    """
    import bz2
    meta_p, roster_p, tracking_p = _resolve_match_paths(match_id)
    try:
        dataset = kloppy_pff.load_tracking(
            meta_data=meta_p, roster_meta_data=roster_p, raw_data=tracking_p,
            only_alive=False,
        )
    except Exception as e:
        if any(t in str(e).lower() for t in ("bz2", "decode", "json", "compression")):
            with bz2.open(tracking_p, "rb") as fh:
                raw_bytes = fh.read()
            dataset = kloppy_pff.load_tracking(
                meta_data=meta_p, roster_meta_data=roster_p, raw_data=raw_bytes,
                only_alive=False,
            )
        else:
            raise

    team_names: dict[str, str] = {
        t.team_id: (t.name or t.team_id) for t in dataset.metadata.teams
    }

    # GK identification: copied logic from loader.
    n_calib = min(200, len(dataset.frames))
    sums: dict[str, list[float]] = {}
    pteams: dict[str, str] = {}
    for f in dataset.frames[:n_calib]:
        for pl, pd_ in f.players_data.items():
            if pd_.coordinates is None:
                continue
            pid_s = pl.player_id
            if pid_s not in sums:
                sums[pid_s] = [0.0, 0]
                pteams[pid_s] = pl.team.team_id
            sums[pid_s][0] += pd_.coordinates.x
            sums[pid_s][1] += 1
    mean_x = {pid: v[0] / v[1] for pid, v in sums.items() if v[1] > 0}
    gk_ids: set[str] = set()
    for team_id in set(pteams.values()):
        members = {pid: x for pid, x in mean_x.items() if pteams[pid] == team_id}
        if not members:
            continue
        team_mean = sum(members.values()) / len(members)
        best_pid, best_score = None, -1.0
        for pid, x in members.items():
            score = abs(x - team_mean)
            if score > best_score:
                best_score, best_pid = score, pid
        if best_pid is not None:
            gk_ids.add(best_pid)

    half_len = PITCH_LENGTH_M / 2.0
    half_wid = PITCH_WIDTH_M / 2.0
    dt = float(SAMPLING_STRIDE) / float(dataset.frame_rate)
    n_features = len(FRAME_FEATURE_COLUMNS)

    prev_pos: dict[str, np.ndarray] = {}
    BALL_KEY = "__ball__"

    player_info: dict[int, dict] = {}

    out_tensors: list[np.ndarray] = []
    out_ids: list[np.ndarray] = []

    for frame_idx, f in enumerate(dataset.frames):
        if frame_idx % SAMPLING_STRIDE != 0:
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
        for i, (pl, _) in enumerate(items):
            prev = prev_pos.get(pl.player_id)
            if prev is not None:
                v = (positions_m[i] - prev) / dt
                velocities[i] = np.clip(v, -MAX_SPEED_MPS, MAX_SPEED_MPS)
            prev_pos[pl.player_id] = positions_m[i]

        prev_b = prev_pos.get(BALL_KEY)
        ball_v = (
            np.clip((ball_m - prev_b) / dt, -MAX_SPEED_MPS, MAX_SPEED_MPS)
            if prev_b is not None else np.zeros(2, dtype=np.float32)
        )
        prev_pos[BALL_KEY] = ball_m

        dists = np.linalg.norm(positions_m - ball_m, axis=1)
        closest_idx = int(np.argmin(dists))
        in_poss_team = items[closest_idx][0].team

        n_slots = min(NUM_PLAYERS_PER_FRAME, len(items))
        players_feat = np.zeros((NUM_PLAYERS_PER_FRAME, n_features), dtype=np.float32)
        slot_ids = np.full(NUM_PLAYERS_PER_FRAME, -1, dtype=np.int64)

        for i in range(n_slots):
            pl, _ = items[i]
            is_attacking = 1.0 if pl.team == in_poss_team else -1.0
            is_gk = 1.0 if pl.player_id in gk_ids else 0.0
            has_poss = 1.0 if i == closest_idx else 0.0
            players_feat[i, 0] = positions_m[i, 0] / half_len
            players_feat[i, 1] = positions_m[i, 1] / half_wid
            players_feat[i, 2] = velocities[i, 0]
            players_feat[i, 3] = velocities[i, 1]
            players_feat[i, 4] = is_attacking
            players_feat[i, 5] = is_gk
            players_feat[i, 6] = has_poss
            try:
                pid_int = int(pl.player_id)
            except (TypeError, ValueError):
                pid_int = -1
            slot_ids[i] = pid_int
            if pid_int >= 0 and pid_int not in player_info:
                name = (
                    getattr(pl, "full_name", None)
                    or getattr(pl, "name", None)
                    or f"#{pl.jersey_no}"
                )
                player_info[pid_int] = {
                    "name": name,
                    "team_id": pl.team.team_id,
                }

        ball_feat = np.zeros(n_features, dtype=np.float32)
        ball_feat[0] = ball_m[0] / half_len
        ball_feat[1] = ball_m[1] / half_wid
        ball_feat[2] = ball_v[0]
        ball_feat[3] = ball_v[1]

        frame_tensor = np.zeros(
            (NUM_PLAYERS_PER_FRAME + 1, n_features), dtype=np.float32
        )
        frame_tensor[:NUM_PLAYERS_PER_FRAME] = players_feat
        frame_tensor[NUM_PLAYERS_PER_FRAME] = ball_feat

        out_tensors.append(frame_tensor)
        out_ids.append(slot_ids)

    return out_tensors, out_ids, player_info, team_names


def process_match(
    match_id: str,
    lit: XTRegressionLitModule,
    device: torch.device,
) -> tuple[dict[tuple[int, int], float], dict[int, dict]]:
    """Process a single match, returning:

    - pair_sums: dict mapping (player_id_a, player_id_b) with a < b
      to summed symmetrized attention across all frames where BOTH
      players were on-pitch.
    - player_info: dict mapping player_id -> {name, team_id} (last seen).
    """
    out_tensors, out_ids, player_info, _team_names = _stream_match_combined(match_id)
    if not out_tensors:
        return {}, {}

    pair_sums: dict[tuple[int, int], float] = defaultdict(float)
    n_frames = len(out_tensors)
    # Precompute upper-triangle indices for vectorized pair extraction.
    iu, ju = np.triu_indices(NUM_PLAYER_SLOTS, k=1)

    for start in range(0, n_frames, BATCH_SIZE):
        end = min(start + BATCH_SIZE, n_frames)
        tensors_np = np.stack(out_tensors[start:end], axis=0)  # (B, 23, 7)
        x = torch.from_numpy(tensors_np).to(device)
        with torch.no_grad():
            _, attn = lit.backbone.encode_with_attention(x)
        # Average across layers + heads -> (B, T, T)
        pair_attn = attn.mean(dim=(1, 2)).cpu().numpy()
        # Symmetrize and drop the ball token (index 22).
        pair_attn = pair_attn + np.transpose(pair_attn, (0, 2, 1))
        pair_attn = pair_attn[:, :NUM_PLAYER_SLOTS, :NUM_PLAYER_SLOTS]

        # Batched pair extraction.
        # vals: (B, n_pairs), ids: (B, 22)
        batch_vals = pair_attn[:, iu, ju]  # (B, n_pairs)
        ids_arr = np.stack(out_ids[start:end], axis=0)  # (B, 22)
        a_arr = np.minimum(ids_arr[:, iu], ids_arr[:, ju])
        b_arr = np.maximum(ids_arr[:, iu], ids_arr[:, ju])
        mask = (ids_arr[:, iu] >= 0) & (ids_arr[:, ju] >= 0) & (ids_arr[:, iu] != ids_arr[:, ju])

        # Flatten + filter.
        a_flat = a_arr[mask]
        b_flat = b_arr[mask]
        v_flat = batch_vals[mask]
        # Group-sum per (a, b) using a structured key. 64-bit composite.
        keys = a_flat.astype(np.int64) * (1 << 32) + b_flat.astype(np.int64)
        uniq_keys, inv = np.unique(keys, return_inverse=True)
        grouped = np.zeros(uniq_keys.shape[0], dtype=np.float64)
        np.add.at(grouped, inv, v_flat)
        # Decode back.
        uniq_a = (uniq_keys >> 32).astype(np.int64)
        uniq_b = (uniq_keys & ((1 << 32) - 1)).astype(np.int64)
        for k in range(uniq_keys.shape[0]):
            pair_sums[(int(uniq_a[k]), int(uniq_b[k]))] += float(grouped[k])

    return dict(pair_sums), player_info


def main() -> int:
    if OUT_PATH.exists():
        print(f"[skip] {OUT_PATH} already exists; remove to regenerate.")
        df = pd.read_parquet(OUT_PATH)
        print(f"  current: {len(df)} rows, {df.game_id.nunique()} matches")
        return 0

    device = pick_device()
    print(f"[init] device = {device}")
    print(f"[init] loading model from {CKPT_PATH}")
    lit = load_model(device)

    # Lineups for same-team verification (player_id -> team_id per game).
    lineups = pd.read_parquet(LINEUPS_PATH)
    lineup_team: dict[tuple[int, int], str] = {
        (int(r.game_id), int(r.player_id)): str(r.team_id)
        for r in lineups.itertuples(index=False)
    }

    matches = [int(p.stem) for p in event_files()]
    print(f"[init] {len(matches)} PFF matches to process")

    rows: list[dict] = []
    t0 = time.time()
    for mi, match_id in enumerate(matches, 1):
        tm0 = time.time()
        match_id_s = str(match_id)
        try:
            pair_sums, player_info = process_match(match_id_s, lit, device)
        except Exception as e:  # noqa: BLE001
            print(f"  [{mi}/{len(matches)}] match {match_id} FAILED: {e}")
            traceback.print_exc()
            continue
        n_pairs = len(pair_sums)
        if n_pairs == 0:
            print(f"  [{mi}/{len(matches)}] match {match_id}: no pairs?")
            continue

        for (pi, pj), val in pair_sums.items():
            info_i = player_info.get(pi, {})
            info_j = player_info.get(pj, {})
            # Prefer lineup parquet for team_id (authoritative); fall back to
            # kloppy metadata.
            team_i = lineup_team.get((match_id, pi)) or info_i.get("team_id", "")
            team_j = lineup_team.get((match_id, pj)) or info_j.get("team_id", "")
            same = bool(team_i and team_j and team_i == team_j)
            rows.append({
                "game_id": match_id,
                "team_id": team_i,
                "player_p": pi,
                "name_p": info_i.get("name", ""),
                "player_q": pj,
                "name_q": info_j.get("name", ""),
                "same_team": same,
                "pair_attention": val,
            })

        dt = time.time() - tm0
        print(
            f"  [{mi}/{len(matches)}] match {match_id}: "
            f"{n_pairs} pairs in {dt:.1f}s "
            f"(elapsed {time.time()-t0:.1f}s)"
        )

    if not rows:
        print("[error] no rows produced; aborting write.")
        return 1

    df = pd.DataFrame(rows)
    df = df.astype({
        "game_id": "int64",
        "team_id": "string",
        "player_p": "int64",
        "name_p": "string",
        "player_q": "int64",
        "name_q": "string",
        "same_team": "bool",
        "pair_attention": "float64",
    })
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"\n[write] wrote {len(df)} rows to {OUT_PATH}")
    print(f"        matches: {df.game_id.nunique()}, "
          f"unique unordered pairs: {df.groupby(['player_p','player_q']).ngroups}")

    # Verification: top-10 same-team pairs across the corpus.
    same_df = df[df.same_team].copy()
    corpus = (
        same_df.groupby(["player_p", "player_q", "name_p", "name_q", "team_id"], dropna=False)
        ["pair_attention"].sum().reset_index()
        .sort_values("pair_attention", ascending=False)
    )
    print(f"\nTop 10 same-team attention pairs across the corpus:")
    for i, r in enumerate(corpus.head(10).itertuples(index=False), 1):
        print(
            f"  {i:>2}. [{r.team_id}] {r.name_p} ↔ {r.name_q}  "
            f"attn={r.pair_attention:.2f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
