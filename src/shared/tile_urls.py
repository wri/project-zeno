"""Widget tile URLs and the rotating eoapi host.

Map widgets snapshot the tile layer they render into their JSONB config.
An absolute tile URL frozen into the database breaks silently — browser-side
only, with no server-side signal — whenever the eoapi host rotates, and it
already has once (this branch moved the default to the cache host because
the certificates broke). So persisted configs are host-less: on write, a
``tile_url`` on the configured eoapi host is reduced to its ``tile_path``;
on read, the *currently configured* host is prepended again. Host rotation
then becomes a config change instead of an orphaning of every persisted map
widget. URLs on any other host (e.g. the GFW tiles service that serves
imagery mosaics) pass through untouched, so the API contract — responses
always carry an absolute ``tile_url`` — is unchanged.
"""

from typing import Optional

from src.shared.config import SharedSettings

# Widget-config keys whose value is a layer snapshot carrying a tile_url.
_LAYER_KEYS = ("dataset", "imagery")


def _base_url() -> str:
    return SharedSettings.eoapi_base_url.rstrip("/")


def _relativize_layer(layer: dict, base: str) -> dict:
    """A copy of one layer dict with an eoapi tile_url reduced to tile_path."""
    tile_url = layer.get("tile_url")
    if isinstance(tile_url, str) and tile_url.startswith(base + "/"):
        layer = dict(layer)
        layer["tile_path"] = tile_url[len(base) :]
        layer.pop("tile_url")
    return layer


def _absolutize_layer(layer: dict, base: str) -> dict:
    """A copy of one layer dict with tile_path expanded to an absolute
    tile_url, unless it already carries one."""
    tile_path = layer.get("tile_path")
    if isinstance(tile_path, str) and not layer.get("tile_url"):
        layer = dict(layer)
        layer["tile_url"] = base + tile_path
    return layer


def relativize_widget_config(config: Optional[dict]) -> Optional[dict]:
    """A copy of a widget config with eoapi tile URLs reduced to tile_path.

    Layers whose tile_url lives on another host keep it verbatim. A
    multi-layer dataset's sibling layers (config[key]["layers"], e.g. LGMS's
    agriculture/lulucf) are each relativized the same way as the top-level
    tile_url. The input is never mutated (callers pass request bodies and
    agent state).
    """
    if not config:
        return config
    base = _base_url()
    out = dict(config)
    for key in _LAYER_KEYS:
        layer = out.get(key)
        if not isinstance(layer, dict):
            continue
        layer = _relativize_layer(layer, base)
        sub_layers = layer.get("layers")
        if isinstance(sub_layers, list):
            layer = dict(layer)
            layer["layers"] = [
                _relativize_layer(sub, base) if isinstance(sub, dict) else sub
                for sub in sub_layers
            ]
        out[key] = layer
    return out


def absolutize_widget_config(config: Optional[dict]) -> Optional[dict]:
    """A copy of a widget config with tile_path expanded to an absolute
    tile_url on the currently configured eoapi host.

    Configs that already carry a tile_url (foreign-host layers, or rows
    written before tile_path existed) are returned unchanged. A multi-layer
    dataset's sibling layers (config[key]["layers"]) are each absolutized the
    same way as the top-level tile_url.
    """
    if not config:
        return config
    base = _base_url()
    out = dict(config)
    for key in _LAYER_KEYS:
        layer = out.get(key)
        if not isinstance(layer, dict):
            continue
        layer = _absolutize_layer(layer, base)
        sub_layers = layer.get("layers")
        if isinstance(sub_layers, list):
            layer = dict(layer)
            layer["layers"] = [
                _absolutize_layer(sub, base) if isinstance(sub, dict) else sub
                for sub in sub_layers
            ]
        out[key] = layer
    return out
