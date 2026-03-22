import json
from typing import Any, Dict, Optional
from uuid import UUID

import structlog
from sqlalchemy import select, text

from src.api.data_models import CustomAreaOrm
from src.shared.aoi.registry import all_sources, get_source
from src.shared.database import get_session_from_pool

# ---------------------------------------------------------------------------
# Backward-compatible constants — derived from the registry.
# Existing imports throughout the codebase continue to work.
# ---------------------------------------------------------------------------
GADM_TABLE = get_source("gadm").table
KBA_TABLE = get_source("kba").table
LANDMARK_TABLE = get_source("landmark").table
WDPA_TABLE = get_source("wdpa").table
CUSTOM_AREA_TABLE = get_source("custom").table

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

# Derived from registry — kept for backward compat
SOURCE_ID_MAPPING = {
    cfg.source_type.value: {"table": cfg.table, "id_column": cfg.id_column}
    for cfg in all_sources()
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


def format_id(idx):
    """
    Convert the ID to a string and remove the last two characters if they are '_1', '_2', '_3', '_4', or '_5'.
    """
    idx = str(idx)
    if idx[-2:] in ["_1", "_2", "_3", "_4", "_5"]:
        return idx[:-2]
    return idx


async def get_geometry_data(
    source: str, src_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get geometry data by source and source ID.

    Args:
        source: Source type (gadm, kba, landmark, wdpa, custom)
        src_id: Source-specific ID
        session: Database session
        user_id: User ID (required for custom areas)

    Returns:
        Dict with name, subtype, source, src_id, and geometry, or None if not found

    Raises:
        ValueError: For invalid source or missing user_id for custom areas
    """

    async with get_session_from_pool() as session:
        if source == "custom":
            user_id = structlog.contextvars.get_contextvars().get("user_id")
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

        # Handle standard geometry sources via registry
        try:
            config = get_source(source)
        except (ValueError, KeyError):
            valid_sources = [c.source_type.value for c in all_sources()]
            raise ValueError(
                f"Invalid source: {source}. Must be one of: {', '.join(valid_sources)}"
            )

        sql_query = f"""
            SELECT name, subtype, ST_AsGeoJSON(geometry) as geometry_json
            FROM {config.table}
            WHERE "{config.id_column}" = :src_id
        """

        coerced_id = config.coerce_id(src_id)

        q = await session.execute(text(sql_query), {"src_id": coerced_id})
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
            "src_id": src_id,
            "geometry": geometry,
        }
