"""Tests for ``build-aois``: its argument guards and the gadm name patch.

``--prune`` deletes rows, so the command rejects a combination that cannot
prune. Both guards raise before ``asyncio.run``, so those tests need no
database and no ``DatabaseManager``.

The transform itself reads the ``geometries_*`` staging tables, which the test
schema does not contain: they are bulk-loaded by GeoPandas, not declared in
``Base.metadata``. The fixtures below create a minimal one and drop it again.
Dropping matters: ``conftest.clear_tables`` only truncates the tables in
``Base.metadata``, so a leaked staging table would leak into later tests.
"""

import pytest
import pytest_asyncio
from click.testing import CliRunner
from sqlalchemy import text

from src.api.cli import _build_reference_aois, cli
from tests.conftest import async_session_maker

# One valid square for every seeded row: the transform derives geometry, bbox
# and area from it, and none of these tests assert on those.
_SQUARE = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"

# Chunk count for the seeded builds. The real default is 16; a smaller number
# keeps the tests quick while still running the multi-pass, per-chunk-commit
# path rather than a single statement.
_CHUNKS = 4


async def _seed_gadm_staging(rows: list[dict]) -> None:
    """Create ``geometries_gadm`` and insert *rows*.

    Only the columns the gadm transform reads are declared. The real table has
    ~90 columns from GADM's own schema; the quoted upper-case names mirror the
    casing GeoPandas preserves, which ``_resolve_column`` depends on.
    """
    async with async_session_maker() as session:
        await session.execute(text("DROP TABLE IF EXISTS geometries_gadm"))
        await session.execute(
            text(
                "CREATE TABLE geometries_gadm ("
                ' "GID_0" text,'
                ' "COUNTRY" text,'
                ' "NAME_1" text,'
                " gadm_id text,"
                " name text,"
                " subtype text,"
                " geometry geometry(MultiPolygon, 4326))"
            )
        )
        for row in rows:
            await session.execute(
                text(
                    "INSERT INTO geometries_gadm "
                    '("GID_0", "COUNTRY", "NAME_1", gadm_id, name, subtype,'
                    " geometry) VALUES (:iso3, :country, :name_1, :gadm_id,"
                    " :name, :subtype,"
                    " ST_Multi(ST_GeomFromText(:geom, 4326)))"
                ),
                {"geom": _SQUARE, **row},
            )
        await session.commit()


async def _aoi_names(source: str) -> dict[str, str]:
    """Return ``{source_id: name}`` for one source's rows in ``aois``."""
    async with async_session_maker() as session:
        result = await session.execute(
            text("SELECT source_id, name FROM aois WHERE source = :source"),
            {"source": source},
        )
        return {row[0]: row[1] for row in result.all()}


async def _build(source: str) -> int:
    async with async_session_maker() as session:
        return await _build_reference_aois(
            session, source, nchunks=_CHUNKS, dry_run=False
        )


def _state(gadm_id: str, name: str, name_1: str, iso3: str, country: str):
    return {
        "gadm_id": gadm_id,
        "name": name,
        "name_1": name_1,
        "subtype": "state-province",
        "iso3": iso3,
        "country": country,
    }


# The three patched rows as GADM actually ships them, plus two controls: a
# named sibling, and the level-1 row that has no child rows to derive a name
# from and so must keep its broken name.
_GADM_ROWS = [
    _state("GBR.1_1", "NA, United Kingdom", "NA", "GBR", "United Kingdom"),
    _state(
        "GBR.2_1",
        "Scotland, United Kingdom",
        "Scotland",
        "GBR",
        "United Kingdom",
    ),
    _state("IRL.4_1", "NA, Ireland", "NA", "IRL", "Ireland"),
    _state(
        "MHL.19_1",
        "NA, Marshall Islands",
        "NA",
        "MHL",
        "Marshall Islands",
    ),
]


@pytest_asyncio.fixture
async def gadm_staging():
    """Seed ``geometries_gadm``, and drop it however the test ends."""
    await _seed_gadm_staging(_GADM_ROWS)
    yield
    async with async_session_maker() as session:
        await session.execute(text("DROP TABLE IF EXISTS geometries_gadm"))
        await session.commit()


def test_prune_needs_the_custom_source():
    result = CliRunner().invoke(
        cli, ["build-aois", "--source", "gadm", "--prune"]
    )

    assert result.exit_code == 2
    assert "--prune needs the custom source" in result.output


def test_prune_rejects_inspect():
    result = CliRunner().invoke(cli, ["build-aois", "--prune", "--inspect"])

    assert result.exit_code == 2
    assert "--prune cannot run with --inspect" in result.output


@pytest.mark.asyncio
async def test_gadm_build_patches_the_broken_names(gadm_staging):
    """The rows GADM ships as "NA" reach ``aois`` under their real names."""
    await _build("gadm")

    names = await _aoi_names("gadm")
    assert names["GBR.1_1"] == "England, United Kingdom"
    assert names["IRL.4_1"] == "Cork, Ireland"


@pytest.mark.asyncio
async def test_gadm_build_leaves_unpatched_names_alone(gadm_staging):
    """A patch entry is the only thing that changes a name.

    ``MHL.19_1`` is the level-1 row whose name GADM's own hierarchy cannot
    recover, so it stays broken on purpose: unfindable junk today, unfindable
    junk after, which is the safe state.
    """
    await _build("gadm")

    names = await _aoi_names("gadm")
    assert names["GBR.2_1"] == "Scotland, United Kingdom"
    assert names["MHL.19_1"] == "NA, Marshall Islands"


@pytest.mark.asyncio
async def test_gadm_rebuild_is_idempotent(gadm_staging):
    """A second build upserts the same rows to the same names.

    This is the ``ON CONFLICT ... DO UPDATE`` path every environment takes,
    because build-aois is re-run rather than reset.
    """
    first = await _build("gadm")
    before = await _aoi_names("gadm")

    second = await _build("gadm")
    after = await _aoi_names("gadm")

    assert first == second == len(_GADM_ROWS)
    assert before == after
    assert len(after) == len(_GADM_ROWS)


@pytest.mark.asyncio
async def test_patch_does_not_touch_other_sources():
    """The patch is keyed on gadm ids, and applies to the gadm source only.

    Seeding a kba row under a patched gadm id is the sharpest form of the
    question: a source-blind patch would rename it.
    """
    async with async_session_maker() as session:
        await session.execute(text("DROP TABLE IF EXISTS geometries_kba"))
        await session.execute(
            text(
                "CREATE TABLE geometries_kba ("
                ' "ISO3" text, sitrecid text, name text, subtype text,'
                " geometry geometry(MultiPolygon, 4326))"
            )
        )
        await session.execute(
            text(
                "INSERT INTO geometries_kba VALUES ('GBR', 'GBR.1_1',"
                " 'NA, United Kingdom', 'key-biodiversity-area',"
                " ST_Multi(ST_GeomFromText(:geom, 4326)))"
            ),
            {"geom": _SQUARE},
        )
        await session.commit()

    try:
        await _build("kba")
        names = await _aoi_names("kba")
        assert names == {"GBR.1_1": "NA, United Kingdom"}
    finally:
        async with async_session_maker() as session:
            await session.execute(text("DROP TABLE IF EXISTS geometries_kba"))
            await session.commit()
