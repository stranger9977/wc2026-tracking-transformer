"""Top-level training entry point.

Eventually this owns the same surface area as Sumer's ``src/train.py``:
hyperparameter sweep config, LightningModule wiring, checkpoint resumption,
prediction dump. For now it's a scaffold.

Run (once implemented):
    uv run python -m wc2026_tracking_transformer.train --task next_event_value

NOTE: Implementation is a SKELETON.
"""

from argparse import ArgumentParser, Namespace


def main(args: Namespace) -> None:
    """Train a soccer tracking transformer.

    TODO list:
        1. Resolve ``args.task`` to a head class from
           :mod:`wc2026_tracking_transformer.tasks`.
        2. Build :class:`SoccerTrackingTransformer` backbone +
           task head wrapped in a ``LightningModule``.
        3. Load processed parquet from ``data/processed/`` via the dataset
           class (TBD — soccer version of Sumer's ``BDB2024_Dataset``).
        4. Wire ``Trainer`` with TensorBoard logging, ``EarlyStopping``,
           ``ModelCheckpoint`` (mirror Sumer's ``train.py::train_model``).
        5. ``trainer.fit(...)``, then dump predictions to parquet.

    Args:
        args: Parsed CLI args.

    Raises:
        NotImplementedError: scaffolding only.
    """
    raise NotImplementedError(
        "train.main is a scaffold. See module docstring for the implementation plan."
    )


def _build_argparser() -> ArgumentParser:
    parser = ArgumentParser(description="Train a soccer tracking transformer.")
    parser.add_argument(
        "--task",
        type=str,
        default="next_event_value",
        choices=["next_event_value", "pair_attention"],
        help="Which task head to train. 'pair_attention' is analysis-only and "
             "expects a backbone trained on another task.",
    )
    parser.add_argument("--model-dim", type=int, default=128)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--max-epochs", type=int, default=200)
    parser.add_argument("--device", type=int, default=-1, help="GPU index, -1 for CPU.")
    return parser


if __name__ == "__main__":
    main(_build_argparser().parse_args())
