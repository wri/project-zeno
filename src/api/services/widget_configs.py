"""The map-widget config contract, in one place.

A map widget is a self-contained snapshot: the frontend renders
``config["dataset"]["tile_url"]`` or ``config["imagery"]["tile_url"]``
directly, with no catalog lookup and no chat state. Both the agent tool
(``add_map_widget``) and the analysis templates write that snapshot, so
the projection lives here — one definition, one set of keys.

The projections are explicit key allowlists. A dataset record carries prose
(description, methodology, instructions) and an imagery state may grow
fields; neither belongs in a widget's JSONB config, and an allowlist means
new upstream fields cannot leak into it by default.
"""

from typing import Mapping, Optional

#: Render-relevant fields of the imagery state (``ImageryState``) — all of it.
IMAGERY_KEYS = (
    "provider",
    "tile_url",
    "tilejson_url",
    "bounds",
    "min_zoom",
    "max_zoom",
    "mosaic_id",
    "item_count",
    "start_date",
    "end_date",
    "mean_cloud_cover",
    "min_cloud_cover",
    "max_cloud_cover_observed",
    "target_date",
    "window_days",
    "max_cloud_cover",
    "aoi_names",
)


def dataset_snapshot(dataset: Mapping) -> dict:
    """The ``dataset`` sub-object of a map widget's config.

    Takes a mapping, so both callers hand over what they already hold: the
    agent passes the dataset in its own state, a template passes
    ``asdict()`` of a resolved ``DatasetLayer``. The keys of the two are the
    same by design — a layer resolved from chat and one resolved by a
    template must render identically.
    """
    parameters = dataset.get("parameters")
    return {
        "dataset_id": dataset.get("dataset_id"),
        "dataset_name": dataset.get("dataset_name"),
        "tile_url": dataset.get("tile_url"),
        "context_layer": dataset.get("context_layer"),
        "context_layers": dataset.get("context_layers") or None,
        "parameters": [
            {"name": p.get("name"), "values": p.get("values")}
            for p in parameters
        ]
        if parameters
        else None,
        "start_date": dataset.get("start_date"),
        "end_date": dataset.get("end_date"),
    }


def imagery_snapshot(imagery: Mapping) -> dict:
    """The ``imagery`` sub-object of a map widget's config.

    Takes the ``ImageryState`` shape as a dict (``model_dump()`` or the agent
    state), so the imagery providers and the mosaic service share one path.
    """
    return {key: imagery.get(key) for key in IMAGERY_KEYS}


def map_widget_config(
    layer_key: str, snapshot: dict, title: Optional[str] = None
) -> dict:
    """A whole map-widget config around one layer snapshot.

    ``layer_key`` is ``"dataset"`` or ``"imagery"`` — exactly one, which is
    what ``DashboardWidgetCreateRequest`` validates on the REST path.
    """
    config: dict = {"default_view": "map", layer_key: snapshot}
    if title:
        config["title"] = title
    return config
