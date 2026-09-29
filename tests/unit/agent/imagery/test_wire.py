from pydantic import TypeAdapter

from src.shared.imagery.planet import PlanetImagery
from src.shared.imagery.wire import Imagery

PLANET_PAYLOAD = {
    "provider": "planet",
    "period": {"start": "2026-08-01", "end": "2026-08-31"},
    "tile_url": "https://tiles.example/{z}/{x}/{y}.png",
    "bounds": [-56.0, -8.0, -54.0, -6.0],
    "min_zoom": 10,
    "max_zoom": 18,
    "aoi_names": ["Novo Progresso"],
}


def test_wire_contract_reads_a_planet_payload_as_planet_imagery():
    imagery = TypeAdapter(Imagery).validate_python(PLANET_PAYLOAD)

    assert isinstance(imagery, PlanetImagery)
