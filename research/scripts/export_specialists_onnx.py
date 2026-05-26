"""Export the score-only / concede-only specialist checkpoints to ONNX.

Mirrors the recipe used for ``frame_vaep.onnx`` (the shared two-head model):
    input  : ``x`` of shape (batch, 23, 7), float32
    output : ``p_score`` (score specialist) **or** ``p_concede`` (concede
             specialist), shape (batch,), sigmoid-activated

Each specialist exposes exactly ONE BCE head — the Whiteboard JS layer is
expected to fall back to the baseline value for the missing head.

Usage:
    PYTHONPATH=src uv run python research/scripts/export_specialists_onnx.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch
from torch import Tensor, nn

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from wc2026_tracking_transformer.model.frame_vaep_specialist import (  # noqa: E402
    FrameVaepSpecialistLitModule,
)


class _SpecialistWrapper(nn.Module):
    """Wrapper that runs backbone → head → sigmoid, named for ONNX export."""

    def __init__(self, lit: FrameVaepSpecialistLitModule) -> None:
        super().__init__()
        self.backbone = lit.backbone
        self.task_head = lit.task_head

    def forward(self, x: Tensor) -> Tensor:
        enc = self.backbone(x)
        return torch.sigmoid(self.task_head(enc))


def export_specialist(ckpt_path: Path, out_path: Path, output_name: str) -> None:
    print(f"[{output_name}] loading {ckpt_path.name} …")
    lit = FrameVaepSpecialistLitModule.load_from_checkpoint(
        ckpt_path, map_location="cpu"
    ).eval()
    wrapper = _SpecialistWrapper(lit).eval()

    dummy = torch.zeros((1, 23, 7), dtype=torch.float32)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper,
        (dummy,),
        str(out_path),
        input_names=["x"],
        output_names=[output_name],
        dynamic_axes={"x": {0: "batch"}, output_name: {0: "batch"}},
        opset_version=17,
        do_constant_folding=True,
    )
    print(f"  wrote {out_path}  ({out_path.stat().st_size/1024:.1f} KiB)")

    # Parity check against PyTorch.
    import onnxruntime as ort

    sess = ort.InferenceSession(str(out_path), providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(0)
    x_np = rng.standard_normal((4, 23, 7)).astype(np.float32)
    with torch.no_grad():
        y_torch = wrapper(torch.from_numpy(x_np)).numpy()
    y_onnx = sess.run([output_name], {"x": x_np})[0]
    max_diff = float(np.max(np.abs(y_torch - y_onnx)))
    print(f"  parity max|Δ| = {max_diff:.2e}; sample {output_name}: {y_onnx.tolist()}")


def main() -> None:
    out_dir = REPO / "research" / "site" / "assets" / "models"
    export_specialist(
        REPO / "output" / "transformer_score_only.ckpt",
        out_dir / "frame_vaep_score.onnx",
        output_name="p_score",
    )
    export_specialist(
        REPO / "output" / "transformer_concede_only.ckpt",
        out_dir / "frame_vaep_concede.onnx",
        output_name="p_concede",
    )


if __name__ == "__main__":
    main()
