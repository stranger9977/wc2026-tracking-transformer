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
        NUM_TOKENS_PER_FRAME,
        SoccerTrackingDataModule,
        TrackingFrame,
        list_matches,
        load_dfl_match,
        load_match,
        load_metrica_match,
        load_pff_match,
        load_skillcorner_match,
    )

    assert NUM_PLAYERS_PER_FRAME == 22
    assert NUM_TOKENS_PER_FRAME == 23
    assert len(FRAME_FEATURE_COLUMNS) >= 6, "expect at least the Sumer-spec 6 features"
    assert callable(load_match)
    assert callable(list_matches)
    for fn in (load_dfl_match, load_skillcorner_match, load_metrica_match, load_pff_match):
        assert callable(fn)
    assert TrackingFrame.__name__ == "TrackingFrame"
    assert SoccerTrackingDataModule.__name__ == "SoccerTrackingDataModule"


def test_model_module_surface() -> None:
    from wc2026_tracking_transformer.model import (
        NextEventValueLitModule,
        SoccerTrackingTransformer,
    )

    model = SoccerTrackingTransformer(feature_len=7, model_dim=32, num_heads=2, num_layers=1)
    assert model.model_dim == 32
    assert model.num_layers == 1

    lit = NextEventValueLitModule(feature_len=7, model_dim=32, num_heads=2, num_layers=1)
    assert lit.hparams.model_dim == 32


def test_tasks_module_surface() -> None:
    from wc2026_tracking_transformer.tasks import NextEventValueHead, PairAttentionHead

    head = NextEventValueHead(model_dim=32)
    assert head.model_dim == 32

    pair = PairAttentionHead(symmetrize=True)
    assert pair.symmetrize is True


def test_tracking_loader_dispatch_validates_source() -> None:
    """The unified dispatcher rejects unknown source names."""
    import pytest

    from wc2026_tracking_transformer.data import list_matches, load_match

    with pytest.raises(ValueError, match="Unknown source"):
        load_match("nfl", "/nonexistent")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unknown source"):
        list_matches("nfl")  # type: ignore[arg-type]
