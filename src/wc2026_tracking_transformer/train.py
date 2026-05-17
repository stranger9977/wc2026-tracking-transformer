"""Top-level training entry — config-driven via LightningCLI.

The same entry point works on local CPU, a single GPU, and a Lightning AI
Studio with multiple GPUs. Only the config YAML changes.

Examples:

    # Sanity check on CPU with synthetic data
    uv run python -m wc2026_tracking_transformer.train fit \\
        --config configs/local_cpu.yaml

    # Single GPU
    uv run python -m wc2026_tracking_transformer.train fit \\
        --config configs/single_gpu.yaml

    # Lightning AI Studio multi-GPU
    uv run python -m wc2026_tracking_transformer.train fit \\
        --config configs/lightning_studio_multi_gpu.yaml
"""

from __future__ import annotations

from lightning.pytorch.cli import LightningCLI

from wc2026_tracking_transformer.data.datamodule import SoccerTrackingDataModule
from wc2026_tracking_transformer.model.lit_model import NextEventValueLitModule


def cli_main() -> LightningCLI:
    """Build the LightningCLI and let it parse argv / config."""
    return LightningCLI(
        model_class=NextEventValueLitModule,
        datamodule_class=SoccerTrackingDataModule,
        save_config_callback=None,
        # Don't auto-run if imported (e.g., during tests). Let __main__ drive it.
        run=True,
    )


if __name__ == "__main__":
    cli_main()
