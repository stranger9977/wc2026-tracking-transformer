"""LightningModule for the next-event-value task.

Wraps :class:`SoccerTrackingTransformer` + :class:`NextEventValueHead` with
training/validation steps, optimizer config, and metric logging. The same
module works across configs — local CPU, single GPU, Lightning AI Studio
multi-GPU DDP — only the trainer/data config changes.
"""

from __future__ import annotations

import lightning.pytorch as pl
import torch
import torch.nn.functional as F
from torch import Tensor

from wc2026_tracking_transformer.model.transformer import SoccerTrackingTransformer
from wc2026_tracking_transformer.tasks.next_event_value import NextEventValueHead


class NextEventValueLitModule(pl.LightningModule):
    """Lightning wrapper around backbone + next-event-value head.

    Labels are 2-d binary: ``[is_score_in_window, is_concede_in_window]``.
    Loss is independent BCE per head (the events aren't mutually exclusive).

    Args:
        feature_len: Per-token input feature count.
        model_dim: Transformer embedding dim.
        num_heads: Attention heads per layer.
        num_layers: Stacked encoder layers.
        dropout: Encoder dropout.
        head_pool: ``"mean"`` or ``"ball"``.
        head_hidden: MLP hidden dim inside the head.
        learning_rate: AdamW LR.
        weight_decay: AdamW weight decay.
    """

    def __init__(
        self,
        feature_len: int = 7,
        model_dim: int = 128,
        num_heads: int = 4,
        num_layers: int = 2,
        dropout: float = 0.1,
        head_pool: str = "mean",
        head_hidden: int = 128,
        learning_rate: float = 1e-4,
        weight_decay: float = 1e-5,
    ) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.backbone = SoccerTrackingTransformer(
            feature_len=feature_len,
            model_dim=model_dim,
            num_heads=num_heads,
            num_layers=num_layers,
            dropout=dropout,
        )
        self.head = NextEventValueHead(
            model_dim=model_dim,
            pool=head_pool,
            hidden=head_hidden,
            dropout=dropout,
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.head(self.backbone(x))

    def _shared_step(
        self, batch: tuple[Tensor, Tensor], stage: str
    ) -> Tensor:
        x, y = batch
        logits = self(x)
        loss = F.binary_cross_entropy_with_logits(logits, y.float())
        with torch.no_grad():
            probs = torch.sigmoid(logits)
            acc = ((probs > 0.5).float() == y).float().mean()
        self.log(
            f"{stage}_loss",
            loss,
            on_step=stage == "train",
            on_epoch=True,
            prog_bar=True,
            sync_dist=True,
        )
        self.log(
            f"{stage}_acc",
            acc,
            on_step=False,
            on_epoch=True,
            prog_bar=True,
            sync_dist=True,
        )
        return loss

    def training_step(self, batch, batch_idx):  # type: ignore[override]
        return self._shared_step(batch, "train")

    def validation_step(self, batch, batch_idx):  # type: ignore[override]
        return self._shared_step(batch, "val")

    def configure_optimizers(self):  # type: ignore[override]
        return torch.optim.AdamW(
            self.parameters(),
            lr=self.hparams.learning_rate,
            weight_decay=self.hparams.weight_decay,
        )
