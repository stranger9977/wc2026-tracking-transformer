"""LightningModule for xT regression (single-head, MSE).

Predicts ``max(xT) in the next K seconds`` per frame from the 22-player +
ball tokens.  This replaces the original two-head binary classification
when the supervised target is dense and continuous.

Loss: HuberLoss (smooth-L1) — robust to outliers near the goal cells where
xT spikes from ~0.05 to ~0.30 in one cell hop.

Reported metrics:
    * ``val_mae`` — mean absolute error in xT units.
    * ``val_spearman_ours`` — Spearman ρ between our predictions and labels.
    * ``val_spearman_lookup`` — Spearman ρ for the xT-lookup baseline.
    * ``val_lift_vs_lookup`` — ``val_spearman_ours - val_spearman_lookup``.
      Positive ⇒ we beat the static baseline; that's the off-ball signal.
"""

from __future__ import annotations

import lightning.pytorch as pl
import torch
import torch.nn.functional as F
from torch import Tensor, nn

from wc2026_tracking_transformer.model.transformer import SoccerTrackingTransformer


class XTRegressionHead(nn.Module):
    """Pool encoder outputs and predict a single xT scalar."""

    def __init__(self, model_dim: int, hidden: int = 128, dropout: float = 0.1) -> None:
        super().__init__()
        self.head = nn.Sequential(
            nn.Linear(model_dim, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, 1),
        )

    def forward(self, encoded: Tensor) -> Tensor:
        pooled = encoded.mean(dim=1)
        return self.head(pooled).squeeze(-1)


class XTRegressionLitModule(pl.LightningModule):
    """Single-head xT-regression model.

    Batch format: ``(x, y, baseline)`` triples where ``x`` is the frame
    tensor ``(B, 23, 7)``, ``y`` is the regression target ``(B,)`` =
    max-xT-in-next-K-seconds, and ``baseline`` is the xT-lookup value for
    each frame ``(B,)`` — used to report the lift metric.
    """

    def __init__(
        self,
        feature_len: int = 7,
        model_dim: int = 128,
        num_heads: int = 4,
        num_layers: int = 2,
        dropout: float = 0.1,
        head_hidden: int = 128,
        learning_rate: float = 3e-4,
        weight_decay: float = 1e-5,
    ) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.backbone = SoccerTrackingTransformer(
            feature_len=feature_len, model_dim=model_dim,
            num_heads=num_heads, num_layers=num_layers, dropout=dropout,
        )
        self.head = XTRegressionHead(model_dim=model_dim, hidden=head_hidden, dropout=dropout)
        # Buffers for Spearman computation over a whole validation epoch.
        self._val_preds: list[Tensor] = []
        self._val_targets: list[Tensor] = []
        self._val_baselines: list[Tensor] = []

    def forward(self, x: Tensor) -> Tensor:
        return self.head(self.backbone(x))

    def _unpack(self, batch):
        # Support both (x, y) and (x, y, baseline) batches.
        if len(batch) == 3:
            x, y, baseline = batch
        else:
            x, y = batch
            baseline = torch.zeros_like(y)
        return x, y.float(), baseline.float()

    def training_step(self, batch, batch_idx):  # type: ignore[override]
        x, y, _ = self._unpack(batch)
        y_hat = self(x)
        loss = F.huber_loss(y_hat, y, delta=0.05)
        with torch.no_grad():
            mae = F.l1_loss(y_hat, y)
        self.log("train_loss", loss, on_step=False, on_epoch=True, prog_bar=True, sync_dist=True)
        self.log("train_mae", mae, on_step=False, on_epoch=True, prog_bar=True, sync_dist=True)
        return loss

    def validation_step(self, batch, batch_idx):  # type: ignore[override]
        x, y, baseline = self._unpack(batch)
        y_hat = self(x)
        loss = F.huber_loss(y_hat, y, delta=0.05)
        mae = F.l1_loss(y_hat, y)
        self.log("val_loss", loss, on_step=False, on_epoch=True, prog_bar=True, sync_dist=True)
        self.log("val_mae", mae, on_step=False, on_epoch=True, prog_bar=True, sync_dist=True)
        self._val_preds.append(y_hat.detach().cpu())
        self._val_targets.append(y.detach().cpu())
        self._val_baselines.append(baseline.detach().cpu())
        return loss

    def on_validation_epoch_end(self) -> None:  # type: ignore[override]
        if not self._val_preds:
            return
        preds = torch.cat(self._val_preds).numpy()
        targets = torch.cat(self._val_targets).numpy()
        baselines = torch.cat(self._val_baselines).numpy()
        self._val_preds.clear(); self._val_targets.clear(); self._val_baselines.clear()

        rho_ours = _spearman(preds, targets)
        rho_base = _spearman(baselines, targets) if (baselines != 0).any() else 0.0
        lift = rho_ours - rho_base
        self.log("val_spearman_ours", rho_ours, prog_bar=True, sync_dist=False)
        self.log("val_spearman_lookup", rho_base, prog_bar=False, sync_dist=False)
        self.log("val_lift_vs_lookup", lift, prog_bar=True, sync_dist=False)

    def configure_optimizers(self):  # type: ignore[override]
        return torch.optim.AdamW(
            self.parameters(),
            lr=self.hparams.learning_rate,
            weight_decay=self.hparams.weight_decay,
        )


def _spearman(a, b) -> float:
    """Spearman rank correlation, scipy-free."""
    import numpy as np
    if len(a) < 2: return 0.0
    ra = np.argsort(np.argsort(a))
    rb = np.argsort(np.argsort(b))
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0: return 0.0
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb))
