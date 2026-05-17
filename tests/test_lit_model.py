"""Smoke tests for the LightningModule + backbone wiring.

Forward-pass on synthetic data, verify shapes. Confirms the transformer +
head + Lightning pipeline are correctly stitched together.
"""

import torch


def test_backbone_forward_shape() -> None:
    from wc2026_tracking_transformer.model import SoccerTrackingTransformer

    model = SoccerTrackingTransformer(
        feature_len=7, model_dim=32, num_heads=2, num_layers=2
    )
    x = torch.randn(4, 23, 7)
    out = model(x)
    assert out.shape == (4, 23, 32)


def test_backbone_attention_extraction() -> None:
    from wc2026_tracking_transformer.model import SoccerTrackingTransformer

    # Eval mode so attention-dropout doesn't perturb the row sums.
    model = SoccerTrackingTransformer(
        feature_len=7, model_dim=32, num_heads=2, num_layers=3
    ).eval()
    x = torch.randn(2, 23, 7)
    with torch.no_grad():
        encoded, attn = model.encode_with_attention(x)
    assert encoded.shape == (2, 23, 32)
    # (B, num_layers, num_heads, T, T)
    assert attn.shape == (2, 3, 2, 23, 23)
    # In eval mode, attention rows sum to 1.
    row_sums = attn.sum(dim=-1)
    assert torch.allclose(row_sums, torch.ones_like(row_sums), atol=1e-4)


def test_pair_attention_head_reduction() -> None:
    from wc2026_tracking_transformer.tasks import PairAttentionHead

    head = PairAttentionHead(reduce_layers="mean", reduce_heads="mean", symmetrize=True)
    attn = torch.softmax(torch.randn(2, 3, 4, 23, 23), dim=-1)
    pair = head(attn)
    assert pair.shape == (2, 23, 23)
    # symmetrized
    assert torch.allclose(pair, pair.transpose(-1, -2), atol=1e-6)


def test_lit_module_forward_loss_and_step() -> None:
    from wc2026_tracking_transformer.model import NextEventValueLitModule

    lit = NextEventValueLitModule(
        feature_len=7, model_dim=32, num_heads=2, num_layers=1
    )
    x = torch.randn(4, 23, 7)
    y = torch.randint(0, 2, (4, 2)).float()
    logits = lit(x)
    assert logits.shape == (4, 2)

    # _shared_step shouldn't error and should return a scalar loss
    loss = lit._shared_step((x, y), stage="val")
    assert loss.ndim == 0
    assert torch.isfinite(loss)
