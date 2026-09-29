from datetime import date

import pytest
from pydantic import ValidationError

from src.shared.imagery.contract import ImageryBase, LayerPeriod
from src.shared.imagery.planet import MonthlyPeriod


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
        )
