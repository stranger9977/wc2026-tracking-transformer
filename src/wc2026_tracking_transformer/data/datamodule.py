"""Lightning DataModule for soccer tracking.

Sources:

  * ``source="synthetic"`` — random tensors of the right shape. Lets the full
    training pipeline (Trainer / DDP / mixed precision / logging) be
    smoke-tested on CPU before any real data is downloaded.
  * ``source="metrica"`` — real tracking data from Metrica's open-data
    sample (2 matches via :mod:`kloppy.metrica`). Phase-1 labels are derived
    from tracking only: P(ball enters attacking third within K seconds)
    and P(ball enters defensive third within K seconds). Goal-anchored
    labels will replace these once events are wired in.
  * ``source="dfl"``/``"skillcorner"``/``"pff"`` — :py:exc:`NotImplementedError`
    until their loaders are written.

The split is **match-level**: frames from one match never cross train/val.
"""

from __future__ import annotations

from pathlib import Path

import lightning.pytorch as pl
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from wc2026_tracking_transformer.data.batching import batch_frames
from wc2026_tracking_transformer.data.loaders.metrica import (
    OPEN_DATA_MATCH_IDS,
    goal_and_shot_labels_from_events,
    load_metrica_events,
    load_metrica_match,
)
from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_TOKENS_PER_FRAME,
)


class SyntheticFrameDataset(Dataset):
    """Random (frame, label) pairs of the right shapes.

    Useful only for wiring tests — bypassed entirely once a real
    source loader exists.
    """

    def __init__(
        self,
        n_samples: int = 1024,
        feature_len: int = len(FRAME_FEATURE_COLUMNS),
        num_tokens: int = NUM_TOKENS_PER_FRAME,
        seed: int = 0,
    ) -> None:
        self.n = n_samples
        self.feature_len = feature_len
        self.num_tokens = num_tokens
        rng = np.random.default_rng(seed)
        self.frames = rng.standard_normal(
            (n_samples, num_tokens, feature_len)
        ).astype(np.float32)
        self.labels = (rng.random((n_samples, 2)) < 0.05).astype(np.float32)

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        return (
            torch.from_numpy(self.frames[idx]),
            torch.from_numpy(self.labels[idx]),
        )


class MetricaFrameDataset(Dataset):
    """Real Metrica frames + labels.

    Two label modes:

    ``label_mode="thirds"`` (phase-1, tracking-only)
        Head 0 = ball reaches attacking third in K seconds.
        Head 1 = ball reaches defensive third in K seconds.
        Dense positives (~40-55%), useful when events aren't reachable.

    ``label_mode="events"`` (phase-2, real)
        Head 0 = a SHOT happens in the next K seconds (denser, ~5-10% rate).
        Head 1 = a GOAL happens in the next K seconds (sparse, ~0.5-1%
        rate at 5 Hz).
        Real soccer semantics, but goals are rare so head-1 is hard to
        learn from 2 matches alone. Negative sampling around events
        (Section 6 of the deck) is the principled fix.

    Args:
        match_ids: Metrica open-data match ids to load.
        k_seconds: Look-ahead window for the labels.
        frame_rate_hz: Effective sampling rate after stride.
        sampling_stride: Downsample stride passed to the loader.
        label_mode: ``"thirds"`` or ``"events"``.
    """

    THIRD_THRESHOLD = 1.0 / 3.0  # in x_norm space [-1, 1]

    def __init__(
        self,
        match_ids: tuple[str, ...] | None = None,
        k_seconds: float = 10.0,
        frame_rate_hz: float = 5.0,
        sampling_stride: int = 5,
        label_mode: str = "thirds",
    ) -> None:
        if match_ids is None:
            match_ids = OPEN_DATA_MATCH_IDS
        if label_mode not in {"thirds", "events"}:
            raise ValueError(f"label_mode must be 'thirds' or 'events', got {label_mode!r}")

        future_window = int(round(k_seconds * frame_rate_hz))
        all_frame_tensors: list[np.ndarray] = []
        all_labels: list[np.ndarray] = []

        for mid in match_ids:
            frames = list(load_metrica_match(mid, sampling_stride=sampling_stride))
            if len(frames) <= future_window:
                continue
            tensors = batch_frames(frames)  # (N, 23, 7)
            n = len(frames)

            if label_mode == "thirds":
                ball_x = tensors[:, -1, 0]      # ball token's x_norm
                attacks_third = ball_x > self.THIRD_THRESHOLD
                defends_third = ball_x < -self.THIRD_THRESHOLD
                usable = n - future_window
                labels = np.zeros((usable, 2), dtype=np.float32)
                for i in range(usable):
                    w = slice(i + 1, i + 1 + future_window)
                    labels[i, 0] = float(attacks_third[w].any())
                    labels[i, 1] = float(defends_third[w].any())
                all_frame_tensors.append(tensors[:usable])
                all_labels.append(labels)
            else:  # "events"
                events_df = load_metrica_events(mid)
                labels_full = goal_and_shot_labels_from_events(
                    events_df,
                    n_frames_sampled=n,
                    k_seconds=k_seconds,
                    sampling_stride=sampling_stride,
                )
                usable = n - future_window
                all_frame_tensors.append(tensors[:usable])
                all_labels.append(labels_full[:usable])

        if not all_frame_tensors:
            raise RuntimeError(
                "MetricaFrameDataset: no usable frames loaded — check that "
                "kloppy can reach the Metrica open-data GitHub repo."
            )

        self.frames = np.concatenate(all_frame_tensors, axis=0)
        self.labels = np.concatenate(all_labels, axis=0)
        self.label_mode = label_mode

    def __len__(self) -> int:
        return self.frames.shape[0]

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        return (
            torch.from_numpy(self.frames[idx]),
            torch.from_numpy(self.labels[idx]),
        )


class SoccerTrackingDataModule(pl.LightningDataModule):
    """DataModule with synthetic + real-data paths.

    Args:
        source: ``"synthetic"`` (default), ``"metrica"`` (real), or one of
            ``"dfl"``/``"skillcorner"``/``"pff"`` (NotImplementedError until
            their loaders are written).
        data_root: Override the default raw-data directory for the source.
        batch_size: Batch size for all loaders.
        num_workers: DataLoader workers.
        n_synthetic_train/n_synthetic_val: sample counts for synthetic mode.
        metrica_k_seconds: Look-ahead window for phase-1 placeholder labels.
        metrica_sampling_stride: Frame-rate downsample for Metrica (5 = 5 Hz).
    """

    def __init__(
        self,
        source: str = "synthetic",
        data_root: str | None = None,
        batch_size: int = 32,
        num_workers: int = 0,
        n_synthetic_train: int = 1024,
        n_synthetic_val: int = 256,
        metrica_k_seconds: float = 10.0,
        metrica_sampling_stride: int = 5,
        metrica_label_mode: str = "thirds",
    ) -> None:
        super().__init__()
        self.source = source
        self.data_root = Path(data_root) if data_root else None
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.n_synthetic_train = n_synthetic_train
        self.n_synthetic_val = n_synthetic_val
        self.metrica_k_seconds = metrica_k_seconds
        self.metrica_sampling_stride = metrica_sampling_stride
        self.metrica_label_mode = metrica_label_mode
        self.train_ds: Dataset | None = None
        self.val_ds: Dataset | None = None

    def setup(self, stage: str | None = None) -> None:
        if self.source == "synthetic":
            self.train_ds = SyntheticFrameDataset(
                n_samples=self.n_synthetic_train, seed=0
            )
            self.val_ds = SyntheticFrameDataset(
                n_samples=self.n_synthetic_val, seed=1
            )
            return
        if self.source == "metrica":
            # Match-level split: match 1 → train, match 2 → val.
            effective_fr_hz = 25.0 / self.metrica_sampling_stride
            self.train_ds = MetricaFrameDataset(
                match_ids=("1",),
                k_seconds=self.metrica_k_seconds,
                frame_rate_hz=effective_fr_hz,
                sampling_stride=self.metrica_sampling_stride,
                label_mode=self.metrica_label_mode,
            )
            self.val_ds = MetricaFrameDataset(
                match_ids=("2",),
                k_seconds=self.metrica_k_seconds,
                frame_rate_hz=effective_fr_hz,
                sampling_stride=self.metrica_sampling_stride,
                label_mode=self.metrica_label_mode,
            )
            return
        raise NotImplementedError(
            f"Real-data path for source={self.source!r} requires `load_match` to be "
            f"implemented for that backend. See "
            f"`src/wc2026_tracking_transformer/data/loaders/{self.source}.py`. "
            f"For now, set source='synthetic' or source='metrica'."
        )

    def train_dataloader(self) -> DataLoader:
        assert self.train_ds is not None, "Call setup() first"
        return DataLoader(
            self.train_ds,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.num_workers,
            persistent_workers=self.num_workers > 0,
        )

    def val_dataloader(self) -> DataLoader:
        assert self.val_ds is not None, "Call setup() first"
        return DataLoader(
            self.val_ds,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
            persistent_workers=self.num_workers > 0,
        )
