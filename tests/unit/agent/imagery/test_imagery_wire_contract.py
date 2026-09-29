from datetime import date

import pytest

from src.agent.imagery import ImageryRequest, PlanetImageryProvider
from src.agent.tools.show_imagery import provider_command

AMAZON_AOI = {
    "name": "Novo Progresso",
    "source": "gadm",
    "src_id": "BRA.14.83_2",
    "bbox": [-56.0, -8.0, -54.0, -6.0],
}


@pytest.mark.xfail(strict=True, reason="Imagery wire contract not built yet")
async def test_planet_imagery_tool_update_satisfies_the_wire_contract_as_planet_imagery():
    from pydantic import TypeAdapter

    from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery
    from src.shared.imagery.wire import Imagery

    request = ImageryRequest(
        aois=[AMAZON_AOI], target_date=date(2026, 8, 15), language="en"
    )
    result = await PlanetImageryProvider().get_imagery(request)

    wire_imagery = provider_command(result, "call-1").update["imagery"]
    imagery = TypeAdapter(Imagery).validate_python(wire_imagery)

    assert isinstance(imagery, PlanetImagery)
    assert imagery.period == MonthlyPeriod.from_month("2026-08")
