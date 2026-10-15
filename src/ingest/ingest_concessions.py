"""Ingest the GFW concession datasets into PostGIS, one table per type.

Reads the GFW Data API's NDJSON export of each dataset. The export holds the
rows of the published source zip (``gfw_global_*_concessions_v2025*.zip``,
same row count, same attributes) plus ``gfw_fid`` and ``gfw_geostore_id``.
``gfw_fid`` is the id the GFW tile cache carries, so an area picked on the
GFW concession layer resolves to the same AOI that search finds.

The five datasets share one schema (``iso3``, ``conc_type``, ``conc_name``,
``cont_type``, ``cont_id``, ``company``, ``comp_group``, ...). Mining has
``mineral`` in place of ``comp_group``.

The file is downloaded once to disk, then streamed through GDAL in small
batches, so memory stays flat: the mining export is 928 MB and a logging
parcel can hold 482,000 vertices.

Concessions are not searchable by name; they are reached as the subregions
of a place. The ``name`` written here is their display name.

Each row stays one AOI. A concession the source splits into parcels
("Palong 17" is 26 rows) is not merged: the parcels share a name and differ
by ``cont_id`` where the source has one. A row with no name, company or group
is kept with a generic name ("Logging concession, CAN"), so it can still be
picked on the map and listed as a subregion.

Usage::

    uv run python src/ingest/ingest_concessions.py            # all types
    uv run python src/ingest/ingest_concessions.py oil_palm mining
"""

import re
import sys
from dataclasses import dataclass, field

import geopandas as gpd
import pandas as pd
import pyogrio
from sqlalchemy import create_engine, text

from src.ingest.utils import (
    DB_URL,
    cached_ndjson_path,
    create_geometry_index_if_not_exists,
    create_id_index_if_not_exists,
)
from src.shared.geocoding_helpers import (
    AOI_SOURCE_ID_COLUMNS,
    SOURCE_STAGING_TABLES,
    SUBREGION_TO_SUBTYPE_MAPPING,
)

_DATA_LAKE = "s3://gfw-data-lake"
_NDJSON = "vector/epsg-4326/default.ndjson"


@dataclass(frozen=True)
class ConcessionDataset:
    source: str  # the AOI source key
    url: str
    # conc_name values that name no concession: a territory or a pointer to
    # another table, repeated over thousands of rows.
    name_markers: frozenset[str] = field(default_factory=frozenset)
    # Whether cont_id tells this dataset's parcels apart. RSPO's is the
    # member's certification number, shared by thousands of parcels.
    cont_id_in_name: bool = True


CONCESSION_DATASETS = {
    "oil_palm": ConcessionDataset(
        source="oil_palm",
        url=f"{_DATA_LAKE}/gfw_oil_palm/v2025/{_NDJSON}",
    ),
    "rspo_oil_palm": ConcessionDataset(
        source="rspo_oil_palm",
        url=f"{_DATA_LAKE}/rspo_oil_palm/v2025/{_NDJSON}",
        cont_id_in_name=False,
    ),
    "logging": ConcessionDataset(
        source="logging",
        url=f"{_DATA_LAKE}/gfw_managed_forests/v2025/{_NDJSON}",
    ),
    "mining": ConcessionDataset(
        source="mining",
        url=f"{_DATA_LAKE}/gfw_mining_concessions/v2025/{_NDJSON}",
        # "Yukon Territory" is the conc_name of 21,603 Yukon claims.
        name_markers=frozenset(
            {"Yukon Territory", "REFER TO LOT TABLE", "Not found"}
        ),
    ),
    "wood_fiber": ConcessionDataset(
        source="wood_fiber",
        url=f"{_DATA_LAKE}/gfw_wood_fiber/v2025/{_NDJSON}",
    ),
}

# The text columns that feed the display name and the search columns.
_TEXT_COLUMNS = (
    "conc_name",
    "company",
    "comp_group",
    "conc_type",
    "cont_type",
    "cont_id",
    "mineral",
)

# The sources' markers for a missing value, in any text column.
_NO_DATA = frozenset(
    {
        "",
        "NA",
        "ND",
        "na",
        "No Data",
        "No group",
        "Unknown",
        "Other / Unknown",
        "DADO NÃO CADASTRADO",  # SIGMINE (Brazil): "data not registered"
    }
)

# A holder's share of the concession, which mining sources append to the
# company: "IDM Mining Ltd - 100%", "Desai Miyoba (100%)", "JOSE G. GUTIERREZ
# MONARREZ 67%", "Glencore Canada Corporation (92528) 100 % (responsable)".
# A number is only taken as a share when "%" follows it, so "(1981) Limited"
# stays.
_SHARE_RE = re.compile(
    r"\s*(?:\(\d+\)\s*)?(?:-\s*)?\(?\d{1,3}(?:[.,]\d+)?\s*%\)?"
    r"(?:\s*\(responsable\))?"
)


def clean_text(value, markers: frozenset[str] = frozenset()) -> str | None:
    """*value* trimmed, or None when it is missing or a no-data marker."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return None if text in _NO_DATA or text in markers else text


def strip_shares(company: str | None) -> str | None:
    """The company without its holders' ownership shares."""
    if company is None:
        return None
    stripped = _SHARE_RE.sub("", company)
    stripped = re.sub(r"\s*,\s*", ", ", stripped).strip(" ,")
    return stripped or None


def concession_name(row: pd.Series, cont_id_in_name: bool = True) -> str:
    """The display name: ``leaf (cont_id), company, type, ISO3``.

    The leaf is the source's own ``conc_name``; when that is missing, the
    company, then the company group, stands in. The company is left out when
    it already is the leaf. A row with no leaf is named by its type.
    """
    name = row.get("conc_name")
    company = row.get("company")
    conc_type = row.get("conc_type")
    leaf = name or company or row.get("comp_group")
    head = leaf or conc_type
    cont_id = row.get("cont_id") if cont_id_in_name else None
    if cont_id:
        head = f"{head} ({cont_id})"
    parts = [
        head,
        company if company and company != name and company != leaf else None,
        conc_type if leaf else None,
        row.get("iso3"),
    ]
    return ", ".join(part for part in parts if part)


def prepare(chunk: pd.DataFrame, dataset: ConcessionDataset) -> pd.DataFrame:
    """Clean one chunk of a dataset and add its ``name`` and ``subtype``."""
    for column in _TEXT_COLUMNS:
        if column in chunk.columns:
            markers = dataset.name_markers if column == "conc_name" else None
            chunk[column] = (
                chunk[column]
                .map(lambda v, m=markers: clean_text(v, m or frozenset()))
                .astype("object")
            )
    if "company" in chunk.columns:
        chunk["company"] = chunk["company"].map(strip_shares)
    chunk["name"] = chunk.apply(
        concession_name, axis=1, cont_id_in_name=dataset.cont_id_in_name
    )
    chunk["subtype"] = SUBREGION_TO_SUBTYPE_MAPPING[dataset.source]
    return chunk


_BATCH_SIZE = 500


def ingest_concessions(dataset: ConcessionDataset) -> None:
    table = SOURCE_STAGING_TABLES[dataset.source]
    id_column = AOI_SOURCE_ID_COLUMNS[dataset.source]
    path = cached_ndjson_path(dataset.url)
    print(f"Loading {dataset.source} concessions from {path}...")

    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

    total = 0
    with pyogrio.raw.open_arrow(
        path, batch_size=_BATCH_SIZE, use_pyarrow=True
    ) as (_, reader):
        for batch in reader:
            chunk = gpd.GeoDataFrame.from_arrow(batch)
            chunk = chunk.set_crs("EPSG:4326", allow_override=True)
            # GDAL names the column after its own field (wkb_geometry);
            # the build reads "geometry".
            if chunk.geometry.name != "geometry":
                chunk = chunk.rename_geometry("geometry")
            prepare(chunk, dataset).to_postgis(
                table,
                engine,
                if_exists="replace" if total == 0 else "append",
                index=False,
            )
            total += len(chunk)
            if total % 50_000 < _BATCH_SIZE:
                print(f"  {total} rows...")

    create_geometry_index_if_not_exists(
        table_name=table, index_name=f"idx_{table}_geom", column="geometry"
    )
    create_id_index_if_not_exists(
        table_name=table,
        index_name=f"idx_{table}_{id_column}",
        column=id_column,
    )
    print(f"✓ {dataset.source} ingestion completed: {total} concessions")


if __name__ == "__main__":
    names = sys.argv[1:] or list(CONCESSION_DATASETS)
    unknown = set(names) - set(CONCESSION_DATASETS)
    if unknown:
        sys.exit(f"Unknown concession type(s): {', '.join(sorted(unknown))}")
    for name in names:
        ingest_concessions(CONCESSION_DATASETS[name])
