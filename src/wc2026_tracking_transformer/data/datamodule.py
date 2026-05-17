"""Lightning DataModule for soccer tracking.

Two paths:

  * ``source="synthetic"`` — random tensors of the right shape. Lets the
    full training pipeline (Trainer / DDP / mixed precision / logging) be
    smoke-tested on CPU before any real data is downloaded.
  * ``source="dfl"`` (or other backend) — real data via the per-source
    loaders. NotImplementedError until ``load_match`` is implemented for
    that backend.

The split is **match-level**: frames from one match never cross train/val/test.
This is more conservative than Sumer's play-level split for NFL — possessions
in soccer aren't independent units, so cross-possession leakage is real.
"""

from __future__ import annotations

from pathlib import Path

import lightning.pytorch as pl
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from wc2026_tracking_transformer.data.schema import (
    FRAME_FEATURE_COLUMNS,
    NUM_TOKENS_PER_FRAME,
)


class SyntheticFrameDataset(Dataset):
    """Random (frame, label) pairs of the right shapes.

    Useful only for wiring tests — replace with a real ``Dataset`` once
    ``load_match`` is implemented.
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
        # Two-head label: independent Bernoulli for P(score) / P(concede).
        self.labels = (rng.random((n_samples, 2)) < 0.05).astype(np.float32)

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        return (
            torch.from_numpy(self.frames[idx]),
            torch.from_numpy(self.labels[idx]),
        )


class SoccerTrackingDataModule(pl.LightningDataModule):
    """Datamodule with synthetic + real-data paths.

    Args:
        source: ``"synthetic"`` (default) for wiring tests, or one of the
            real backends (``"dfl"``, ``"skillcorner"``, ``"metrica"``,
            ``"pff"``) once that loader is implemented.
        data_root: Override the default raw-data directory for the source.
        batch_size: Batch size for all loaders.
        num_workers: DataLoader workers.
        n_synthetic_train / n_synthetic_val: sample counts for synthetic mode.
    """

    def __init__(
        self,
        source: str = "synthetic",
        data_root: str | None = None,
        batch_size: int = 32,
        num_workers: int = 0,
        n_synthetic_train: int = 1024,
        n_synthetic_val: int = 256,
    ) -> None:
        super().__init__()
        self.source = source
        self.data_root = Path(data_root) if data_root else None
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.n_synthetic_train = n_synthetic_train
        self.n_synthetic_val = n_synthetic_val
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
        raise NotImplementedError(
            f"Real-data path for source={self.source!r} requires `load_match` to be "
            f"implemented for that backend. See "
            f"`src/wc2026_tracking_transformer/data/loaders/{self.source}.py`. "
            f"For now, set source='synthetic' to sanity-check the training pipeline."
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
