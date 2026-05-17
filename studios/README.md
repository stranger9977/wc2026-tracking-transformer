# Training on Lightning AI Studio

This project is set up to run cleanly on [Lightning AI](https://lightning.ai/)
Studios — managed cloud GPU environments that integrate with PyTorch Lightning.

The same `LightningCLI` entry point (`uv run python -m wc2026_tracking_transformer.train fit`)
works locally on CPU, on a single GPU, and in a multi-GPU Studio. Only the YAML
config changes — see `configs/local_cpu.yaml`, `configs/single_gpu.yaml`, and
`configs/lightning_studio_multi_gpu.yaml`.

## One-time setup

1. **Create an account** at https://lightning.ai
2. **Create a Studio.** Pick a template with CUDA + Python 3.12. The default
   PyTorch template is fine — we'll install our own deps.
3. **Pick the right GPU SKU for your run:**
   - **Smoke test / debug:** A10G x 1 (cheap, plenty for synthetic data)
   - **First real training run on DFL (7 matches):** A10G x 1 or A100 x 1
   - **Long pretraining or multi-source:** A100 x 4 or H100 x 4

## Deploying this repo to a Studio

Inside the Studio terminal:

```bash
# Clone the repo
git clone <your-fork-url> wc2026-tracking-transformer
cd wc2026-tracking-transformer

# Install via uv (uv is preinstalled on Lightning AI templates; if not: pip install uv)
uv sync --extra dev

# Verify the wiring works on synthetic data (no real data needed)
uv run python -m wc2026_tracking_transformer.train fit --config configs/local_cpu.yaml
```

The synthetic-data run should complete in well under a minute on any GPU. If
it does, the Studio is correctly configured.

## Getting data into the Studio

Lightning AI Studios have a few options for data. Pick the one that matches the
dataset size:

- **DFL Bassek 2025** (~tens of GB): use Lightning's S3 bucket connector or
  `lightning rsync` from a local machine. Place under `data/raw/dfl_bassek/`.
- **SkillCorner Open Data** (~hundreds of MB): just `git clone` the repo into
  `data/raw/skillcorner_aleague/` directly inside the Studio.
- **Metrica sample** (~tens of MB): same as SkillCorner — clone directly.

The expected directory layouts are documented in `data/README.md`.

## Launching multi-GPU training

Once data is in place and the loader for that source is implemented:

```bash
# Single-GPU run
uv run python -m wc2026_tracking_transformer.train fit \
    --config configs/single_gpu.yaml

# Multi-GPU DDP run (adjust trainer.devices to match your Studio SKU)
uv run python -m wc2026_tracking_transformer.train fit \
    --config configs/lightning_studio_multi_gpu.yaml
```

## Monitoring

Lightning AI Studios have built-in TensorBoard integration. After kicking off a
run with `enable_checkpointing: true` and the default logger, you can open
TensorBoard from the Studio sidebar.

For multi-node / multi-GPU runs, the Lightning Trainer logs are aggregated by
the DDP root process; you only need one TensorBoard instance.

## Cost notes

- A10G x 1: cheap-ish, fine for development.
- A100 x 4: substantially more expensive — use only for real training runs.
- **Auto-stop your Studios** when not in use. Lightning AI bills per minute of
  GPU time.

## Useful links

- Lightning AI Studios: https://lightning.ai/studios
- Lightning AI pricing: https://lightning.ai/pricing
- PyTorch Lightning docs (CLI / Trainer): https://lightning.ai/docs/pytorch/stable/
- LightningCLI reference: https://lightning.ai/docs/pytorch/stable/cli/lightning_cli.html
