from typing import Annotated, Optional, Union

from pydantic import Field, TypeAdapter, ValidationError

from src.shared.imagery.planet import PlanetImagery
from src.shared.imagery.sentinel2 import Sentinel2Imagery

Imagery = Annotated[
    Union[PlanetImagery, Sentinel2Imagery], Field(discriminator="provider")
]

_ADAPTER = TypeAdapter(Imagery)


def from_payload(payload: dict) -> Optional[Imagery]:
    try:
        return _ADAPTER.validate_python(payload)
    except ValidationError:
        return None
