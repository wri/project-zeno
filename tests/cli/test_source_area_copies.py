"""Tests for the report on custom areas that copy a source area's geometry."""

import pytest

from src.api.repositories.source_area_copy_report import (
    list_source_area_copies,
)
from tests.conftest import async_session_maker, seed_reference_aoi

AUTH = {"Authorization": "Bearer abc123"}

UNIT_SQUARE = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
}
DRAWN_SQUARE = {
    "type": "Polygon",
    "coordinates": [[[5, 5], [5, 6], [6, 6], [6, 5], [5, 5]]],
}
DEGENERATE = {
    "type": "Polygon",
    "coordinates": [[[10, 10], [10, 10], [10, 10], [10, 10]]],
}


async def create_custom_area(client, name, geometry):
    res = await client.post(
        "/api/custom_areas",
        json={"name": name, "geometries": [geometry]},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def read_report():
    async with async_session_maker() as session:
        return await list_source_area_copies(session, tolerance=0.001)


@pytest.mark.asyncio
async def test_copy_report_matches_a_saved_gadm_copy_and_ignores_a_drawn_area(
    auth_override, client
):
    auth_override("test-user-wri")
    await seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    copy_id = await create_custom_area(client, "Brazil", UNIT_SQUARE)
    await create_custom_area(client, "Farm plot", DRAWN_SQUARE)

    (copy,) = await read_report()

    assert copy["finding"] == "copy"
    assert copy["custom_area_id"] == copy_id
    assert (copy["ref_source"], copy["ref_src_id"]) == ("gadm", "BRA")
    assert copy["name_matches"] is True
    assert (copy["dashboards"], copy["subscriptions"]) == (0, 0)


@pytest.mark.asyncio
async def test_copy_report_lists_custom_areas_missing_from_the_library(
    auth_override, client
):
    auth_override("test-user-wri")
    area_id = await create_custom_area(client, "Broken", DEGENERATE)

    (row,) = await read_report()

    assert (row["finding"], row["custom_area_id"]) == (
        "not_in_library",
        area_id,
    )
