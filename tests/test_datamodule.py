"""Tests for SoccerTrackingDataModule (synthetic + real-data paths)."""

import pytest
import torch


def test_synthetic_datamodule_constructs_and_yields_batches() -> None:
    from wc2026_tracking_transformer.data import SoccerTrackingDataModule

    dm = SoccerTrackingDataModule(
        source="synthetic",
        batch_size=8,
        n_synthetic_train=32,
        n_synthetic_val=16,
        num_workers=0,
    )
    dm.setup()
    train_loader = dm.train_dataloader()
    val_loader = dm.val_dataloader()

    train_batch = next(iter(train_loader))
    val_batch = next(iter(val_loader))

    for x, y in (train_batch, val_batch):
        assert isinstance(x, torch.Tensor)
        assert isinstance(y, torch.Tensor)
        assert x.dim() == 3  # (B, T, F)
        assert x.shape[1] == 23  # 22 players + ball
        assert x.shape[2] >= 6
        assert y.shape == (x.shape[0], 2)


@pytest.mark.parametrize("source", ["dfl", "skillcorner", "pff"])
def test_real_source_raises_until_loader_implemented(source: str) -> None:
    """Real-data sources should NotImplementedError until their loader exists."""
    from wc2026_tracking_transformer.data import SoccerTrackingDataModule

    dm = SoccerTrackingDataModule(source=source, batch_size=4)
    with pytest.raises(NotImplementedError):
        dm.setup()


def test_synthetic_lightning_fit_smoke(tmp_path) -> None:
    """End-to-end Lightning fit on synthetic data, 1 epoch, 1 batch each."""
    import lightning.pytorch as pl

    from wc2026_tracking_transformer.data import SoccerTrackingDataModule
    from wc2026_tracking_transformer.model import NextEventValueLitModule

    dm = SoccerTrackingDataModule(
        source="synthetic",
        batch_size=8,
        n_synthetic_train=16,
        n_synthetic_val=8,
        num_workers=0,
    )
    lit = NextEventValueLitModule(
        feature_len=7, model_dim=16, num_heads=2, num_layers=1
    )
    trainer = pl.Trainer(
        accelerator="cpu",
        devices=1,
        max_epochs=1,
        limit_train_batches=1,
        limit_val_batches=1,
        enable_progress_bar=False,
        enable_checkpointing=False,
        logger=False,
        default_root_dir=str(tmp_path),
    )
    trainer.fit(lit, datamodule=dm)
