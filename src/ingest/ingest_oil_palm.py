"""Ingest the GFW oil palm concessions (``gfw_oil_palm``) into PostGIS.

Placeholder data: the real source is the ``gfw_oil_palm/v2025`` ndjson in the
GFW data lake, which this project cannot read yet. Until it can, this reads a
GeoJSON placeholder scraped from the public tile cache (one feature per
concession parcel, every source attribute kept, geometry simplified at the
tile zoom). Point
``OIL_PALM_DATA_SOURCE`` at the ndjson and swap the reader for
``gdf_from_ndjson_chunked`` once the data lake is readable.

Each row stays one AOI. A concession the source splits into parcels
("Palong 17" is 26 rows) is not merged: the parcels share a name and differ by
``cont_id``, which the display name carries.
"""

import os

import geopandas as gpd
import pandas as pd

from src.ingest.utils import (
    create_geometry_index_if_not_exists,
    create_id_index_if_not_exists,
    create_text_search_index_if_not_exists,
    ingest_to_postgis,
)
from src.shared.geocoding_helpers import AOI_SOURCE_ID_COLUMNS

OIL_PALM_DATA_SOURCE = os.environ.get(
    "OIL_PALM_DATA_SOURCE", "data/oil_palm_placeholder.geojson"
)
OIL_PALM_DATASET = "gfw_oil_palm"
TABLE = "geometries_oil_palm"

# The source's markers for a missing value.
_NO_DATA = {"", "No group", "Unknown", "na", "NA"}


def _clean(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return None if text in _NO_DATA else text


def oil_palm_name(row: pd.Series) -> str | None:
    """The display name: ``leaf (cont_id), company, type, ISO3``.

    The leaf is the source's own ``conc_name``; when that is missing, the
    company, then the company group, stands in. The company is left out when
    it already is the leaf.
    """
    company = _clean(row.get("company"))
    leaf = (
        _clean(row.get("conc_name"))
        or company
        or _clean(row.get("comp_group"))
    )
    if leaf is None:
        return None
    cont_id = _clean(row.get("cont_id"))
    if cont_id:
        leaf = f"{leaf} ({cont_id})"
    parts = [
        leaf,
        company
        if company and company != _clean(row.get("conc_name"))
        else None,
        _clean(row.get("conc_type")),
        _clean(row.get("iso3")),
    ]
    return ", ".join(part for part in parts if part)


def ingest_oil_palm() -> None:
    print(f"Reading oil palm concessions from {OIL_PALM_DATA_SOURCE}...")
    gdf = gpd.read_file(OIL_PALM_DATA_SOURCE)
    if "dataset" in gdf.columns:
        gdf = gdf[gdf["dataset"] == OIL_PALM_DATASET]
    # The scraped sample carries draft search fields; staging keeps only
    # the source's own columns.
    gdf = gdf.drop(
        columns=[
            c
            for c in gdf.columns
            if c.startswith("search_")
            or c in ("dataset", "subtype", "name", "source_id")
        ]
    )
    # The tile-cache placeholder has no cont_id; the source table does.
    for column in ("conc_name", "company", "comp_group", "cont_id"):
        if column not in gdf.columns:
            gdf[column] = None
    gdf["cont_id"] = gdf["cont_id"].astype("string")
    gdf["name"] = gdf.apply(oil_palm_name, axis=1)
    gdf["subtype"] = "oil-palm-concession"

    ingest_to_postgis(table_name=TABLE, gdf=gdf, if_exists="replace")

    create_geometry_index_if_not_exists(
        table_name=TABLE,
        index_name=f"idx_{TABLE}_geom",
        column="geometry",
    )
    create_text_search_index_if_not_exists(
        table_name=TABLE,
        index_name=f"idx_{TABLE}_name_gin",
        column="name",
    )
    id_column = AOI_SOURCE_ID_COLUMNS["oil_palm"]
    create_id_index_if_not_exists(
        table_name=TABLE,
        index_name=f"idx_{TABLE}_{id_column}",
        column=id_column,
    )

    print(f"✓ Oil palm ingestion completed: {len(gdf)} concessions")


if __name__ == "__main__":
    ingest_oil_palm()
