"""GFW static vector tile filter + WGS84 bbox hints for pick_aoi UI state.

Static tile URL pattern (no /dynamic/):
``https://tiles.globalforestwatch.org/{dataset}/{version}/default/{z}/{x}/{y}.pbf``
"""

from __future__ import annotations

import json
from typing import Any, List

import structlog
from sqlalchemy import bindparam, text

from src.shared.database import get_connection_from_pool
from src.shared.geocoding_helpers import (
    GADM_LEVELS,
    SOURCE_ID_MAPPING,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

GFW_TILE_URL_PATTERN = (
    "https://tiles.globalforestwatch.org/"
    "{dataset}/{version}/default/{z}/{x}/{y}.pbf"
)

# GADM: split static caches use v4.1; combined uses v4.1.85 (see inspect_gfw_pbf_tiles).
_GADM_SPLIT_VERSION = "v4.1"
_GADM_COMBINED_VERSION = "v4.1.85"

# subtype -> (dataset_name, version, suggested_detail_zoom, sample_xy for docs)
GADM_GFW_STATIC: dict[str, tuple[str, str, int, tuple[int, int] | None]] = {
    "country": (
        "gadm_administrative_boundaries_adm0",
        _GADM_SPLIT_VERSION,
        2,
        None,
    ),
    "state-province": (
        "gadm_administrative_boundaries_adm0_adm1",
        _GADM_SPLIT_VERSION,
        3,
        None,
    ),
    "district-county": (
        "gadm_administrative_boundaries_adm0_adm1_adm2",
        _GADM_SPLIT_VERSION,
        6,
        (0, 16),
    ),
    "municipality": (
        "gadm_administrative_boundaries",
        _GADM_COMBINED_VERSION,
        8,
        None,
    ),
    "locality": (
        "gadm_administrative_boundaries",
        _GADM_COMBINED_VERSION,
        9,
        None,
    ),
    "neighbourhood": (
        "gadm_administrative_boundaries",
        _GADM_COMBINED_VERSION,
        10,
        None,
    ),
    "global": (
        "gadm_administrative_boundaries",
        _GADM_COMBINED_VERSION,
        2,
        None,
    ),
}

_NON_GADM_SPECS: dict[str, dict[str, Any]] = {
    "kba": {
        "dataset": "birdlife_key_biodiversity_areas",
        "version": "v20240903",
        "source_layer": "birdlife_key_biodiversity_areas",
        "filter_property": "sitrecid",
        "numeric_ids": True,
        "zoom": 2,
    },
    "landmark": {
        "dataset": "landmark_indigenous_and_community_lands",
        "version": "latest",
        "source_layer": "landmark_indigenous_and_community_lands",
        # MVT uses gfw_fid; DB primary key is landmark_id — same value in GFW pipelines.
        "filter_property": "gfw_fid",
        "numeric_ids": True,
        "zoom": 2,
    },
    "wdpa": {
        "dataset": "wdpa_protected_areas",
        "version": "latest",
        "source_layer": "wdpa_protected_areas",
        "filter_property": "wdpa_pid",
        "numeric_ids": False,
        "zoom": 2,
    },
}


def _gadm_mvt_prop_for_subtype(subtype: str) -> str | None:
    if subtype not in GADM_LEVELS and subtype != "global":
        return None
    if subtype == "global":
        return "gid_0"
    return GADM_LEVELS[subtype]["col_name"].lower()


def mapbox_membership_filter(
    property_name: str, values: List[Any]
) -> list[Any]:
    """Mapbox GL expression: feature is highlighted iff property is in values."""
    if not values:
        return ["==", ["get", property_name], "__no_match__"]
    if len(values) == 1:
        return ["==", ["get", property_name], values[0]]
    return ["in", ["get", property_name], ["literal", values]]


def _coerce_filter_values(
    raw_ids: List[str], *, as_numbers: bool
) -> List[Any]:
    if not as_numbers:
        return [str(x) for x in raw_ids]
    out: List[Any] = []
    for x in raw_ids:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            try:
                out.append(float(x))
            except (TypeError, ValueError):
                out.append(str(x))
    return out


def _unique_preserve(ids: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for i in ids:
        if i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out


def _gfw_static_config_for_gadm(
    subtype: str, gadm_ids: List[str]
) -> dict[str, Any] | None:
    spec = GADM_GFW_STATIC.get(subtype) or GADM_GFW_STATIC["global"]
    dataset, version, zoom, sample_xy = spec
    prop = _gadm_mvt_prop_for_subtype(subtype)
    if prop is None:
        return None
    values = _coerce_filter_values(
        _unique_preserve(gadm_ids), as_numbers=False
    )
    filt = mapbox_membership_filter(prop, values)
    cfg: dict[str, Any] = {
        "tile_url_pattern": GFW_TILE_URL_PATTERN,
        "dataset": dataset,
        "version": version,
        "implementation": "default",
        "source_layer": dataset,
        "filter": filt,
        "filter_property": prop,
        "suggested_detail_zoom": zoom,
    }
    if sample_xy is not None:
        cfg["sample_tile_xy"] = list(sample_xy)
    return cfg


def _gfw_static_config_non_gadm(
    source: str, src_ids: List[str]
) -> dict[str, Any]:
    meta = _NON_GADM_SPECS[source]
    raw_ids = _unique_preserve(src_ids)
    values = _coerce_filter_values(raw_ids, as_numbers=meta["numeric_ids"])
    prop = meta["filter_property"]
    filt = mapbox_membership_filter(prop, values)
    return {
        "tile_url_pattern": GFW_TILE_URL_PATTERN,
        "dataset": meta["dataset"],
        "version": meta["version"],
        "implementation": "default",
        "source_layer": meta["source_layer"],
        "filter": filt,
        "filter_property": prop,
        "suggested_detail_zoom": meta["zoom"],
    }


def _flatten_positions(coords: Any) -> List[tuple[float, float]]:
    if coords is None:
        return []
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        if isinstance(coords[0], (int, float)) and isinstance(
            coords[1], (int, float)
        ):
            return [(float(coords[0]), float(coords[1]))]
    if isinstance(coords, (list, tuple)):
        out: List[tuple[float, float]] = []
        for c in coords:
            out.extend(_flatten_positions(c))
        return out
    return []


def bbox_from_geojson_dict(geom: dict[str, Any]) -> List[tuple[float, float]]:
    gtype = geom.get("type")
    if gtype == "GeometryCollection":
        nested = geom.get("geometries") or []
        pts: List[tuple[float, float]] = []
        for g in nested:
            if isinstance(g, dict):
                pts.extend(bbox_from_geojson_dict(g))
        return pts
    return _flatten_positions(geom.get("coordinates"))


def bbox_wgs84_from_geojson_geometries(
    geometries: List[Any],
) -> dict[str, float] | None:
    lngs: List[float] = []
    lats: List[float] = []
    for item in geometries:
        if isinstance(item, str):
            try:
                body = json.loads(item)
            except json.JSONDecodeError:
                continue
        elif isinstance(item, dict):
            body = item
        else:
            continue
        for lng, lat in bbox_from_geojson_dict(body):
            lngs.append(lng)
            lats.append(lat)
    if not lngs:
        return None
    return {
        "west": min(lngs),
        "south": min(lats),
        "east": max(lngs),
        "north": max(lats),
    }


async def _fetch_bbox_postgis(
    table: str, id_column: str, ids: List[str]
) -> dict[str, float] | None:
    if not ids:
        return None

    stmt = text(
        f"""
        SELECT
            MIN(ST_XMin(geometry::geometry)) AS west,
            MIN(ST_YMin(geometry::geometry)) AS south,
            MAX(ST_XMax(geometry::geometry)) AS east,
            MAX(ST_YMax(geometry::geometry)) AS north
        FROM {table}
        WHERE "{id_column}" IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))

    async with get_connection_from_pool() as conn:

        def _read(sync_conn):
            result = sync_conn.execute(stmt, {"ids": list(ids)})
            return result.mappings().first()

        row = await conn.run_sync(_read)
    if not row or row["west"] is None:
        return None
    return {
        "west": float(row["west"]),
        "south": float(row["south"]),
        "east": float(row["east"]),
        "north": float(row["north"]),
    }


async def _fetch_bbox_custom(
    ids: List[str], user_id: str
) -> dict[str, float] | None:
    stmt = text(
        """
        SELECT geometries
        FROM custom_areas
        WHERE id IN :ids AND user_id = :user_id
        """
    ).bindparams(bindparam("ids", expanding=True))

    async with get_connection_from_pool() as conn:

        def _read(sync_conn):
            result = sync_conn.execute(
                stmt, {"ids": list(ids), "user_id": user_id}
            )
            return [r[0] for r in result.fetchall()]

        rows = await conn.run_sync(_read)
    all_geoms: List[Any] = []
    for raw in rows:
        if raw is None:
            continue
        if isinstance(raw, list):
            all_geoms.extend(raw)
        else:
            all_geoms.append(raw)
    return bbox_wgs84_from_geojson_geometries(all_geoms)


async def fetch_selection_bbox(aois: list[dict]) -> dict[str, float] | None:
    if not aois:
        return None
    source = aois[0]["source"]
    if source not in SOURCE_ID_MAPPING:
        return None
    ids = _unique_preserve([str(a["src_id"]) for a in aois])
    mapping = SOURCE_ID_MAPPING[source]
    table = mapping["table"]
    id_col = mapping["id_column"]
    if source == "custom":
        user_id = structlog.contextvars.get_contextvars().get("user_id")
        if not user_id:
            logger.warning("user_id missing for custom area bbox")
            return None
        return await _fetch_bbox_custom(ids, str(user_id))
    return await _fetch_bbox_postgis(table, id_col, ids)


def build_gfw_static_layer(aois: list[dict]) -> dict[str, Any] | None:
    if not aois:
        return None
    source = aois[0]["source"]
    if source == "custom":
        return None
    if source == "gadm":
        subtype = aois[0].get("subtype") or "global"
        gadm_ids = [str(a["src_id"]) for a in aois]
        return _gfw_static_config_for_gadm(subtype, gadm_ids)
    if source in _NON_GADM_SPECS:
        return _gfw_static_config_non_gadm(
            source, [str(a["src_id"]) for a in aois]
        )
    return None


async def build_vector_layer_highlight(
    aois: list[dict],
) -> dict[str, Any]:
    """Payload for LangGraph state / frontend: bbox + optional GFW static layer filter."""
    if not aois:
        return {
            "source": "",
            "bbox_wgs84": None,
            "gfw_static_layer": None,
        }
    source = str(aois[0]["source"])
    bbox: dict[str, float] | None = None
    try:
        bbox = await fetch_selection_bbox(aois)
    except Exception:
        logger.exception("bbox_query_failed", source=source)

    gfw: dict[str, Any] | None = None
    try:
        gfw = build_gfw_static_layer(aois)
    except Exception:
        logger.exception("gfw_filter_build_failed", source=source)

    return {
        "source": source,
        "bbox_wgs84": bbox,
        "gfw_static_layer": gfw,
    }
