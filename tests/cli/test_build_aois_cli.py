"""Tests for ``build-aois``: its argument guards and the gadm name repair.

``--prune`` deletes rows, so the command rejects a combination that cannot
prune. Both guards raise before ``asyncio.run``, so those tests need no
database and no ``DatabaseManager``.

The transform itself reads the ``geometries_*`` staging tables, which the test
schema does not contain: they are bulk-loaded by GeoPandas, not declared in
``Base.metadata``. The fixtures below create a minimal one and drop it again.
Dropping matters: ``conftest.clear_tables`` only truncates the tables in
``Base.metadata``, so a leaked staging table would leak into later tests.

The seeded hierarchy is a miniature of the real GADM dirt, because the repair
rules turn on exactly that dirt: children that disagree with each other, a
parent with no children, a tie, and names GADM stored one level down.
"""

import pytest
import pytest_asyncio
from click.testing import CliRunner
from sqlalchemy import text

from src.api.cli import _build_reference_aois, _derive_gadm_name_repairs, cli
from tests.conftest import async_session_maker

# One valid square for every seeded row: the transform derives geometry, bbox
# and area from it, and none of these tests assert on those.
_SQUARE = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"

# Chunk count for the seeded builds. The real default is 16; a smaller number
# keeps the tests quick while still running the multi-pass, per-chunk-commit
# path rather than a single statement. The seeded ids deliberately hash into
# different chunks from their own children (see the cross-chunk test).
_CHUNKS = 4

_STAGING_COLUMNS = (
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


def _row(gadm_id: str, name: str, subtype: str, **columns) -> dict:
    """A staging row: ids and names as GADM ships them, others left NULL."""
    row = {col.lower(): None for col in _STAGING_COLUMNS}
    row.update(
        gadm_id=gadm_id, name=name, subtype=subtype, country="United Kingdom"
    )
    row.update({key.lower(): value for key, value in columns.items()})
    return row


async def _seed_gadm_staging(rows: list[dict]) -> None:
    """Create ``geometries_gadm`` and insert *rows*.

    Only the columns the gadm transform and the repair read are declared. The
    real table has ~90 columns from GADM's own schema; the quoted upper-case
    names mirror the casing GeoPandas preserves, which ``_resolve_column``
    depends on.
    """
    declared = ", ".join(f'"{col}" text' for col in _STAGING_COLUMNS)
    columns = ", ".join(f'"{col}"' for col in _STAGING_COLUMNS)
    values = ", ".join(f":{col.lower()}" for col in _STAGING_COLUMNS)
    async with async_session_maker() as session:
        await session.execute(text("DROP TABLE IF EXISTS geometries_gadm"))
        await session.execute(
            text(
                f"CREATE TABLE geometries_gadm ({declared},"
                " geometry geometry(MultiPolygon, 4326))"
            )
        )
        for row in rows:
            await session.execute(
                text(
                    f"INSERT INTO geometries_gadm ({columns}, geometry)"
                    f" VALUES ({values},"
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


async def _repairs() -> dict[str, str]:
    async with async_session_maker() as session:
        return await _derive_gadm_name_repairs(
            session, "geometries_gadm", "gadm_id"
        )


def _district(gadm_id: str, name_2: str, **columns) -> dict:
    """A GBR district row, with its display name composed as ingest does."""
    cols = {"GID_0": "GBR", "GID_1": "GBR.1_1", "NAME_1": "England"}
    cols.update(columns)
    cols.update({"GID_2": gadm_id, "NAME_2": name_2})
    name = f"{name_2}, {cols['NAME_1']}, United Kingdom"
    return _row(gadm_id, name, "district-county", **cols)


def _municipality(gadm_id: str, parent: str, name_2: str, name_3: str) -> dict:
    return _row(
        gadm_id,
        f"{name_3}, {name_2}, England, United Kingdom",
        "municipality",
        GID_0="GBR",
        GID_1="GBR.1_1",
        NAME_1="England",
        GID_2=parent,
        NAME_2=name_2,
        GID_3=gadm_id,
        NAME_3=name_3,
    )


# A miniature of the real hierarchy. Every group below is one rule or one
# refusal; the comments name the real row each stands in for.
_GADM_ROWS = [
    # Level 1, Rule A. England's children disagree exactly as GADM's do: most
    # say England, one says NA (never a vote), one says Wales (a real GADM
    # error). England takes 2 of the 3 named votes.
    _row("GBR", "United Kingdom", "country", GID_0="GBR"),
    _row(
        "GBR.1_1",
        "NA, United Kingdom",
        "state-province",
        GID_0="GBR",
        GID_1="GBR.1_1",
        NAME_1="NA",
    ),
    _district("GBR.1.1_1", "Barnsley"),
    _district("GBR.1.4_1", "Wakefield", NAME_1="Wales"),
    _district("GBR.1.3_1", "Sheffield", NAME_1="NA"),
    # Level 1 control: a sibling GADM named correctly.
    _row(
        "GBR.2_1",
        "Scotland, United Kingdom",
        "state-province",
        GID_0="GBR",
        GID_1="GBR.2_1",
        NAME_1="Scotland",
    ),
    # Level 1 refusal: MHL.19_1 has no children at all, so nothing to borrow.
    _row(
        "MHL.19_1",
        "NA, Marshall Islands",
        "state-province",
        GID_0="MHL",
        COUNTRY="Marshall Islands",
        GID_1="MHL.19_1",
        NAME_1="NA",
    ),
    # Level 1 refusal: the all-NA ghost row, whose children split 1-1.
    _row("NA", "NA, NA", "state-province", GID_1="NA", NAME_1="NA"),
    _row(
        "NA.1_1",
        "NA, England, United Kingdom",
        "district-county",
        GID_1="NA",
        NAME_1="England",
        GID_2="NA.1_1",
        NAME_2="NA",
    ),
    _row(
        "NA.2_1",
        "NA, Scotland, United Kingdom",
        "district-county",
        GID_1="NA",
        NAME_1="Scotland",
        GID_2="NA.2_1",
        NAME_2="NA",
    ),
    # Level 1, Rule A with a near-miss dissenter, as Ireland ships it.
    _row(
        "IRL.4_1",
        "NA, Ireland",
        "state-province",
        GID_0="IRL",
        COUNTRY="Ireland",
        GID_1="IRL.4_1",
        NAME_1="NA",
    ),
    _row(
        "IRL.4.1_1",
        "Cobh, Cork, Ireland",
        "district-county",
        GID_0="IRL",
        COUNTRY="Ireland",
        GID_1="IRL.4_1",
        NAME_1="Cork",
        GID_2="IRL.4.1_1",
        NAME_2="Cobh",
    ),
    _row(
        "IRL.4.2_1",
        "Youghal, Cork, Ireland",
        "district-county",
        GID_0="IRL",
        COUNTRY="Ireland",
        GID_1="IRL.4_1",
        NAME_1="Cork",
        GID_2="IRL.4.2_1",
        NAME_2="Youghal",
    ),
    _row(
        "IRL.4.3_1",
        "Mahon, Cork City, Ireland",
        "district-county",
        GID_0="IRL",
        COUNTRY="Ireland",
        GID_1="IRL.4_1",
        NAME_1="Cork City",
        GID_2="IRL.4.3_1",
        NAME_2="Mahon",
    ),
    # Level 2, Rule B: GADM stored Bristol's name on its only child.
    _district("GBR.1.2_1", "NA"),
    _municipality("GBR.1.2.1_1", "GBR.1.2_1", "NA", "Bristol"),
    # Level 2, Rule A: Warwickshire, named only in its children's NAME_2.
    _district("GBR.1.5_1", "NA"),
    _municipality("GBR.1.5.1_1", "GBR.1.5_1", "Warwickshire", "Nuneaton"),
    _municipality("GBR.1.5.2_1", "GBR.1.5_1", "Warwickshire", "Rugby"),
    _municipality("GBR.1.5.3_1", "GBR.1.5_1", "Warwickshire", "Warwick"),
    # Level 2 refusal: several children, none of which carries the parent name.
    _district("GBR.1.6_1", "NA"),
    _municipality("GBR.1.6.1_1", "GBR.1.6_1", "NA", "Chesterfield"),
    _municipality("GBR.1.6.2_1", "GBR.1.6_1", "NA", "Bolsover"),
    # Level 2 refusal: an only child that GADM did not name either.
    _district("GBR.1.7_1", "NA"),
    _municipality("GBR.1.7.1_1", "GBR.1.7_1", "NA", "NA"),
    # Level 2 refusal: no children.
    _district("GBR.1.8_1", "NA"),
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
async def test_rule_a_takes_the_majority_child_name(gadm_staging):
    """A broken parent adopts the name most of its named children carry.

    England wins 2 of 3 named votes: the child that says "NA" never votes, and
    the one that says "Wales" is outvoted.
    """
    repairs = await _repairs()

    assert repairs["GBR.1_1"] == "England, United Kingdom"
    assert repairs["IRL.4_1"] == "Cork, Ireland"


@pytest.mark.asyncio
async def test_rule_a_repairs_a_county_named_only_in_its_children(
    gadm_staging,
):
    """Rule A is not level-1 only: GADM shifts county names down too."""
    repairs = await _repairs()

    assert repairs["GBR.1.5_1"] == "Warwickshire, England, United Kingdom"


@pytest.mark.asyncio
async def test_rule_b_adopts_an_only_childs_name(gadm_staging):
    """A district holding one named municipality takes that name."""
    repairs = await _repairs()

    assert repairs["GBR.1.2_1"] == "Bristol, England, United Kingdom"


@pytest.mark.asyncio
async def test_rows_the_rules_cannot_reach_are_left_alone(gadm_staging):
    """Four ways a name is genuinely absent from GADM's hierarchy.

    No children, a tie between children, several children that all omit the
    parent name, and an only child that is itself unnamed. Every one keeps the
    broken name it has today rather than inventing one.
    """
    repairs = await _repairs()

    assert "MHL.19_1" not in repairs  # no children
    assert "NA" not in repairs  # ghost row: children split 1-1
    assert "GBR.1.6_1" not in repairs  # no child carries the parent name
    assert "GBR.1.7_1" not in repairs  # only child is unnamed too
    assert "GBR.2_1" not in repairs  # not broken in the first place


@pytest.mark.asyncio
async def test_gadm_build_writes_the_repaired_names(gadm_staging):
    """The rows GADM ships as "NA" reach ``aois`` under their real names."""
    await _build("gadm")

    names = await _aoi_names("gadm")
    assert names["GBR.1_1"] == "England, United Kingdom"
    assert names["IRL.4_1"] == "Cork, Ireland"


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
