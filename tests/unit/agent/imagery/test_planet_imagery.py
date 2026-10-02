import pytest
from pydantic import ValidationError

from src.shared.imagery.contract import RasterSource
from src.shared.imagery.planet import MonthlyPeriod
from tests.unit.agent.imagery.factories import planet_imagery


def test_planet_imagery_identifies_its_provider_as_planet():
    assert planet_imagery().provider == "planet"


def test_planet_imagery_keeps_the_monthly_period_it_was_built_with():
    period = MonthlyPeriod.from_month("2025-12")

    assert planet_imagery(period=period).period == period


def test_planet_imagery_keeps_the_tile_source_it_renders_from():
    imagery = planet_imagery(tile_url="https://planet.example/{z}/{x}/{y}.png")

    assert imagery.tile_url == "https://planet.example/{z}/{x}/{y}.png"


def test_planet_imagery_names_the_areas_it_covers():
    imagery = planet_imagery(aoi_names=["Novo Progresso", "Altamira"])

    assert imagery.aoi_names == ["Novo Progresso", "Altamira"]


def test_planet_imagery_keeps_the_layer_id_it_was_built_with():
    assert planet_imagery(layer_id="planet-layer").layer_id == "planet-layer"


def test_planet_imagery_rejects_fields_it_does_not_define():
    with pytest.raises(
        ValidationError, match="Extra inputs are not permitted"
    ):
        planet_imagery(mosaic_id="planet:2026-08")


def test_planet_imagery_keeps_the_raster_source_it_was_built_with():
    source = RasterSource(
        tiles=["https://tiles.example/planet/{z}/{x}/{y}.png"],
        bounds=(-55.6, -9.6, -51.6, -3.0),
        minzoom=11,
        maxzoom=17,
    )

    assert planet_imagery(source=source).source == source


def test_planet_imagery_leaves_bounds_and_zooms_to_its_raster_source():
    flat = {"bounds", "min_zoom", "max_zoom"}

    assert flat & set(planet_imagery().model_dump()) == set()
