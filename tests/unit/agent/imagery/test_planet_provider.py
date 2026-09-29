from datetime import date

from src.agent.imagery import ImageryRequest, PlanetImageryProvider
from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery

NOVO_PROGRESSO = {
    "name": "Novo Progresso",
    "source": "gadm",
    "src_id": "BRA.14.83_2",
    "bbox": [-56.0, -8.0, -54.0, -6.0],
}


async def test_planet_provider_builds_planet_imagery_for_the_requested_month():
    request = ImageryRequest(
        aois=[NOVO_PROGRESSO], target_date=date(2026, 8, 15), language="en"
    )

    result = await PlanetImageryProvider().get_imagery(request)

    assert result.imagery == PlanetImagery(
        period=MonthlyPeriod.from_month("2026-08"),
        tile_url=(
            "https://tiles.globalforestwatch.org/integrated_alerts_planet_imagery"
            "/{z}/{x}/{y}.png?month=2026-08"
        ),
        bounds=(-56.0, -8.0, -54.0, -6.0),
        min_zoom=10,
        max_zoom=18,
        aoi_names=["Novo Progresso"],
    )
