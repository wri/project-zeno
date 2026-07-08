import json
from typing import Any, Dict, Optional, Union
from uuid import UUID

import pandas as pd
from sqlalchemy import select, text

from src.api.data_models import CustomAreaOrm
from src.shared.database import (
    get_connection_from_pool,
    get_session_from_pool,
)
from src.shared.logging_config import get_logger
from src.shared.request_context import current_user_id

logger = get_logger(__name__)

GADM_TABLE = "geometries_gadm"
KBA_TABLE = "geometries_kba"
LANDMARK_TABLE = "geometries_landmark"
WDPA_TABLE = "geometries_wdpa"
CUSTOM_AREA_TABLE = "custom_areas"


SUBREGION_TO_SUBTYPE_MAPPING = {
    "country": "country",
    "state": "state-province",
    "district": "district-county",
    "municipality": "municipality",
    "locality": "locality",
    "neighbourhood": "neighbourhood",
    "kba": "key-biodiversity-area",
    "wdpa": "protected-area",
    "landmark": "indigenous-and-community-land",
    "custom": "custom-area",
}


SOURCE_ID_MAPPING = {
    "kba": {"table": KBA_TABLE, "id_column": "sitrecid"},
    "landmark": {"table": LANDMARK_TABLE, "id_column": "landmark_id"},
    "wdpa": {"table": WDPA_TABLE, "id_column": "wdpa_pid"},
    "gadm": {"table": GADM_TABLE, "id_column": "gadm_id"},
    "custom": {"table": CUSTOM_AREA_TABLE, "id_column": "id"},
}


# GADM LEVELS
GADM_LEVELS = {
    "country": {"col_name": "GID_0", "name": "iso"},
    "state-province": {"col_name": "GID_1", "name": "adm1"},
    "district-county": {"col_name": "GID_2", "name": "adm2"},
    "municipality": {"col_name": "GID_3", "name": "adm3"},
    "locality": {"col_name": "GID_4", "name": "adm4"},
    "neighbourhood": {"col_name": "GID_5", "name": "adm5"},
}

GADM_SUBTYPE_MAP = {val["col_name"]: key for key, val in GADM_LEVELS.items()}

# Matches standard GADM IDs (3-letter ISO prefix): "USA", "BRA.16_1", "IND.12.26_1", etc.
# Excludes disputed-territory codes like "Z01", "Z02" which downstream APIs reject.
GADM_STANDARD_ID_RE = r"^[A-Z]{3}"


# Friendly source aliases accepted from callers (e.g. the search API) and
# mapped onto the canonical source keys used in SOURCE_ID_MAPPING.
SOURCE_ALIASES = {
    "protectedareas": "wdpa",
    "protected_areas": "wdpa",
    "protected-areas": "wdpa",
}

VALID_AOI_SOURCES = set(SOURCE_ID_MAPPING.keys())


def normalize_aoi_source(source: str) -> str:
    """Map a (possibly aliased) source name onto a canonical source key."""
    key = SOURCE_ALIASES.get(source.lower(), source.lower())
    if key not in VALID_AOI_SOURCES:
        raise ValueError(
            f"Invalid source: {source}. Must be one of: "
            f"{', '.join(sorted(VALID_AOI_SOURCES))}"
        )
    return key


def _antimeridian_bbox_sql(geom_expr: str) -> str:
    """
    Returns [west, south, east, north] JSON array.
    For antimeridian-crossing geometries (span > 180°), clips to each
    half-plane to get the bbox of the eastern and western parts separately —
    no ST_Dump, no vertex iteration. Falls back to naive bbox if either
    clip returns nothing (geometry doesn't truly cross the antimeridian).
    """
    east_half = "ST_MakeEnvelope(0, -90, 180, 90, 4326)"
    west_half = "ST_MakeEnvelope(-180, -90, 0, 90, 4326)"
    return f"""
    CASE
        WHEN ST_XMax({geom_expr}) - ST_XMin({geom_expr}) > 180
        THEN (
            SELECT COALESCE(
                CASE
                    WHEN west IS NOT NULL AND east IS NOT NULL
                    THEN json_build_array(west, ST_YMin({geom_expr}), east, ST_YMax({geom_expr}))
                END,
                json_build_array(ST_XMin({geom_expr}), ST_YMin({geom_expr}), ST_XMax({geom_expr}), ST_YMax({geom_expr}))
            )
            FROM (
                SELECT
                    ST_XMin(ST_Envelope(ST_ClipByBox2D({geom_expr}, {east_half}))) AS west,
                    ST_XMax(ST_Envelope(ST_ClipByBox2D({geom_expr}, {west_half}))) AS east
            ) AS parts
        )
        ELSE json_build_array(
            ST_XMin({geom_expr}),
            ST_YMin({geom_expr}),
            ST_XMax({geom_expr}),
            ST_YMax({geom_expr})
        )
    END
    """


BBOX_SQL = f"({_antimeridian_bbox_sql('geometry')}) AS bbox"

# The custom geometries table stores geometries as an list of geojsons,
# requiring a funky SQL to pull out the overall bounds
CUSTOM_BBOX_SQL = f"""
(
    SELECT {_antimeridian_bbox_sql("bounds.geometry")}
    FROM (
        SELECT ST_Envelope(
            ST_Collect(ST_SetSRID(ST_GeomFromGeoJSON(geom_json), 4326))
        ) AS geometry
        FROM jsonb_array_elements_text(geometries) AS geom(geom_json)
    ) AS bounds
) AS bbox
"""


async def search_aois(
    name: Optional[str],
    sources: Optional[list[str]],
    user_id: Optional[str],
    limit: int = 50,
    offset: int = 0,
) -> pd.DataFrame:
    """Search AOIs across sources by name and/or source type.

    This is the shared search core reused by both the agent's ``pick_aoi``
    geocoder (via :func:`query_aoi_database`) and the ``GET /api/aois``
    endpoint.

    Args:
        name: Fuzzy name to search for. When empty/None the query runs in
            *browse* mode: no name filter, ordered alphabetically.
        sources: Subset of canonical source keys (gadm/kba/wdpa/landmark/custom)
            to search; ``None`` searches all available sources. Aliases such as
            ``protectedareas`` are accepted and normalized.
        user_id: Owner used to scope custom areas. Required when ``custom`` is
            among the searched sources.
        limit: Maximum number of rows to return.
        offset: Number of rows to skip (offset pagination).

    Returns:
        DataFrame with columns ``src_id, name, subtype, source, bbox`` (plus
        ``similarity_score`` when searching by name).
    """
    if sources:
        requested = {normalize_aoi_source(s) for s in sources}
    else:
        requested = set(SOURCE_ID_MAPPING.keys())

    has_name = bool(name and name.strip())

    async with get_connection_from_pool() as conn:
        # Enable pg_trgm extension for the similarity function
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        await conn.execute(text("SET pg_trgm.similarity_threshold = 0.2;"))
        await conn.commit()

        # Probe which of the requested tables actually exist
        existing_tables = []
        for source in ("gadm", "kba", "landmark", "wdpa", "custom"):
            if source not in requested:
                continue
            table = SOURCE_ID_MAPPING[source]["table"]
            try:
                await conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
                existing_tables.append(source)
            except Exception:
                logger.warning(f"Table {table} does not exist")
                await conn.rollback()

        name_filter = "AND name % :name" if has_name else ""
        union_parts = []

        if "gadm" in existing_tables:
            union_parts.append(
                f"""
                SELECT gadm_id AS src_id, name, subtype, 'gadm' as source, {BBOX_SQL}
                FROM {GADM_TABLE}
                WHERE name IS NOT NULL AND gadm_id ~ '{GADM_STANDARD_ID_RE}' {name_filter}
            """
            )

        for source in ("kba", "landmark", "wdpa"):
            if source in existing_tables:
                id_column = SOURCE_ID_MAPPING[source]["id_column"]
                table = SOURCE_ID_MAPPING[source]["table"]
                union_parts.append(
                    f"""
                    SELECT CAST({id_column} AS TEXT) as src_id,
                           name, subtype, '{source}' as source, {BBOX_SQL}
                    FROM {table}
                    WHERE name IS NOT NULL {name_filter}
                """
                )

        if "custom" in existing_tables:
            if not user_id:
                raise ValueError("user_id required for custom areas")
            id_column = SOURCE_ID_MAPPING["custom"]["id_column"]
            union_parts.append(
                f"""
                SELECT CAST({id_column} AS TEXT) as src_id,
                       name, 'custom-area' as subtype, 'custom' as source, {CUSTOM_BBOX_SQL}
                FROM {CUSTOM_AREA_TABLE}
                WHERE user_id = :user_id AND name IS NOT NULL {name_filter}
            """
            )

        if not union_parts:
            logger.warning("No matching geometry tables exist for the request")
            return pd.DataFrame()

        combined_query = " UNION ALL ".join(union_parts)

        if has_name:
            sql_query = f"""
                WITH combined_search AS (
                    {combined_query}
                )
                SELECT *,
                       similarity(LOWER(name), LOWER(:name)) AS similarity_score
                FROM combined_search
                WHERE name IS NOT NULL AND name % :name
                ORDER BY similarity_score DESC, name, source, src_id
                LIMIT :limit OFFSET :offset
            """
        else:
            sql_query = f"""
                WITH combined_search AS (
                    {combined_query}
                )
                SELECT *
                FROM combined_search
                WHERE name IS NOT NULL
                ORDER BY name, source, src_id
                LIMIT :limit OFFSET :offset
            """

        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if has_name:
            params["name"] = name
        if "custom" in existing_tables:
            params["user_id"] = user_id

        def _read(sync_conn):
            return pd.read_sql(text(sql_query), sync_conn, params=params)

        return await conn.run_sync(_read)


def format_id(idx):
    """
    Convert the ID to a string and remove the last two characters if they are '_1', '_2', '_3', '_4', or '_5'.
    """
    idx = str(idx)
    if idx[-2:] in ["_1", "_2", "_3", "_4", "_5"]:
        return idx[:-2]
    return idx


async def get_geometry_data(
    source: str, src_id: str, user_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Get geometry data by source and source ID.

    Args:
        source: Source type (gadm, kba, landmark, wdpa, custom)
        src_id: Source-specific ID
        session: Database session
        user_id: User ID (required for custom areas; falls back to request context)

    Returns:
        Dict with name, subtype, source, src_id, and geometry, or None if not found

    Raises:
        ValueError: For invalid source or missing user_id for custom areas
    """

    async with get_session_from_pool() as session:
        if source == "custom":
            user_id = user_id or current_user_id()
            if not user_id:
                raise ValueError("user_id required for custom areas")

            try:
                area_id = UUID(src_id)
            except ValueError:
                raise ValueError(
                    f"Invalid UUID format for custom area ID: {src_id}"
                )

            stmt = select(CustomAreaOrm).filter_by(id=area_id, user_id=user_id)
            result = await session.execute(stmt)
            custom_area = result.scalars().first()

            if not custom_area:
                return None

            # Parse the stored geometries JSONB field
            try:
                geometries = (
                    [
                        json.loads(geom_str)
                        for geom_str in custom_area.geometries
                    ]
                    if custom_area.geometries
                    else []
                )

                if len(geometries) == 0:
                    geometry = None
                elif len(geometries) == 1:
                    geometry = geometries[0]
                else:
                    # Multiple geometries - return as GeometryCollection
                    geometry = {
                        "type": "GeometryCollection",
                        "geometries": geometries,
                    }
            except (json.JSONDecodeError, IndexError):
                geometry = None

            return {
                "name": custom_area.name,
                "subtype": "custom",
                "source": source,
                "src_id": src_id,
                "geometry": geometry,
            }

        # Handle standard geometry sources
        if source not in SOURCE_ID_MAPPING:
            valid_sources = list(SOURCE_ID_MAPPING.keys())
            raise ValueError(
                f"Invalid source: {source}. Must be one of: {', '.join(valid_sources)}"
            )

        table_name = SOURCE_ID_MAPPING[source]["table"]
        id_column = SOURCE_ID_MAPPING[source]["id_column"]

        sql_query = f"""
            SELECT name, subtype, ST_AsGeoJSON(geometry) as geometry_json
            FROM {table_name}
            WHERE "{id_column}" = :src_id
        """

        nsrc_id: Union[int, str] = src_id
        if source == "kba":
            # These sources IDs stored as numeric values. Convert nsrc_id to integer
            # if we can, else leave as string.
            try:
                nsrc_id = int(nsrc_id)
            except ValueError:
                pass

        q = await session.execute(text(sql_query), {"src_id": nsrc_id})
        result = q.first()

        if not result:
            return None

        # Parse GeoJSON string
        try:
            geometry = (
                json.loads(result.geometry_json)
                if result.geometry_json
                else None
            )
        except json.JSONDecodeError:
            geometry = None

        return {
            "name": result.name,
            "subtype": result.subtype,
            "source": source,
            "src_id": nsrc_id,
            "geometry": geometry,
        }
