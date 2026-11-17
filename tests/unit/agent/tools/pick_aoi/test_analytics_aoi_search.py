import httpx
import pytest

from src.agent.subagents.pick_aoi.analytics_aoi_search import (
    AnalyticsApiAoiSearch,
)
from src.agent.subagents.pick_aoi.types import AreaOfInterestType
from src.shared.request_context import bound_user_id

BASE_URL = "http://analytics.test"


def search_returning(matches, requests):
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"data": matches, "status": "success"})

    return AnalyticsApiAoiSearch(
        BASE_URL, transport=httpx.MockTransport(handle)
    )


def match(aoi_type, aoi_id, display_name, bbox=(-1.0, -2.0, 3.0, 4.0)):
    return {
        "aoi_type": aoi_type,
        "aoi_id": aoi_id,
        "name": display_name.split(",")[0],
        "display_name": display_name,
        "bbox": list(bbox),
    }


@pytest.mark.asyncio
async def test_matches_become_candidate_rows_in_zenos_aoi_shape():
    search = search_returning(
        [
            match("admin", "BRA.12", "Mato Grosso, Brazil"),
            match("admin", "BRA", "Brazil"),
            match("key_biodiversity_area", "22245", "Rio Capim, Brazil"),
            match("protected_area", "975", "Yosemite, National Park, USA"),
            match("indigenous_land", "MEX358", "Champotón, Mexico"),
            match("custom_aoi", "home-farm", "Home farm"),
        ],
        [],
    )

    rows = await search.candidates("anything", None, 10)

    assert rows[["source", "src_id", "name", "subtype"]].values.tolist() == [
        ["gadm", "BRA.12_1", "Mato Grosso, Brazil", "state-province"],
        ["gadm", "BRA", "Brazil", "country"],
        ["kba", "22245", "Rio Capim, Brazil", "key-biodiversity-area"],
        ["wdpa", "975", "Yosemite, National Park, USA", "protected-area"],
        [
            "landmark",
            "MEX358",
            "Champotón, Mexico",
            "indigenous-and-community-land",
        ],
        ["custom", "home-farm", "Home farm", "custom-area"],
    ]
    assert rows["bbox"][0] == [-1.0, -2.0, 3.0, 4.0]


@pytest.mark.asyncio
async def test_rank_order_is_kept_as_descending_similarity():
    search = search_returning(
        [
            match("admin", "BRA.12", "Mato Grosso, Brazil"),
            match("admin", "BRA", "Brazil"),
        ],
        [],
    )

    rows = await search.candidates("mato grosso", None, 10)

    assert rows["similarity_score"].is_monotonic_decreasing
    assert rows["similarity_score"].nunique() == 2


@pytest.mark.asyncio
async def test_the_global_admin_area_is_left_out():
    search = search_returning([match("admin", "global", "Global")], [])

    rows = await search.candidates("world", None, 10)

    assert rows.empty


@pytest.mark.asyncio
async def test_the_request_names_the_place_type_and_limit_but_not_the_user():
    requests = []
    search = search_returning([], requests)

    with bound_user_id("user-1"):
        await search.candidates("Yosemite", AreaOfInterestType.WDPA, 5)

    params = dict(requests[0].url.params)
    assert requests[0].url.path == "/v0/aois/search"
    assert params == {
        "q": "Yosemite",
        "type": "protected_area",
        "limit": "5",
    }
