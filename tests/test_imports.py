"""Smoke test: the package imports and surfaces its public API.

Runs without any data. If this passes, the scaffold is wired correctly.
"""


def test_package_imports() -> None:
    import wc2026_tracking_transformer as wtt

    assert wtt.__version__ == "0.0.1"


def test_data_module_surface() -> None:
    from wc2026_tracking_transformer.data import (
        FRAME_FEATURE_COLUMNS,
        NUM_PLAYERS_PER_FRAME,
        TrackingFrame,
        load_pff_match,
    )

    assert NUM_PLAYERS_PER_FRAME == 22
    assert len(FRAME_FEATURE_COLUMNS) >= 6, "expect at least the Sumer-spec 6 features"
    assert callable(load_pff_match)
    assert TrackingFrame.__name__ == "TrackingFrame"


def test_model_module_surface() -> None:
    from wc2026_tracking_transformer.model import SoccerTrackingTransformer

    model = SoccerTrackingTransformer(feature_len=7, model_dim=32, num_layers=1)
    assert model.model_dim == 32
    assert model.num_layers == 1


def test_tasks_module_surface() -> None:
    from wc2026_tracking_transformer.tasks import NextEventValueHead, PairAttentionHead

    head = NextEventValueHead(model_dim=32)
    assert head.model_dim == 32

    pair = PairAttentionHead(symmetrize=True)
    assert pair.symmetrize is True
