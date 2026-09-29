import pytest
from pydantic import ValidationError

from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery


def test_planet_imagery_identifies_its_provider_as_planet():
    imagery = PlanetImagery(period=MonthlyPeriod.from_month("2026-08"))

    assert imagery.provider == "planet"


def test_planet_imagery_keeps_the_monthly_period_it_was_built_with():
    period = MonthlyPeriod.from_month("2026-08")

    assert PlanetImagery(period=period).period == period


def test_planet_imagery_rejects_fields_it_does_not_define():
    with pytest.raises(
        ValidationError, match="Extra inputs are not permitted"
    ):
        PlanetImagery(
            period=MonthlyPeriod.from_month("2026-08"),
            mosaic_id="planet:2026-08",
        )
