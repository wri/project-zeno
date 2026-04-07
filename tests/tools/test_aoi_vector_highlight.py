"""Unit tests for GFW vector highlight helpers (no DB)."""

from src.agent.tools.aoi_vector_highlight import (
    bbox_wgs84_from_geojson_geometries,
    build_gfw_static_layer,
    mapbox_membership_filter,
)


def test_mapbox_membership_filter_single_and_multi():
    assert mapbox_membership_filter("gid_0", ["USA"]) == [
        "==",
        ["get", "gid_0"],
        "USA",
    ]
    assert mapbox_membership_filter("sitrecid", [1, 2]) == [
        "in",
        ["get", "sitrecid"],
        ["literal", [1, 2]],
    ]


def test_bbox_from_geojson_polygon_string():
    geoms = [
        '{"type":"Polygon","coordinates":[[[0,1],[2,1],[2,3],[0,3],[0,1]]]}'
    ]
    b = bbox_wgs84_from_geojson_geometries(geoms)
    assert b == {"west": 0.0, "south": 1.0, "east": 2.0, "north": 3.0}


def test_build_gfw_static_gadm_country():
    cfg = build_gfw_static_layer(
        [
            {
                "source": "gadm",
                "subtype": "country",
                "src_id": "IDN",
                "name": "Indonesia",
            }
        ]
    )
    assert cfg is not None
    assert cfg["dataset"] == "gadm_administrative_boundaries_adm0"
    assert cfg["version"] == "v4.1"
    assert cfg["filter_property"] == "gid_0"
    assert cfg["filter"] == ["==", ["get", "gid_0"], "IDN"]


def test_build_gfw_static_kba():
    cfg = build_gfw_static_layer(
        [
            {
                "source": "kba",
                "subtype": "key-biodiversity-area",
                "src_id": "123",
                "name": "X",
            }
        ]
    )
    assert cfg is not None
    assert cfg["dataset"] == "birdlife_key_biodiversity_areas"
    assert cfg["filter"] == ["==", ["get", "sitrecid"], 123]


def test_build_gfw_custom_none():
    assert (
        build_gfw_static_layer(
            [
                {
                    "source": "custom",
                    "subtype": "custom-area",
                    "src_id": "00000000-0000-0000-0000-000000000001",
                    "name": "A",
                }
            ]
        )
        is None
    )
