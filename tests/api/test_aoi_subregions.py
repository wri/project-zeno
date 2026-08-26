"""Tests for subregion expansion over the unified ``aois`` table.

``query_subregion_database`` finds the children of a selected AOI in two ways. For
GADM it matches a prefix of the id. For every other source it tests a spatial
overlap. These tests cover both ways against the real table. The existing pick_aoi
tests replace this function with a stub.

These tests use one geometry layout, inside a 0..40 box of longitude and latitude:

    parent  BRA        (0 0) .. (20 20)   also the spatial parent
    child   BRA.1_1    (0 0) .. (10 10)   inside
    child   BRA.2_1   (10 0) .. (20 10)   inside
    other   ARG.1_1   (30 0) .. (40 10)   outside, in another country
    touching           (20 0) .. (30 10)  shares only the edge at x=20
"""

import pytest
from sqlalchemy import text

from src.agent.subagents.pick_aoi.tool import query_subregion_database
from tests.conftest import async_session_maker, seed_reference_aoi


def _box(x0, y0, x1, y1):
    return f"POLYGON(({x0} {y0}, {x0} {y1}, {x1} {y1}, {x1} {y0}, {x0} {y0}))"


async def _seed_gadm_family():
    await seed_reference_aoi(
        "gadm", "BRA", "Brazil", "country", geometry_wkt=_box(0, 0, 20, 20)
    )
    await seed_reference_aoi(
        "gadm",
        "BRA.1_1",
        "Acre",
        "state-province",
        geometry_wkt=_box(0, 0, 10, 10),
    )
    await seed_reference_aoi(
        "gadm",
        "BRA.2_1",
        "Bahia",
        "state-province",
        geometry_wkt=_box(10, 0, 20, 10),
    )
    await seed_reference_aoi(
        "gadm",
        "ARG.1_1",
        "Salta",
        "state-province",
        geometry_wkt=_box(30, 0, 40, 10),
    )


# ---------------------------------------------------------------------------
# GADM containment: a prefix match on the id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gadm_children_are_scoped_to_the_parent_id():
    await _seed_gadm_family()

    df = await query_subregion_database("state", "gadm", "BRA")

    assert sorted(df["src_id"]) == ["BRA.1_1", "BRA.2_1"]
    assert set(df["source"]) == {"gadm"}
    assert set(df["subtype"]) == {"state-province"}


@pytest.mark.asyncio
async def test_gadm_parent_version_suffix_is_ignored():
    """`BRA.1_1` must expand to `BRA.1.x_1`. A literal match is wrong."""
    await seed_reference_aoi(
        "gadm",
        "BRA.1_1",
        "Acre",
        "state-province",
        geometry_wkt=_box(0, 0, 10, 10),
    )
    await seed_reference_aoi(
        "gadm",
        "BRA.1.1_1",
        "Rio Branco",
        "district-county",
        geometry_wkt=_box(0, 0, 5, 5),
    )

    df = await query_subregion_database("district", "gadm", "BRA.1_1")

    assert list(df["src_id"]) == ["BRA.1.1_1"]


@pytest.mark.asyncio
async def test_gadm_expansion_emits_the_source_id_column():
    """The frontend reads the `gadm_id` column from the extras of AOIIndex."""
    await _seed_gadm_family()

    df = await query_subregion_database("state", "gadm", "BRA")

    assert "gadm_id" in df.columns
    assert list(df["gadm_id"]) == list(df["src_id"])


@pytest.mark.asyncio
async def test_gadm_expansion_returns_precomputed_bbox():
    await seed_reference_aoi(
        "gadm", "BRA", "Brazil", "country", geometry_wkt=_box(0, 0, 20, 20)
    )
    await seed_reference_aoi(
        "gadm",
        "BRA.1_1",
        "Acre",
        "state-province",
        geometry_wkt=_box(0, 0, 10, 10),
        bbox=(1.5, 2.5, 3.5, 4.5),
    )

    df = await query_subregion_database("state", "gadm", "BRA")

    assert list(df["bbox"]) == [[1.5, 2.5, 3.5, 4.5]]


@pytest.mark.asyncio
async def test_gadm_expansion_falls_back_to_world_bbox():
    await seed_reference_aoi(
        "gadm", "BRA", "Brazil", "country", geometry_wkt=_box(0, 0, 20, 20)
    )
    await seed_reference_aoi(
        "gadm",
        "BRA.1_1",
        "Acre",
        "state-province",
        geometry_wkt=_box(0, 0, 10, 10),
        bbox=None,
    )

    df = await query_subregion_database("state", "gadm", "BRA")

    assert list(df["bbox"]) == [[-180.0, -90.0, 180.0, 90.0]]


@pytest.mark.asyncio
async def test_missing_parent_returns_no_rows():
    """An empty parent CTE gives an empty cross join, and therefore no rows."""
    await _seed_gadm_family()

    df = await query_subregion_database("state", "gadm", "NOPE")

    assert df.empty


@pytest.mark.asyncio
async def test_non_gadm_parent_of_gadm_subregion_is_unfiltered():
    """A non-GADM parent gets no containment test, only the disputed exclusion.

    The query returns every admin unit of the subtype worldwide, and
    check_aoi_selection then rejects the result as too many subregions. This test
    fixes the current behaviour. The behaviour is a known defect.
    """
    await _seed_gadm_family()
    await seed_reference_aoi(
        "gadm",
        "Z01.1_1",
        "Disputed State",
        "state-province",
        geometry_wkt=_box(0, 0, 5, 5),
        is_disputed=True,
    )
    await seed_reference_aoi(
        "wdpa",
        "P1",
        "Some Park",
        "protected-area",
        geometry_wkt=_box(0, 0, 5, 5),
    )

    df = await query_subregion_database("state", "wdpa", "P1")

    # ARG.1_1 is far from the park, but the query returns it. It excludes only
    # the disputed row.
    assert sorted(df["src_id"]) == ["ARG.1_1", "BRA.1_1", "BRA.2_1"]


# ---------------------------------------------------------------------------
# Spatial containment: kba, wdpa and landmark subregions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spatial_expansion_selects_overlapping_children():
    await seed_reference_aoi(
        "gadm", "BRA", "Brazil", "country", geometry_wkt=_box(0, 0, 20, 20)
    )
    await seed_reference_aoi(
        "wdpa",
        "P1",
        "Inside Park",
        "protected-area",
        geometry_wkt=_box(0, 0, 10, 10),
    )
    await seed_reference_aoi(
        "wdpa",
        "P2",
        "Outside Park",
        "protected-area",
        geometry_wkt=_box(30, 0, 40, 10),
    )

    df = await query_subregion_database("wdpa", "gadm", "BRA")

    assert list(df["src_id"]) == ["P1"]
    assert "wdpa_pid" in df.columns


@pytest.mark.asyncio
async def test_spatial_expansion_excludes_border_only_touch():
    """The query excludes ST_Touches. A neighbour that shares only an edge is
    not inside the parent."""
    await seed_reference_aoi(
        "gadm", "BRA", "Brazil", "country", geometry_wkt=_box(0, 0, 20, 20)
    )
    await seed_reference_aoi(
        "kba",
        "1",
        "Edge KBA",
        "key-biodiversity-area",
        geometry_wkt=_box(20, 0, 30, 10),
    )

    df = await query_subregion_database("kba", "gadm", "BRA")

    assert df.empty


@pytest.mark.asyncio
async def test_spatial_expansion_from_a_custom_parent():
    """A custom parent now works. It raised an error before, because
    custom_areas holds no geometry column.

    Both sides of the join are now in `aois`, so a custom area can expand into
    the reference AOIs that it covers. This test writes the custom row directly
    into `aois`, which is the projection that the mirror writes. It does not use
    the CRUD endpoint, because only the projection is under test.
    """
    await seed_reference_aoi(
        "custom",
        "11111111-1111-1111-1111-111111111111",
        "Drawn Area",
        "custom-area",
        geometry_wkt=_box(0, 0, 20, 20),
    )
    await seed_reference_aoi(
        "landmark",
        "L1",
        "Inside Territory",
        "indigenous-and-community-land",
        geometry_wkt=_box(0, 0, 10, 10),
    )

    df = await query_subregion_database(
        "landmark", "custom", "11111111-1111-1111-1111-111111111111"
    )

    assert list(df["src_id"]) == ["L1"]
    assert "landmark_id" in df.columns


@pytest.mark.asyncio
async def test_kba_src_ids_come_back_as_text():
    """sitrecid was numeric before unification. `aois` stores every id as text.

    Search already returns a KBA id as text, so the two paths now agree.
    """
    await seed_reference_aoi(
        "gadm", "BRA", "Brazil", "country", geometry_wkt=_box(0, 0, 20, 20)
    )
    await seed_reference_aoi(
        "kba",
        "16595",
        "Some KBA",
        "key-biodiversity-area",
        geometry_wkt=_box(0, 0, 10, 10),
    )

    df = await query_subregion_database("kba", "gadm", "BRA")

    assert list(df["src_id"]) == ["16595"]
    assert list(df["sitrecid"]) == ["16595"]


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_subregion_raises():
    with pytest.raises(ValueError, match="does not match"):
        await query_subregion_database("continent", "gadm", "BRA")


@pytest.mark.asyncio
async def test_deprecated_rows_are_excluded():
    await _seed_gadm_family()
    await seed_reference_aoi(
        "gadm",
        "BRA.3_1",
        "Old Bahia",
        "state-province",
        geometry_wkt=_box(10, 0, 20, 10),
    )
    async with async_session_maker() as session:
        await session.execute(
            text(
                "UPDATE aois SET is_deprecated = true "
                "WHERE source = 'gadm' AND source_id = 'BRA.3_1'"
            )
        )
        await session.commit()

    df = await query_subregion_database("state", "gadm", "BRA")

    assert sorted(df["src_id"]) == ["BRA.1_1", "BRA.2_1"]
