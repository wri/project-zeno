from pydantic import TypeAdapter

from src.shared.imagery.planet import PlanetImagery
from src.shared.imagery.sentinel2 import Sentinel2Imagery
from src.shared.imagery.wire import Imagery
from tests.unit.agent.imagery.factories import sentinel2_imagery

PLANET_PAYLOAD = {
    "provider": "planet",
    "period": {"start": "2026-08-01", "end": "2026-08-31"},
    "layer_id": "planet-layer-id",
    "tile_url": "https://tiles.example/{z}/{x}/{y}.png",
    "bounds": [-56.0, -8.0, -54.0, -6.0],
    "min_zoom": 10,
    "max_zoom": 18,
    "source": {
        "tiles": ["https://tiles.example/{z}/{x}/{y}.png"],
        "bounds": [-56.0, -8.0, -54.0, -6.0],
        "minzoom": 10,
        "maxzoom": 18,
    },
    "aoi_names": ["Novo Progresso"],
}


def test_wire_contract_reads_a_planet_payload_as_planet_imagery():
    imagery = TypeAdapter(Imagery).validate_python(PLANET_PAYLOAD)

    assert isinstance(imagery, PlanetImagery)


def test_wire_contract_reads_a_sentinel2_payload_as_sentinel2_imagery():
    payload = sentinel2_imagery().model_dump(mode="json")

    imagery = TypeAdapter(Imagery).validate_python(payload)

    assert isinstance(imagery, Sentinel2Imagery)
