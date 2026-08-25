from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.agent.config import AgentSettings
from src.agent.subagents.pick_aoi import Geocoder, pick_aoi
from src.agent.subagents.pick_aoi.tool import (
    AOIIndex,
    ExtractedPlace,
    PlaceQuery,
    _as_extracted_place,
)
from src.agent.subagents.pick_aoi.types import AreaOfInterestType
from src.shared import geocoding_helpers
from src.shared.geocoding_helpers import fetch_aoi_bbox
from tests.unit.agent.tools.pick_aoi.conftest import (
    _lookup,
    _patch_search,
    _row,
    _SmallModelStub,
    tool_module,
)


def _fake_conn_context(captured, row):
    """A substitute for a pooled connection. It records the SQL and returns *row*."""

    class _FakeConn:
        async def execute(self, query, params=None):
            captured["sql"] = str(query)
            captured["params"] = params
            result = MagicMock()
            result.fetchone.return_value = row
            return result

    class _FakeConnContext:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    return _FakeConnContext()


@pytest.mark.asyncio
async def test_fetch_aoi_bbox_unknown_source_returns_default():
    result = await fetch_aoi_bbox("unknown_source", "some_id")
    assert result == [-180.0, -90.0, 180.0, 90.0]


@pytest.mark.asyncio
async def test_fetch_aoi_bbox_reads_precomputed_bbox_for_every_source(
    monkeypatch,
):
    """One query reads aois for every source. No per-source bbox SQL remains."""
    captured = {}

    def fake_pool():
        return _fake_conn_context(captured, ([1.0, 2.0, 3.0, 4.0],))

    monkeypatch.setattr(
        geocoding_helpers, "get_connection_from_pool", fake_pool
    )

    for source in ("custom", "gadm", "kba"):
        assert await fetch_aoi_bbox(source, "some-id") == [
            1.0,
            2.0,
            3.0,
            4.0,
        ]
        assert "FROM aois" in captured["sql"]
        assert captured["params"] == {"source": source, "src_id": "some-id"}
        # The antimeridian CASE ran for each row before. The build now computes
        # the bbox.
        assert "ST_ClipByBox2D" not in captured["sql"]


@pytest.mark.asyncio
async def test_fetch_aoi_bbox_no_row_returns_default(monkeypatch):
    def fake_pool():
        return _fake_conn_context({}, None)

    monkeypatch.setattr(
        geocoding_helpers, "get_connection_from_pool", fake_pool
    )

    result = await fetch_aoi_bbox("gadm", "NONEXISTENT")

    assert result == [-180.0, -90.0, 180.0, 90.0]


@pytest.mark.asyncio
async def test_fetch_aoi_bbox_null_bbox_returns_default(monkeypatch):
    """aois.bbox accepts a null. A null must not reach the bbox of the AOI."""

    def fake_pool():
        return _fake_conn_context({}, (None,))

    monkeypatch.setattr(
        geocoding_helpers, "get_connection_from_pool", fake_pool
    )

    assert await fetch_aoi_bbox("gadm", "BRA") == [-180.0, -90.0, 180.0, 90.0]


# ---------------------------------------------------------------------------
# pick_aoi tool / Geocoder wiring — the thin tool delegates to the geocoding
# subagent, which extracts place(s) from the question then looks them up.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_aoi_tool_resolves_via_geocoder(monkeypatch):
    """The tool takes only `question`: the subagent extracts the place,
    then runs the DB lookup. No places/subregion args from the caller."""

    async def fake_extract(self, question, aoi_type):
        return PlaceQuery(
            places=[ExtractedPlace(place="Para, Brazil")], subregion=None
        )

    async def fake_query_aoi_database(place_name, aoi_type, result_limit=10):
        return pd.DataFrame(
            [_row("BRA.14_1", "Para, Brazil", subtype="state-province")]
        )

    monkeypatch.setattr(Geocoder, "extract", fake_extract)
    monkeypatch.setattr(
        tool_module, "query_aoi_database", fake_query_aoi_database
    )

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "tree cover loss in Para, Brazil",
                "area_of_interest": "adminstrative area (country, state/region, country/subregion)",
                "state": {},
            },
            "id": "tc-1",
            "type": "tool_call",
        }
    )

    selection = command.update["aoi_selection"]
    assert selection["name"] == "Para, Brazil"
    assert selection["aois"][0]["src_id"] == "BRA.14_1"


@pytest.mark.asyncio
async def test_pick_aoi_tool_asks_for_clarification_when_no_place(
    monkeypatch,
):
    async def fake_extract(self, question, aoi_type):
        return PlaceQuery(places=[], subregion=None)

    monkeypatch.setattr(Geocoder, "extract", fake_extract)

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "show me tree cover loss",
                "area_of_interest": None,
                "state": {},
            },
            "id": "tc-2",
            "type": "tool_call",
        }
    )

    assert "aoi_selection" not in command.update
    assert "couldn't identify a place" in str(
        command.update["messages"][0].content
    )


@pytest.mark.asyncio
async def test_select_best_aoi_empty_candidates_returns_none():
    """The model-selection path, still reachable via AOI_NORMALIZER_ENABLED.

    When DB search returns zero rows, select_best_aoi should return None
    instead of crashing with 'single positional indexer is out-of-bounds'."""
    from src.agent.subagents.pick_aoi.tool import select_best_aoi

    result = await select_best_aoi("some question", pd.DataFrame())
    assert result is None


@pytest.mark.asyncio
async def test_select_best_aoi_bad_src_id_returns_none(monkeypatch):
    """The model-selection path, still reachable via AOI_NORMALIZER_ENABLED.

    When the LLM picks a src_id that isn't among the candidates,
    select_best_aoi should return None instead of crashing on .iloc[0]."""

    async def fake_structured_output(_input):
        return tool_module.AOIId(src_id="does-not-exist")

    class _FakeSmallModel:
        def with_structured_output(self, schema):
            return fake_structured_output

    monkeypatch.setattr(tool_module, "SMALL_MODEL", _FakeSmallModel())

    candidates = pd.DataFrame(
        [
            {
                "src_id": "BRA.14_1",
                "name": "Para, Brazil",
                "subtype": "state-province",
                "source": "gadm",
            }
        ]
    )
    result = await tool_module.select_best_aoi("some question", candidates)
    assert result is None


@pytest.mark.asyncio
async def test_pick_aoi_returns_no_match_when_db_search_empty(monkeypatch):
    """When the DB returns no candidates, pick_aoi should return a helpful
    message instead of crashing."""

    async def fake_extract(self, question, aoi_type):
        return PlaceQuery(
            places=[ExtractedPlace(place="Nonexistent Place")], subregion=None
        )

    async def fake_query_aoi_database(place_name, aoi_type, result_limit=10):
        return pd.DataFrame()  # empty results

    monkeypatch.setattr(Geocoder, "extract", fake_extract)
    monkeypatch.setattr(
        tool_module, "query_aoi_database", fake_query_aoi_database
    )

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "trees around Nonexistent Place",
                "area_of_interest": None,
                "state": {},
            },
            "id": "tc-3",
            "type": "tool_call",
        }
    )

    assert "aoi_selection" not in command.update
    assert (
        "no matching location"
        in str(command.update["messages"][0].content).lower()
    )


@pytest.mark.asyncio
async def test_pick_aoi_reports_unmatched_places_alongside_matches(
    monkeypatch,
):
    """When some places match and others don't, pick_aoi should still return
    the matches but name the place(s) it couldn't find rather than silently
    dropping them."""

    async def fake_extract(self, question, aoi_type):
        return PlaceQuery(
            places=[
                ExtractedPlace(place="Para, Brazil"),
                ExtractedPlace(place="Nonexistent Place"),
            ],
            subregion=None,
        )

    async def fake_query_aoi_database(place_name, aoi_type, result_limit=10):
        if place_name == "Para, Brazil":
            return pd.DataFrame(
                [_row("BRA.14_1", "Para, Brazil", subtype="state-province")]
            )
        return pd.DataFrame()

    monkeypatch.setattr(Geocoder, "extract", fake_extract)
    monkeypatch.setattr(
        tool_module, "query_aoi_database", fake_query_aoi_database
    )

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": (
                    "tree cover loss in Para, Brazil and Nonexistent Place"
                ),
                "area_of_interest": None,
                "state": {},
            },
            "id": "tc-4",
            "type": "tool_call",
        }
    )

    selection = command.update["aoi_selection"]
    assert selection["aois"][0]["src_id"] == "BRA.14_1"
    assert "Nonexistent Place" in str(command.update["messages"][0].content)


# ---------------------------------------------------------------------------
# Extraction shape (PZB-1272) — normalisation rides on the extract call.
# ---------------------------------------------------------------------------


def test_an_extracted_place_needs_only_a_place_name():
    """Every normalisation field is additive, so an un-normalised place is
    still a valid one — that is what makes the kill switch a no-op."""
    place = ExtractedPlace(place="Brazil")

    assert place.place == "Brazil"
    assert place.canonical == ""
    assert place.alternatives == []
    assert place.area_type is None


def test_an_extracted_place_carries_normalisation_and_a_type():
    place = ExtractedPlace(
        place="Botum Sakor National Park",
        canonical="Botum Sakor",
        alternatives=["Parque Nacional Botum Sakor"],
        # The model emits the enum's value as a string.
        area_type="protected area, park, or reserve",
    )
    query = PlaceQuery(places=[place], subregion=None)

    assert query.places[0].area_type == AreaOfInterestType.WDPA
    assert query.places[0].canonical == "Botum Sakor"


def test_a_bare_place_name_means_no_normalisation():
    coerced = _as_extracted_place("Para, Brazil")

    assert coerced == ExtractedPlace(place="Para, Brazil")
    assert _as_extracted_place(coerced) is coerced


# ---------------------------------------------------------------------------
# Multi-term search (PZB-1272) — one query per term, merged and deduplicated.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_single_term_search_is_unchanged(monkeypatch):
    calls = _patch_search(monkeypatch, {"Brazil": [_row("BRA", "Brazil")]})

    merged, primary = await tool_module.query_aoi_database_multiterm(
        ["Brazil"], None
    )

    assert calls == [("Brazil", None, 10)]
    assert list(merged["src_id"]) == ["BRA"]
    assert primary.equals(merged)


@pytest.mark.asyncio
async def test_every_term_is_searched_and_the_results_merged(monkeypatch):
    _patch_search(
        monkeypatch,
        {
            "Ivory Coast": [_row("NZL.12_1", "West Coast, New Zealand")],
            "Cote d'Ivoire": [_row("CIV", "Côte d'Ivoire")],
        },
    )

    merged, primary = await tool_module.query_aoi_database_multiterm(
        ["Ivory Coast", "Cote d'Ivoire"], None
    )

    assert set(merged["src_id"]) == {"NZL.12_1", "CIV"}
    # The ambiguity check must only ever see what the place name itself
    # retrieved, so the primary frame stays the first term's result.
    assert list(primary["src_id"]) == ["NZL.12_1"]


@pytest.mark.asyncio
async def test_a_row_matched_by_two_terms_appears_once_at_its_best_score(
    monkeypatch,
):
    _patch_search(
        monkeypatch,
        {
            "Brazil": [_row("BRA", "Brazil", score=0.6)],
            "Brasil": [_row("BRA", "Brazil", score=0.9)],
        },
    )

    merged, _ = await tool_module.query_aoi_database_multiterm(
        ["Brazil", "Brasil"], None
    )

    assert len(merged) == 1
    assert merged.iloc[0]["similarity_score"] == 0.9


@pytest.mark.asyncio
async def test_terms_matching_different_sources_are_all_returned(monkeypatch):
    _patch_search(
        monkeypatch,
        {
            "Leuser": [_row("IDN.1_1", "Aceh, Indonesia")],
            "Gunung Leuser": [
                _row(
                    "1251",
                    "Gunung Leuser, National Park, IDN",
                    source="wdpa",
                    subtype="protected-area",
                )
            ],
        },
    )

    merged, _ = await tool_module.query_aoi_database_multiterm(
        ["Leuser", "Gunung Leuser"], None
    )

    assert set(merged["source"]) == {"gadm", "wdpa"}


@pytest.mark.asyncio
async def test_no_term_matching_anything_yields_an_empty_frame(monkeypatch):
    _patch_search(monkeypatch, {})

    merged, primary = await tool_module.query_aoi_database_multiterm(
        ["Nowhere", "Nowhere at all"], None
    )

    assert merged.empty
    assert primary.empty


@pytest.mark.asyncio
async def test_searching_without_a_term_is_a_programming_error(monkeypatch):
    _patch_search(monkeypatch, {})

    with pytest.raises(ValueError, match="needs a search term"):
        await tool_module.query_aoi_database_multiterm([], None)


# ---------------------------------------------------------------------------
# Geocoder.lookup wiring (PZB-1272) — normalised terms, per-place source
# narrowing, deterministic selection, and the kill switch.
# ---------------------------------------------------------------------------

_BOTUM_SAKOR = ExtractedPlace(
    place="Botum Sakor National Park",
    canonical="Botum Sakor",
    alternatives=["Parque Nacional Botum Sakor"],
    area_type=AreaOfInterestType.WDPA,
)

_FOREIGN_PARKS = [
    _row("555", "Boma, National Park, SSD", "wdpa", "protected-area"),
    _row("556", "Bako, National Park, MYS", "wdpa", "protected-area"),
]
_BOTUM_SAKOR_ROW = [
    _row(
        "478405",
        "Botum Sakor, ឧទ្យានជាតិ ដើម, KHM",
        "wdpa",
        "protected-area",
    )
]


@pytest.mark.asyncio
async def test_lookup_still_accepts_plain_place_strings(monkeypatch):
    """Callers and the DB-tier suites pass place names, not objects."""
    _patch_search(
        monkeypatch,
        {
            "Para, Brazil": [
                _row(
                    "BRA.14_1",
                    "Pará, Brazil",
                    subtype="state-province",
                    score=0.71,
                )
            ]
        },
    )
    monkeypatch.setattr(tool_module, "SMALL_MODEL", _SmallModelStub())

    command = await _lookup(
        ["Para, Brazil"], question="deforestation in Para, Brazil"
    )

    aois = command.update["aoi_selection"]["aois"]
    assert [aoi["src_id"] for aoi in aois] == ["BRA.14_1"]


@pytest.mark.asyncio
async def test_selection_never_calls_a_model_and_is_repeatable(monkeypatch):
    _patch_search(
        monkeypatch,
        {
            "Botum Sakor National Park": _FOREIGN_PARKS,
            "Botum Sakor": _BOTUM_SAKOR_ROW,
            "Parque Nacional Botum Sakor": _BOTUM_SAKOR_ROW,
        },
    )
    monkeypatch.setattr(tool_module, "SMALL_MODEL", _SmallModelStub())

    picks = []
    for _ in range(2):
        command = await _lookup([_BOTUM_SAKOR])
        picks.append(command.update["aoi_selection"]["aois"][0]["src_id"])

    # The canonical leaf name finds the row the user's wording cannot, and
    # the same candidates always yield the same AOI.
    assert picks == ["478405", "478405"]


@pytest.mark.asyncio
async def test_normalisation_searches_the_canonical_and_alternative_names(
    monkeypatch,
):
    calls = _patch_search(monkeypatch, {"Botum Sakor": _BOTUM_SAKOR_ROW})

    await _lookup([_BOTUM_SAKOR])

    assert [call[0] for call in calls] == [
        "Botum Sakor National Park",
        "Botum Sakor",
        "Parque Nacional Botum Sakor",
    ]
    assert {call[1] for call in calls} == {AreaOfInterestType.WDPA}


@pytest.mark.asyncio
async def test_the_kill_switch_restores_the_single_term_model_pick(
    monkeypatch,
):
    calls = _patch_search(
        monkeypatch, {"Botum Sakor National Park": _FOREIGN_PARKS}
    )
    monkeypatch.setattr(AgentSettings, "aoi_normalizer_enabled", False)

    asked = []

    async def fake_select_best_aoi(question, candidate_aois):
        asked.append(question)
        return AOIIndex(**_FOREIGN_PARKS[0])

    monkeypatch.setattr(tool_module, "select_best_aoi", fake_select_best_aoi)

    command = await _lookup(
        [_BOTUM_SAKOR],
        question="tree cover in Botum Sakor National Park",
    )

    # Only the extracted place name is searched, the inferred type is
    # ignored, and the model chooses again.
    assert [call[0] for call in calls] == ["Botum Sakor National Park"]
    assert [call[1] for call in calls] == [None]
    assert asked == ["tree cover in Botum Sakor National Park"]
    assert command.update["aoi_selection"]["aois"][0]["src_id"] == "555"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "aoi_type,searched_type",
    [
        (None, AreaOfInterestType.WDPA),
        (AreaOfInterestType.GADM, AreaOfInterestType.GADM),
    ],
    ids=["inferred", "explicit-wins"],
)
async def test_an_explicit_area_of_interest_beats_the_inferred_type(
    monkeypatch, aoi_type, searched_type
):
    """The caller's type wins; the inferred one only fills a gap."""
    calls = _patch_search(monkeypatch, {"Botum Sakor": _BOTUM_SAKOR_ROW})

    await _lookup([_BOTUM_SAKOR], aoi_type=aoi_type)

    assert {call[1] for call in calls} == {searched_type}


@pytest.mark.asyncio
async def test_a_narrowed_search_that_finds_nothing_retries_every_source(
    monkeypatch,
):
    """A wrong inferred type must not cost recall."""

    def only_unrestricted(place_name, aoi_type):
        if aoi_type is not None:
            return []
        return [
            _row("KHM.4_1", "Koh Kong, Cambodia", subtype="state-province")
        ]

    calls = _patch_search(monkeypatch, only_unrestricted)

    command = await _lookup([_BOTUM_SAKOR])

    narrowed = [call for call in calls if call[1] is not None]
    unrestricted = [call for call in calls if call[1] is None]
    assert len(narrowed) == 3 and len(unrestricted) == 3
    assert command.update["aoi_selection"]["aois"][0]["src_id"] == "KHM.4_1"


@pytest.mark.asyncio
async def test_an_ambiguity_nudge_ignores_rows_an_alternative_found(
    monkeypatch,
):
    """The aoi_choice round-trip must stay finite.

    Clicking an option resubmits its display string, which is re-resolved by
    the same search. If a choice could be offered over rows that only an
    invented alternative spelling retrieved, the same choice would come back
    forever.
    """
    _patch_search(
        monkeypatch,
        {
            "Puri, India": [
                _row(
                    "IND.26.26_1",
                    "Puri, Odisha, India",
                    subtype="district-county",
                )
            ],
            "Puri Town": [
                _row(
                    "SLE.1.2_1",
                    "Puri, Sierra Leone",
                    subtype="district-county",
                )
            ],
        },
    )

    command = await _lookup(
        [
            ExtractedPlace(
                place="Puri, India",
                canonical="Puri, India",
                alternatives=["Puri Town"],
            )
        ],
        question="deforestation in Puri, India",
    )

    assert "nudge" not in command.update
    assert (
        command.update["aoi_selection"]["aois"][0]["src_id"] == "IND.26.26_1"
    )


@pytest.mark.asyncio
async def test_an_ambiguity_nudge_still_fires_for_the_place_name_itself(
    monkeypatch,
):
    _patch_search(
        monkeypatch,
        {
            "Puri, India": [
                _row(
                    "IND.26.26_1",
                    "Puri, Odisha, India",
                    subtype="district-county",
                ),
                _row(
                    "SLE.1.2_1",
                    "Puri, Sierra Leone",
                    subtype="district-county",
                ),
            ]
        },
    )

    command = await _lookup(
        [ExtractedPlace(place="Puri, India")],
        question="deforestation in Puri, India",
    )

    assert command.update["nudge"]["type"] == "aoi_choice"
    assert len(command.update["nudge"]["options"]) == 2


@pytest.mark.asyncio
async def test_each_place_is_searched_with_its_own_terms(monkeypatch):
    calls = _patch_search(
        monkeypatch,
        {
            "Ivory Coast": [],
            "Côte d'Ivoire": [_row("CIV", "Côte d'Ivoire")],
            "Ghana": [_row("GHA", "Ghana")],
        },
    )

    command = await _lookup(
        [
            ExtractedPlace(
                place="Ivory Coast",
                canonical="Côte d'Ivoire",
                alternatives=["Ivory Coast"],
            ),
            ExtractedPlace(place="Ghana", canonical="Ghana"),
        ],
        question="compare forest loss in Ivory Coast and Ghana",
    )

    # "Ivory Coast" is not repeated as an alternative of itself.
    assert [call[0] for call in calls] == [
        "Ivory Coast",
        "Côte d'Ivoire",
        "Ghana",
    ]
    assert {
        aoi["src_id"] for aoi in command.update["aoi_selection"]["aois"]
    } == {"CIV", "GHA"}


@pytest.mark.asyncio
async def test_a_place_resolved_only_by_an_alternative_raises_no_nudge(
    monkeypatch,
):
    """A new state: the place name matched nothing, an alternative did.

    Before multi-term search an empty candidate frame always meant no
    selection, so the ambiguity check never ran against one.
    """
    _patch_search(
        monkeypatch,
        {
            "United States of America": [
                _row(
                    "USA.6_1",
                    "Colorado, United States",
                    subtype="state-province",
                )
            ]
        },
    )

    command = await _lookup(
        [
            ExtractedPlace(
                place="Colorado, USA",
                canonical="United States of America",
            )
        ],
        question="forest loss in Colorado",
    )

    assert "nudge" not in command.update
    assert command.update["aoi_selection"]["aois"][0]["src_id"] == "USA.6_1"
