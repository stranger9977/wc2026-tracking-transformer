"""Frame-level VAEP LightningModule: two BCE heads on the shared backbone.

Lifts the event-level VAEP framework (Decroos 2019) to the frame level:
    P_score(s_t)   = P(team in possession at frame t scores within K s)
    P_concede(s_t) = P(team in possession at frame t concedes within K s)

Frame-level VAEP at time t is `(P_score(s_t) − P_score(s_{t-Δ})) −
(P_concede(s_t) − P_concede(s_{t-Δ}))` — a continuous, dense, off-ball-aware
generalization of action-level VAEP that doesn't wait for a SPADL event to
re-evaluate the state.
"""
from __future__ import annotations

import lightning.pytorch as pl
import torch
import torch.nn.functional as F
from torch import Tensor, nn

from wc2026_tracking_transformer.model.transformer import SoccerTrackingTransformer


class FrameVaepHead(nn.Module):
    """Mean-pool encoder outputs then project to a single logit."""

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


class FrameVaepLitModule(pl.LightningModule):
    """Two-head frame VAEP: BCE on (p_score, p_concede).

    Batch format: ``(x, y_score, y_concede)``.

    Loss combines both heads with class weighting because goals are rare
    (~165 goals in 64 matches → ~0.5% positive rate at 10 s look-ahead).
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
        pos_weight_score: float = 80.0,
        pos_weight_concede: float = 80.0,
    ) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.backbone = SoccerTrackingTransformer(
            feature_len=feature_len, model_dim=model_dim,
            num_heads=num_heads, num_layers=num_layers, dropout=dropout,
        )
        self.score_head = FrameVaepHead(model_dim=model_dim, hidden=head_hidden, dropout=dropout)
        self.concede_head = FrameVaepHead(model_dim=model_dim, hidden=head_hidden, dropout=dropout)
        self.register_buffer("pw_score", torch.tensor(pos_weight_score, dtype=torch.float32))
        self.register_buffer("pw_concede", torch.tensor(pos_weight_concede, dtype=torch.float32))
        # Buffers for epoch-end AUC
        self._val_score_preds: list[Tensor] = []
        self._val_score_y: list[Tensor] = []
        self._val_concede_preds: list[Tensor] = []
        self._val_concede_y: list[Tensor] = []

    def forward(self, x: Tensor) -> tuple[Tensor, Tensor]:
        enc = self.backbone(x)
        return torch.sigmoid(self.score_head(enc)), torch.sigmoid(self.concede_head(enc))

    def encode_with_attention(self, x: Tensor):
        """Pass-through for callers that want (encoded, attn)."""
        return self.backbone.encode_with_attention(x)

    def _step(self, batch, *, train: bool):
        x, y_score, y_concede = batch
        enc = self.backbone(x)
        score_logit = self.score_head(enc)
        concede_logit = self.concede_head(enc)
        loss_s = F.binary_cross_entropy_with_logits(
            score_logit, y_score.float(), pos_weight=self.pw_score)
        loss_c = F.binary_cross_entropy_with_logits(
            concede_logit, y_concede.float(), pos_weight=self.pw_concede)
        loss = 0.5 * (loss_s + loss_c)
        prefix = "train" if train else "val"
        self.log(f"{prefix}_loss", loss, on_step=False, on_epoch=True, prog_bar=True, sync_dist=True)
        self.log(f"{prefix}_loss_score", loss_s, on_step=False, on_epoch=True, sync_dist=True)
        self.log(f"{prefix}_loss_concede", loss_c, on_step=False, on_epoch=True, sync_dist=True)
        if not train:
            with torch.no_grad():
                ps = torch.sigmoid(score_logit).detach().cpu()
                pc = torch.sigmoid(concede_logit).detach().cpu()
            self._val_score_preds.append(ps)
            self._val_score_y.append(y_score.detach().cpu().float())
            self._val_concede_preds.append(pc)
            self._val_concede_y.append(y_concede.detach().cpu().float())
        return loss

    def training_step(self, batch, batch_idx):  # type: ignore[override]
        return self._step(batch, train=True)

    def validation_step(self, batch, batch_idx):  # type: ignore[override]
        return self._step(batch, train=False)

    def on_validation_epoch_end(self) -> None:  # type: ignore[override]
        if not self._val_score_preds:
            return
        import numpy as np
        from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

        ps = torch.cat(self._val_score_preds).numpy()
        ys = torch.cat(self._val_score_y).numpy()
        pc = torch.cat(self._val_concede_preds).numpy()
        yc = torch.cat(self._val_concede_y).numpy()
        self._val_score_preds.clear(); self._val_score_y.clear()
        self._val_concede_preds.clear(); self._val_concede_y.clear()

        for name, y, p in [("score", ys, ps), ("concede", yc, pc)]:
            if y.sum() > 0 and y.sum() < len(y):
                auc = float(roc_auc_score(y, p))
                ap = float(average_precision_score(y, p))
            else:
                auc = float("nan"); ap = float("nan")
            brier = float(brier_score_loss(y, np.clip(p, 0, 1)))
            self.log(f"val_auc_{name}", auc, prog_bar=True, sync_dist=False)
            self.log(f"val_ap_{name}", ap, prog_bar=False, sync_dist=False)
            self.log(f"val_brier_{name}", brier, prog_bar=False, sync_dist=False)

    def configure_optimizers(self):  # type: ignore[override]
        return torch.optim.AdamW(
            self.parameters(),
            lr=self.hparams.learning_rate,
            weight_decay=self.hparams.weight_decay,
        )
