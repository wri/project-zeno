from datetime import date

import pytest
from pydantic import ValidationError

from src.shared.imagery.contract import ImageryBase, LayerPeriod, RasterSource
from src.shared.imagery.planet import MonthlyPeriod


def raster_source(**overrides) -> RasterSource:
    defaults = {
        "tiles": ["https://tiles.example/{z}/{x}/{y}.png"],
        "bounds": (-56.0, -8.0, -54.0, -6.0),
        "minzoom": 8,
        "maxzoom": 14,
    }
    return RasterSource(**{**defaults, **overrides})


def test_a_bare_layer_period_cannot_be_built():
    with pytest.raises(TypeError, match="LayerPeriod"):
        LayerPeriod(start=date(2026, 8, 1), end=date(2026, 8, 31))


def test_a_layer_period_labels_itself_from_start_to_end():
    assert (
        MonthlyPeriod.from_month("2026-08").label()
        == "2026-08-01 → 2026-08-31"
    )


def test_a_layer_period_rejects_fields_it_does_not_define():
    with pytest.raises(
        ValidationError, match="Extra inputs are not permitted"
    ):
        MonthlyPeriod(
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
            date_start="2026-08-01",
        )


def test_a_bare_imagery_base_cannot_be_built():
    with pytest.raises(TypeError, match="ImageryBase"):
        ImageryBase(
            provider="planet",
            period=MonthlyPeriod.from_month("2026-08"),
            tile_url="https://tiles.example/{z}/{x}/{y}.png",
            aoi_names=["Novo Progresso"],
            layer_id="planet-layer-id",
            source=raster_source(),
        )


def test_a_raster_source_keeps_the_tiles_bounds_and_zooms_it_was_built_with():
    source = raster_source(
        tiles=["https://tiles.example/source/{z}/{x}/{y}.png"],
        bounds=(-55.6, -9.6, -51.6, -3.0),
        minzoom=9,
        maxzoom=15,
    )

    assert source.tiles == ["https://tiles.example/source/{z}/{x}/{y}.png"]
    assert source.bounds == (-55.6, -9.6, -51.6, -3.0)
    assert (source.minzoom, source.maxzoom) == (9, 15)


def test_a_raster_source_rejects_fields_it_does_not_define():
    with pytest.raises(
        ValidationError, match="Extra inputs are not permitted"
    ):
        raster_source(scheme="tms")
