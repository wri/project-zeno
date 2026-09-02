"""Tests for ``build-aois``: its argument guards and the gadm name repair.

``--prune`` deletes rows, so the command rejects a combination that cannot
prune. Both guards raise before ``asyncio.run``, so those tests need no
database and no ``DatabaseManager``.

The transform itself reads the ``geometries_*`` staging tables, which the test
schema does not contain: they are bulk-loaded by GeoPandas, not declared in
``Base.metadata``. ``_staging_table`` creates a minimal one and drops it again.
Dropping matters: ``conftest.clear_tables`` only truncates the tables in
``Base.metadata``, so a leaked staging table would leak into later tests.

The seeded hierarchy is a miniature of the real GADM dirt, because the repair
rules turn on exactly that dirt: children that disagree with each other, a
parent with no children, a tie, and names GADM stored one level down.
"""

from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from click.testing import CliRunner
from sqlalchemy import text

from src.api.cli import _build_reference_aois, _derive_gadm_name_repairs, cli
from src.shared.geocoding_helpers import (
    AOI_SOURCE_ID_COLUMNS,
    GADM_LEVELS,
    SOURCE_STAGING_TABLES,
)
from tests.conftest import UNIT_SQUARE_WKT, async_session_maker

# Chunk count for the seeded builds. The real default is 16; a smaller number
# keeps the tests quick while still running the multi-pass, per-chunk-commit
# path rather than a single statement. The seeded ids deliberately hash into
# different chunks from their own children (see the cross-chunk test).
_CHUNKS = 4

# GADM's own column names, spelled as GADM ships them: pinning that file format
# is the point of the fixture, so these stay literal.
_GADM_COLUMNS = (
    "GID_0",
    "COUNTRY",
    "GID_1",
    "NAME_1",
    "GID_2",
    "NAME_2",
    "GID_3",
    "NAME_3",
    "gadm_id",
    "name",
    "subtype",
)

_GADM_SUBTYPES = list(GADM_LEVELS)
_GADM_LEVEL_COLUMNS = list(GADM_LEVELS.values())


@asynccontextmanager
async def _staging_table(source: str, columns: tuple[str, ...], rows: list):
    """Create ``geometries_<source>``, seed *rows*, and drop it again.

    Only the columns the transform and the repair read are declared, all text.
    The real tables have ~90 columns from the source file's own schema. The
    quoted names preserve the casing GeoPandas keeps, which ``_resolve_column``
    and the repair's column check both depend on. Every row gets the same
    square: none of these tests assert on geometry, bbox or area.
    """
    table = SOURCE_STAGING_TABLES[source]
    declared = ", ".join(f'"{col}" text' for col in columns)
    names = ", ".join(f'"{col}"' for col in columns)
    binds = ", ".join(f":{col}" for col in columns)
    try:
        async with async_session_maker() as session:
            await session.execute(text(f"DROP TABLE IF EXISTS {table}"))
            await session.execute(
                text(
                    f"CREATE TABLE {table} ({declared},"
                    " geometry geometry(MultiPolygon, 4326))"
                )
            )
            await session.execute(
                text(
                    f"INSERT INTO {table} ({names}, geometry)"
                    f" VALUES ({binds},"
                    " ST_Multi(ST_GeomFromText(:geom, 4326)))"
                ),
                [{"geom": UNIT_SQUARE_WKT, **row} for row in rows],
            )
            await session.commit()
        yield
    finally:
        async with async_session_maker() as session:
            await session.execute(text(f"DROP TABLE IF EXISTS {table}"))
            await session.commit()


def _gadm(gadm_id: str, *path: str, **columns) -> dict:
    """The staging row GADM ships for the unit at *path*, country first.

    ``_gadm("IRL.4.3_1", "Ireland", "Cork City", "Mahon")`` is Mahon's row.
    Everything follows from the id and the path, as it does in GADM's own
    files: the subtype from the path's depth, each ``NAME_n`` from the path,
    the display name from the path reversed (how ingest composes it), and each
    ancestor's ``GID_n`` by dropping trailing segments off the id. That last
    rule is what reproduces GADM's malformed "NA" rows, whose ids are one
    segment short and so leave ``GID_0`` null.

    *columns* overrides a single column for a row GADM ships inconsistently.
    """
    level = len(path) - 1
    parts = gadm_id.removesuffix("_1").split(".")

    row: dict = {col: None for col in _GADM_COLUMNS}
    row["gadm_id"] = gadm_id
    row["name"] = ", ".join(reversed(path))
    row["subtype"] = _GADM_SUBTYPES[level]
    for depth, ancestor in enumerate(path):
        row[_GADM_LEVEL_COLUMNS[depth]["name_col"]] = ancestor

    row[_GADM_LEVEL_COLUMNS[level]["col_name"]] = gadm_id
    for depth in range(level - 1, -1, -1):
        head = parts[: len(parts) - (level - depth)]
        if head:
            suffix = "_1" if len(head) > 1 else ""
            row[_GADM_LEVEL_COLUMNS[depth]["col_name"]] = (
                ".".join(head) + suffix
            )

    row.update(columns)
    return row


_UK = "United Kingdom"

# A miniature of the real hierarchy. Every group below is one rule or one
# refusal; the comments name the real row each stands in for.
_GADM_ROWS = [
    # Level 1, Rule A. England's children disagree exactly as GADM's do: most
    # say England, one says NA (never a vote), one says Wales (a real GADM
    # error). England takes 2 of the 3 named votes.
    _gadm("GBR", _UK),
    _gadm("GBR.1_1", _UK, "NA"),
    _gadm("GBR.1.1_1", _UK, "England", "Barnsley"),
    _gadm("GBR.1.4_1", _UK, "Wales", "Wakefield"),
    _gadm("GBR.1.3_1", _UK, "NA", "Sheffield"),
    # Level 1 control: a sibling GADM named correctly.
    _gadm("GBR.2_1", _UK, "Scotland"),
    # Level 1 refusal: MHL.19_1 has no children at all, so nothing to borrow.
    _gadm("MHL.19_1", "Marshall Islands", "NA"),
    # Level 1 refusal: the all-NA ghost row, whose children split 1-1. GADM's
    # own carries a country name that its display name does not, hence the
    # override; the null GID_0 falls out of the short id.
    _gadm("NA", "NA", "NA", COUNTRY=_UK),
    _gadm("NA.1_1", _UK, "England", "NA"),
    _gadm("NA.2_1", _UK, "Scotland", "NA"),
    # Level 1, Rule A with a near-miss dissenter, as Ireland ships it.
    _gadm("IRL.4_1", "Ireland", "NA"),
    _gadm("IRL.4.1_1", "Ireland", "Cork", "Cobh"),
    _gadm("IRL.4.2_1", "Ireland", "Cork", "Youghal"),
    _gadm("IRL.4.3_1", "Ireland", "Cork City", "Mahon"),
    # Level 2, Rule B: GADM stored Bristol's name on its only child.
    _gadm("GBR.1.2_1", _UK, "England", "NA"),
    _gadm("GBR.1.2.1_1", _UK, "England", "NA", "Bristol"),
    # Level 2, Rule A: Warwickshire, named only in its children's NAME_2.
    _gadm("GBR.1.5_1", _UK, "England", "NA"),
    _gadm("GBR.1.5.1_1", _UK, "England", "Warwickshire", "Nuneaton"),
    _gadm("GBR.1.5.2_1", _UK, "England", "Warwickshire", "Rugby"),
    _gadm("GBR.1.5.3_1", _UK, "England", "Warwickshire", "Warwick"),
    # Level 2 refusal: several children, none of which carries the parent name.
    _gadm("GBR.1.6_1", _UK, "England", "NA"),
    _gadm("GBR.1.6.1_1", _UK, "England", "NA", "Chesterfield"),
    _gadm("GBR.1.6.2_1", _UK, "England", "NA", "Bolsover"),
    # Level 2 refusal: an only child that GADM did not name either.
    _gadm("GBR.1.7_1", _UK, "England", "NA"),
    _gadm("GBR.1.7.1_1", _UK, "England", "NA", "NA"),
    # Level 2 refusal: no children.
    _gadm("GBR.1.8_1", _UK, "England", "NA"),
]


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


async def _repairs() -> dict[str, str]:
    async with async_session_maker() as session:
        return await _derive_gadm_name_repairs(
            session,
            SOURCE_STAGING_TABLES["gadm"],
            AOI_SOURCE_ID_COLUMNS["gadm"],
        )


@pytest_asyncio.fixture(scope="module")
async def gadm_staging():
    """Seed ``geometries_gadm`` once for the module.

    Module-scoped because nothing under test writes to staging: the repair is
    read-only and ``build-aois`` only writes ``aois``, which the autouse
    ``clear_tables`` still truncates between tests.
    """
    async with _staging_table("gadm", _GADM_COLUMNS, _GADM_ROWS):
        yield


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


# (source id, repaired name or None if the rules must refuse, why).
_DERIVATION_CASES = [
    (
        "GBR.1_1",
        "England, United Kingdom",
        "Rule A: England wins 2 of 3 named votes -- the child saying 'NA'"
        " never votes, and the one saying 'Wales' is outvoted",
    ),
    (
        "IRL.4_1",
        "Cork, Ireland",
        "Rule A holds against a near-miss dissenter ('Cork City')",
    ),
    (
        "GBR.1.5_1",
        "Warwickshire, England, United Kingdom",
        "Rule A is not level-1 only: GADM shifts county names down too",
    ),
    (
        "GBR.1.2_1",
        "Bristol, England, United Kingdom",
        "Rule B: a district holding one named municipality takes that name",
    ),
    ("MHL.19_1", None, "refused: no children, so no name to borrow"),
    ("NA", None, "refused: the ghost row's two children split 1-1"),
    ("GBR.1.6_1", None, "refused: no child carries the parent's name"),
    ("GBR.1.7_1", None, "refused: the only child is unnamed too"),
    ("GBR.2_1", None, "not broken in the first place"),
]


@pytest.mark.asyncio
async def test_derives_a_name_only_where_gadm_supplies_one(gadm_staging):
    """Both rules and every refusal, against one seeding of the hierarchy.

    A loop rather than ``parametrize``: the map is identical for every case, so
    parametrizing at function scope would only re-derive it per assertion.
    """
    repairs = await _repairs()

    for source_id, expected, why in _DERIVATION_CASES:
        assert repairs.get(source_id) == expected, why


@pytest.mark.asyncio
async def test_repair_survives_the_chunked_insert(gadm_staging):
    """The repair is derived once, so chunk boundaries cannot split a family.

    The INSERT is hash-partitioned by source id, so a parent and its children
    routinely land in different passes. This test first asserts the seeded ids
    really do straddle a boundary, then that the repaired names still arrive.
    """
    id_col = AOI_SOURCE_ID_COLUMNS["gadm"]
    async with async_session_maker() as session:
        buckets = await session.execute(
            text(
                f"SELECT {id_col},"
                f" abs(hashtext({id_col})::bigint) % :n AS chunk"
                f" FROM {SOURCE_STAGING_TABLES['gadm']}"
                f" WHERE {id_col} IN ('GBR.1_1', 'GBR.1.1_1', 'GBR.1.2_1',"
                " 'GBR.1.2.1_1')"
            ),
            {"n": _CHUNKS},
        )
        chunk = dict(buckets.all())

    assert (
        chunk["GBR.1_1"] != chunk["GBR.1.1_1"]
    ), "seed ids stopped straddling"
    assert chunk["GBR.1.2_1"] != chunk["GBR.1.2.1_1"]

    await _build("gadm")

    names = await _aoi_names("gadm")
    assert names["GBR.1_1"] == "England, United Kingdom"
    assert names["GBR.1.2_1"] == "Bristol, England, United Kingdom"
    assert names["IRL.4_1"] == "Cork, Ireland"
    assert names["GBR.1.5_1"] == "Warwickshire, England, United Kingdom"


@pytest.mark.asyncio
async def test_gadm_build_leaves_unrepairable_names_alone(gadm_staging):
    """An irreparable name stays broken on purpose.

    Unfindable junk today, unfindable junk after: search hygiene for those rows
    is a separate decision (SPEC-PR7 rule C), not a name to invent here.
    """
    await _build("gadm")

    names = await _aoi_names("gadm")
    assert names["GBR.2_1"] == "Scotland, United Kingdom"
    assert names["MHL.19_1"] == "NA, Marshall Islands"
    assert names["GBR.1.6_1"] == "NA, England, United Kingdom"
    assert names["GBR.1.7_1"] == "NA, England, United Kingdom"
    assert names["GBR.1.8_1"] == "NA, England, United Kingdom"


@pytest.mark.asyncio
async def test_a_repaired_parent_leaves_its_childs_middle_segment_broken(
    gadm_staging,
):
    """Pinned gap, not a bug to fix here.

    The repair replaces one *leading* segment, so Bristol's district row is
    fixed while the municipality under it still reads its parent as "NA" in
    the middle of its own name. Recomposing display names from repaired
    ancestors is SPEC-PR8's design and the durable fix; this asserts today's
    outcome so that change shows up as a deliberate one.
    """
    await _build("gadm")

    names = await _aoi_names("gadm")
    assert names["GBR.1.2_1"] == "Bristol, England, United Kingdom"
    assert names["GBR.1.2.1_1"] == "Bristol, NA, England, United Kingdom"


@pytest.mark.asyncio
async def test_gadm_rebuild_is_idempotent(gadm_staging):
    """A second build upserts the same rows to the same names.

    This is the ``ON CONFLICT ... DO UPDATE`` path every environment takes,
    because build-aois is re-run rather than reset. The repair is re-derived
    from staging on each run, which is what makes a re-ingest self-healing.
    """
    first = await _build("gadm")
    before = await _aoi_names("gadm")

    second = await _build("gadm")
    after = await _aoi_names("gadm")

    assert first == second == len(_GADM_ROWS)
    assert before == after
    assert len(after) == len(_GADM_ROWS)


@pytest.mark.asyncio
async def test_repair_does_not_touch_other_sources():
    """The repair reads GADM's hierarchy, so it applies to gadm only.

    Seeding a kba row under a gadm id that the rules do repair is the sharpest
    form of the question: a source-blind repair would rename it.
    """
    columns = ("ISO3", AOI_SOURCE_ID_COLUMNS["kba"], "name", "subtype")
    row = {
        "ISO3": "GBR",
        AOI_SOURCE_ID_COLUMNS["kba"]: "GBR.1_1",
        "name": "NA, United Kingdom",
        "subtype": "key-biodiversity-area",
    }

    async with _staging_table("kba", columns, [row]):
        await _build("kba")

        names = await _aoi_names("kba")
        assert names == {"GBR.1_1": "NA, United Kingdom"}
