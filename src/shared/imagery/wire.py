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


def json_schema() -> dict:
    schema = _ADAPTER.json_schema(mode="serialization")
    _make_tolerant(schema)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "imagery.schema.json",
        "title": "Imagery",
        **schema,
    }


def _make_tolerant(node: object) -> None:
    if isinstance(node, dict):
        node.pop("additionalProperties", None)
        for field in node.get("properties", {}).values():
            field.pop("title", None)
        for value in node.values():
            _make_tolerant(value)
    elif isinstance(node, list):
        for value in node:
            _make_tolerant(value)
