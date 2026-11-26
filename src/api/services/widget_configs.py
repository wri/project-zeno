"""Map widget config projections, shared by the agent and the API.

A map widget config is a snapshot of a resolved layer. The frontend renders
it with no catalog lookup and no chat state. The agent tool
``add_map_widget`` and the analysis templates both write this snapshot, so
the projections are in one module and a layer gives the same config on both
paths.

The snapshot is an explicit key allowlist: only render-relevant fields are
copied, so the prose fields on the dataset state (description, methodology,
instructions, ...) can never leak into the database.
"""

from typing import Optional

# Render-relevant fields of the imagery state (ImageryState) — all of it.
IMAGERY_KEYS = (
    "provider",
    "tile_url",
    "bounds",
    "min_zoom",
    "max_zoom",
    "mosaic_id",
    "start_date",
    "end_date",
    "target_date",
    "window_days",
    "max_cloud_cover",
    "aoi_names",
)


def default_layer(
    layers: Optional[list[dict]], selected_layer: Optional[str]
) -> Optional[dict]:
    """The layer entry to fall back to when `tile_url` is missing: the one
    named by `selected_layer` if it matches, otherwise `layers[0]`. The only
    place this dataset's layers are resolved down to a single tile_url —
    the live agent response never does, so this never disagrees with what
    the agent actually selected by picking a different layer independently."""
    if not layers:
        return None
    if selected_layer:
        match = next(
            (layer for layer in layers if layer.get("name") == selected_layer),
            None,
        )
        if match is not None:
            return match
    return layers[0]


def dataset_config(state: dict) -> Optional[dict]:
    """Project the dataset in state onto the widget-config snapshot.

    Returns None when no dataset is selected and it carries neither a tile
    URL nor `layers` (nothing to render). Dates fall back to the top-level
    effective range set by pull_data. `layers` carries a multi-layer
    dataset's (e.g. LGMS) independently-toggleable siblings through the
    snapshot — the top-level `tile_url` is resolved here from
    `selected_layer` (or `layers[0]`) via `default_layer` when the
    dataset's own `tile_url` field is empty.
    """
    dataset = state.get("dataset") or {}
    layers = dataset.get("layers")
    fallback_layer = default_layer(layers, dataset.get("selected_layer"))
    tile_url = dataset.get("tile_url") or (
        fallback_layer.get("tile_url") if fallback_layer else None
    )
    if not tile_url:
        return None
    parameters = dataset.get("parameters")
    return {
        "dataset_id": dataset.get("dataset_id"),
        "dataset_name": dataset.get("dataset_name"),
        "tile_url": tile_url,
        "context_layer": dataset.get("context_layer"),
        "selected_layer": dataset.get("selected_layer"),
        "context_layers": dataset.get("context_layers"),
        "parameters": [
            {"name": p.get("name"), "values": p.get("values")}
            for p in parameters
        ]
        if parameters
        else None,
        "layers": [
            {
                "name": layer.get("name"),
                "title": layer.get("title"),
                "description": layer.get("description"),
                "tile_url": layer.get("tile_url"),
                "start_date": layer.get("start_date"),
                "end_date": layer.get("end_date"),
            }
            for layer in layers
        ]
        if layers
        else None,
        "start_date": dataset.get("start_date") or state.get("start_date"),
        "end_date": dataset.get("end_date") or state.get("end_date"),
    }


def is_renderable_imagery(imagery: object) -> bool:
    """Whether an imagery snapshot has what the frontend renders from.

    Planet (and Sentinel-2 imagery saved before browser rendering) renders
    from its tile_url. Sentinel-2 has no tile_url: the browser searches and
    draws the scenes from the recipe token in ``mosaic_id``.
    """
    if not isinstance(imagery, dict):
        return False
    if imagery.get("tile_url"):
        return True
    provider = imagery.get("provider") or "sentinel-2"
    return provider == "sentinel-2" and bool(imagery.get("mosaic_id"))


def imagery_config(state: dict) -> Optional[dict]:
    """Snapshot the imagery in state (ImageryState shape) for the widget.

    Returns None when no imagery was shown this conversation or the state
    lacks what the frontend renders from (see is_renderable_imagery).
    """
    imagery = state.get("imagery") or {}
    if not imagery.get("mosaic_id") or not is_renderable_imagery(imagery):
        return None
    return {key: imagery.get(key) for key in IMAGERY_KEYS}


def widget_config(layer: str, snapshot: dict, title: Optional[str]) -> dict:
    config: dict = {"default_view": "map", layer: snapshot}
    if title:
        config["title"] = title
    return config
