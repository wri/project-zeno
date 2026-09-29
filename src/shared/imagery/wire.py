from typing import Optional

from pydantic import TypeAdapter, ValidationError

from src.shared.imagery.planet import PlanetImagery

Imagery = PlanetImagery

_ADAPTER = TypeAdapter(Imagery)


def from_payload(payload: dict) -> Optional[Imagery]:
    try:
        return _ADAPTER.validate_python(payload)
    except ValidationError:
        return None
