"""
Canonical map-layer registry: the tile URL for each dataset and how that URL
takes a date filter, derived from the `tile_url` / `tile_date_filter` keys in
the catalog YAMLs (`src/agent/datasets/catalog/*.yml`).

Date filtering is per-dataset: Integrated alerts takes `start_date`/`end_date`
query params, annual tree-cover layers take `start_year`/`end_year`, and the
annual rasters carry the year in the item path. `tile_date_filter` names the
convention so both the agent (get_tile_services_for_dataset, which builds the
URL the map renders) and API clients (which build it for layers added outside
a conversation) resolve it from the same place, instead of each keeping its
own list of dataset ids.

Served URLs are absolute and carry their remaining placeholders literally:
`{z}`/`{x}`/`{y}` always, `{threshold}` on the canopy-cover datasets, and
`{year}` on the annual rasters.
"""

from typing import Optional, TypedDict

from src.agent.datasets.config import DATASETS
from src.shared.config import SharedSettings

# Query params appended to the tile URL, e.g.
# `&start_date=2026-08-25&end_date=2026-09-08` (Integrated alerts).
DATE_PARAMS = "date_params"
# Year-granular query params, e.g. `&start_year=2001&end_year=2025`
# (annual tree cover loss).
YEAR_PARAMS = "year_params"
# The year identifies the raster item in the URL path, so the URL carries a
# `{year}` placeholder instead of a filter (annual land cover, grasslands).
YEAR_IN_PATH = "year_in_path"
# The layer has no time dimension to filter on.
NO_DATE_FILTER = "none"

TILE_DATE_FILTERS = frozenset(
    {DATE_PARAMS, YEAR_PARAMS, YEAR_IN_PATH, NO_DATE_FILTER}
)

# Canopy-cover threshold applied when a request names none. Shared with
# get_tile_services_for_dataset so a `{threshold}` URL resolves the same way
# whoever fills it in.
DEFAULT_CANOPY_COVER = 30

_CANOPY_COVER = "canopy_cover"
_THRESHOLD_PLACEHOLDER = "{threshold}"


class DatasetLayer(TypedDict):
    dataset_id: int
    dataset_name: str
    # Absolute, with `{z}`/`{x}`/`{y}` and any `{threshold}`/`{year}` left for
    # the client to fill.
    tile_url: str
    # One of TILE_DATE_FILTERS: how to scope this URL to a date range.
    date_filter: str
    # First date the dataset covers.
    start_date: str
    # Last date covered, or None when the dataset is ongoing (use today).
    end_date: Optional[str]
    # True when the dataset covers one fixed period that a request cannot
    # narrow — clients should show the full range rather than a requested one.
    content_date_fixed: bool
    # Allowed canopy-cover values, and the one to use by default. Both None
    # unless the tile URL carries a `{threshold}` placeholder.
    threshold_values: Optional[list[int]]
    default_threshold: Optional[int]


def _public_tile_url(dataset: dict, date_filter: str) -> str:
    tile_url: str = dataset["tile_url"]
    if date_filter == YEAR_IN_PATH:
        # These are str.format templates on `year`, so the YAML escapes the
        # tile scheme as {{z}}/{{x}}/{{y}}. Clients get it unescaped.
        tile_url = tile_url.replace("{{", "{").replace("}}", "}")
    if not tile_url.startswith("http"):
        tile_url = SharedSettings.eoapi_base_url.rstrip("/") + tile_url
    return tile_url


def _threshold_values(dataset: dict) -> Optional[list[int]]:
    for parameter in dataset.get("parameters") or []:
        if parameter.get("name") == _CANOPY_COVER:
            return list(parameter.get("values") or [])
    return None


def _build_layers() -> dict[int, DatasetLayer]:
    layers: dict[int, DatasetLayer] = {}
    for dataset in DATASETS:
        if not dataset.get("tile_url"):
            continue

        dataset_id = dataset["dataset_id"]
        context = f"dataset_id={dataset_id} ({dataset['dataset_name']})"

        date_filter = dataset.get("tile_date_filter") or NO_DATE_FILTER
        if date_filter not in TILE_DATE_FILTERS:
            raise ValueError(
                f"unknown tile_date_filter {date_filter!r} in {context}; "
                f"expected one of {sorted(TILE_DATE_FILTERS)}"
            )

        tile_url = _public_tile_url(dataset, date_filter)

        # The two param conventions append with `&`, so the URL must already
        # carry a query string, and a `{year}` layer must have somewhere to
        # put the year. Catching these here beats serving a URL that 404s.
        if date_filter in (DATE_PARAMS, YEAR_PARAMS) and "?" not in tile_url:
            raise ValueError(
                f"tile_date_filter {date_filter!r} appends query params but "
                f"the tile_url in {context} has no query string"
            )
        if date_filter == YEAR_IN_PATH and "{year}" not in tile_url:
            raise ValueError(
                f"tile_date_filter {YEAR_IN_PATH!r} needs a {{year}} "
                f"placeholder, missing from the tile_url in {context}"
            )

        threshold_values: Optional[list[int]] = None
        if _THRESHOLD_PLACEHOLDER in tile_url:
            threshold_values = _threshold_values(dataset)
            if not threshold_values:
                raise ValueError(
                    f"the tile_url in {context} has a "
                    f"{_THRESHOLD_PLACEHOLDER} placeholder but no "
                    f"{_CANOPY_COVER} parameter values"
                )

        layers[dataset_id] = DatasetLayer(
            dataset_id=dataset_id,
            dataset_name=dataset["dataset_name"],
            tile_url=tile_url,
            date_filter=date_filter,
            start_date=dataset["start_date"],
            end_date=dataset.get("end_date"),
            content_date_fixed=bool(dataset.get("content_date_fixed")),
            threshold_values=threshold_values,
            default_threshold=(
                DEFAULT_CANOPY_COVER if threshold_values else None
            ),
        )
    return layers


LAYERS: dict[int, DatasetLayer] = _build_layers()


def get_dataset_layer(dataset_id: int) -> Optional[DatasetLayer]:
    """Return the map-layer entry for a dataset, or None if it has no tiles."""
    return LAYERS.get(dataset_id)
