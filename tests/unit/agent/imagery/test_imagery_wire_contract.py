import json
from datetime import date

from langchain_core.load import dumps
from pydantic import TypeAdapter

from src.agent.imagery import ImageryRequest, PlanetImageryProvider
from src.agent.tools.show_imagery import provider_command
from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery
from src.shared.imagery.wire import Imagery

AMAZON_AOI = {
    "name": "Novo Progresso",
    "source": "gadm",
    "src_id": "BRA.14.83_2",
    "bbox": [-56.0, -8.0, -54.0, -6.0],
}


def as_streamed(update: dict) -> dict:
    return json.loads(dumps(update))


async def test_planet_imagery_streamed_to_the_client_satisfies_the_wire_contract():
    request = ImageryRequest(
        aois=[AMAZON_AOI], target_date=date(2026, 8, 15), language="en"
    )
    result = await PlanetImageryProvider().get_imagery(request)

    streamed = as_streamed(provider_command(result, "call-1").update)
    imagery = TypeAdapter(Imagery).validate_python(streamed["imagery"])

    assert isinstance(imagery, PlanetImagery)
    assert imagery.period == MonthlyPeriod.from_month("2026-08")
