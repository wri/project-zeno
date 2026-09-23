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

import re
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from click.testing import CliRunner
from sqlalchemy import text

from src.api.cli import (
    _build_aoi_names,
    _build_reference_aois,
    _derive_gadm_name_repairs,
    _rebuild_search_tokens,
    cli,
)
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
    "VARNAME_1",
    "NL_NAME_1",
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
    # Level 1 control: a sibling GADM named correctly. It also carries the
    # two optional name columns as GADM ships them: pipe-separated variants
    # and a native-script name.
    _gadm(
        "GBR.2_1", _UK, "Scotland", VARNAME_1="Alba|Scotia", NL_NAME_1="Alba"
    ),
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
    # Context shapes: GADM restates a unit's name down the hierarchy, and a
    # segment can end with the text of the next one ("Île-de-France, France").
    _gadm("PRT.12_1", "Portugal", "Lisboa"),
    _gadm("PRT.12.7_1", "Portugal", "Lisboa", "Lisboa"),
    _gadm("PRT.12.7.1_1", "Portugal", "Lisboa", "Lisboa", "Alvalade"),
    _gadm("FRA.8_1", "France", "Île-de-France"),
    _gadm("FRA.8.3_1", "France", "Île-de-France", "Paris"),
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
    """A second build over unchanged data writes nothing and changes nothing.

    This is the ``ON CONFLICT ... DO UPDATE`` path every environment takes,
    because build-aois is re-run rather than reset. A row whose columns all
    match is left alone, so the rebuild neither bloats the heap nor clears
    the visibility map the search's index-only scans depend on.
    """
    first = await _build("gadm")
    before = await _aoi_names("gadm")

    second = await _build("gadm")
    after = await _aoi_names("gadm")

    assert first == len(_GADM_ROWS)
    assert second == 0
    assert before == after
    assert len(after) == len(_GADM_ROWS)


async def _search_columns(source: str) -> dict[str, dict]:
    """Return ``{source_id: {leaf, leaf_norm, context, tsv, ntsv}}``."""
    async with async_session_maker() as session:
        result = await session.execute(
            text(
                "SELECT source_id, leaf, leaf_norm, context, "
                "search_tsv::text AS tsv, name_tsv::text AS ntsv "
                "FROM aois WHERE source = :source"
            ),
            {"source": source},
        )
        return {row[0]: dict(row._mapping) for row in result.all()}


async def _names(source: str) -> dict[str, set[tuple[str, str]]]:
    """Return ``{source_id: {(kind, name_norm)}}`` for a source."""
    async with async_session_maker() as session:
        result = await session.execute(
            text(
                "SELECT a.source_id, n.kind, n.name_norm "
                "FROM aoi_names n JOIN aois a ON a.id = n.aoi_id "
                "WHERE a.source = :source"
            ),
            {"source": source},
        )
        out: dict[str, set[tuple[str, str]]] = {}
        for source_id, kind, norm in result.all():
            out.setdefault(source_id, set()).add((kind, norm))
        return out


async def _build_names(source: str) -> int:
    async with async_session_maker() as session:
        n = await _build_aoi_names(session, source)
        await session.commit()
        return n


@pytest.mark.asyncio
async def test_gadm_build_fills_the_search_columns(gadm_staging):
    """Leaf, context and tsvector come from GADM's own level columns.

    The leaf is the unit's own NAME_n, repaired where the repair applies, and
    NULL where GADM has no name at all: a no-data marker must not become a
    searchable name. The context is the parents, country last.
    """
    await _build("gadm")
    cols = await _search_columns("gadm")

    barnsley = cols["GBR.1.1_1"]
    assert barnsley["leaf"] == "Barnsley"
    assert barnsley["leaf_norm"] == "barnsley"
    assert barnsley["context"] == "England, United Kingdom"
    assert "'barnsley':1A" in barnsley["tsv"]
    assert "'england':2B" in barnsley["tsv"]
    # The name vector carries the names only: a parent's name would match
    # every row beneath it.
    assert barnsley["ntsv"] == "'barnsley':1A"

    # The repaired leading segment is the leaf.
    assert cols["GBR.1_1"]["leaf"] == "England"
    assert cols["GBR.1_1"]["context"] == "United Kingdom"
    # A country has no context.
    assert cols["GBR"]["leaf"] == "United Kingdom"
    assert cols["GBR"]["context"] is None
    # Irreparable "NA" gives no leaf; the context still carries the parents.
    assert cols["MHL.19_1"]["leaf"] is None
    assert cols["MHL.19_1"]["leaf_norm"] is None
    assert cols["MHL.19_1"]["context"] == "Marshall Islands"
    # A "NA" parent drops out of the context rather than becoming a token.
    assert cols["GBR.1.7.1_1"]["context"] == "England, United Kingdom"
    # A parent restated down the hierarchy appears once in the context; a
    # segment that merely ends with the next one's text is not a repeat.
    assert cols["PRT.12.7.1_1"]["context"] == "Lisboa, Portugal"
    assert cols["PRT.12.7_1"]["leaf"] == "Lisboa"
    assert cols["PRT.12.7_1"]["context"] == "Lisboa, Portugal"
    assert cols["FRA.8.3_1"]["context"] == "Île-de-France, France"
    # The hyphenated parent yields several tokens, so check weight, not position.
    assert re.search(r"'france':[\d,]*\dB", cols["FRA.8.3_1"]["tsv"])


@pytest.mark.asyncio
async def test_gadm_names_hold_variants_and_native_spellings(gadm_staging):
    """The leaf lives on aois; aoi_names holds the other spellings only."""
    await _build("gadm")
    inserted = await _build_names("gadm")
    names = await _names("gadm")

    # One row per spelling: "Alba" is both a variant and the native name.
    assert {norm for _, norm in names["GBR.2_1"]} == {"alba", "scotia"}
    # A unit with no alternate spelling has no rows at all.
    assert "GBR.1.1_1" not in names
    assert "GBR.1_1" not in names
    assert "MHL.19_1" not in names
    # The variants are also tokens of the tsvector, at the leaf's weight.
    cols = await _search_columns("gadm")
    assert "'scotia':3A" in cols["GBR.2_1"]["tsv"]

    # A second run replaces the rows rather than adding to them.
    assert await _build_names("gadm") == inserted
    assert await _names("gadm") == names


@pytest.mark.asyncio
async def test_wdpa_context_names_the_country_and_keeps_orig_name(
    gadm_staging,
):
    """A protected area's context is its designation and country name.

    The country name is looked up from the GADM level-0 rows, which the build
    order puts in aois first; the original-language name becomes a native
    variant when it differs from the English one.
    """
    await _build("gadm")
    columns = (
        "wdpa_pid",
        "wdpa_name",
        "orig_name",
        "desig_eng",
        "iso3",
        "name",
        "subtype",
    )
    rows = [
        {
            "wdpa_pid": "1",
            "wdpa_name": "Masirah Island Reserve",
            "orig_name": "محمية مصيرة",
            "desig_eng": "Nature Reserve",
            "iso3": "GBR",
            "name": "Masirah Island Reserve, Nature Reserve, GBR",
            "subtype": "protected-area",
        },
        {
            "wdpa_pid": "2",
            "wdpa_name": "Same Name",
            "orig_name": "same name",
            "desig_eng": "Park",
            "iso3": "ZZZ",
            "name": "Same Name, Park, ZZZ",
            "subtype": "protected-area",
        },
    ]
    async with _staging_table("wdpa", columns, rows):
        await _build("wdpa")
        await _build_names("wdpa")

        cols = await _search_columns("wdpa")
        assert cols["1"]["leaf"] == "Masirah Island Reserve"
        assert cols["1"]["context"] == "Nature Reserve, United Kingdom"
        assert "'محمية':4A" in cols["1"]["tsv"]
        # The designation is in the name vector, the country is not.
        assert "'nature':6B" in cols["1"]["ntsv"]
        assert "'reserve':3A,7B" in cols["1"]["ntsv"]
        assert "kingdom" not in cols["1"]["ntsv"]
        # No GADM country for the code, so the code itself is the context.
        assert cols["2"]["context"] == "Park, ZZZ"

        names = await _names("wdpa")
        assert names["1"] == {("native", "محمية مصيرة")}
        # A case-only difference is not a variant, so the row has no names.
        assert "2" not in names


@pytest.mark.asyncio
async def test_kba_uses_national_name_with_international_variant():
    columns = ("sitrecid", "NatName", "IntName", "Country", "name", "subtype")
    rows = [
        {
            "sitrecid": "10",
            "NatName": "Van Ovasi",
            "IntName": "Van Plains",
            "Country": "Turkey",
            "name": "Van Ovasi, Van Plains, TUR",
            "subtype": "key-biodiversity-area",
        }
    ]
    async with _staging_table("kba", columns, rows):
        await _build("kba")
        await _build_names("kba")

        cols = await _search_columns("kba")
        assert cols["10"]["leaf"] == "Van Ovasi"
        assert cols["10"]["context"] == "Turkey"
        assert (await _names("kba"))["10"] == {("international", "van plains")}


@pytest.mark.asyncio
async def test_token_table_holds_the_distinct_lexemes(gadm_staging):
    await _build("gadm")
    await _build_names("gadm")
    async with async_session_maker() as session:
        count = await _rebuild_search_tokens(session)
        await session.commit()
        tokens = {
            row[0]: (row[1], row[2])
            for row in await session.execute(
                text("SELECT token, ndoc, prominence FROM aoi_search_tokens")
            )
        }

    assert count == len(tokens)
    assert {"barnsley", "scotland", "scotia", "kingdom"} <= set(tokens)
    # The name vector, not the full one: a parent is not a token of its
    # children, so "kingdom" is carried by the country alone.
    assert tokens["kingdom"] == (1, 1.0)
    # A token's prominence is that of the best-known place carrying it.
    assert tokens["scotland"] == (1, 0.9)
    # No-data markers never enter the tsvector, so they are not tokens.
    assert "na" not in tokens


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
