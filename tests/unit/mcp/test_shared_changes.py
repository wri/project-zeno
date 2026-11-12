"""The shared code the MCP server needed changed: the pull checks both
pull_data tools run, the custom-area switch on `search_aois`, the analytics
headers without a token, the canopy cover default, the dataset cards zap
now reads from the catalog, and the bare `/mcp` path."""

from contextlib import asynccontextmanager

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.shared.aoi_search as aoi_search
from src.agent.datasets import pull_checks
from src.agent.datasets.handlers.analytics_handler import (
    analytics_api_headers,
)
from src.agent.datasets.pull_checks import (
    PullRange,
    PullRefusal,
    plan_pull,
    refuse_dataset,
)
from src.api.services.zap import options
from src.mcp.server import ExactMountPath, build_app

TCL = {"dataset_id": 4, "dataset_name": "Tree cover loss"}
AREA = {"source": "gadm", "src_id": "BRA", "name": "Brazil"}

# --- pull checks -------------------------------------------------------------


def test_refuse_dataset_names_the_hidden_dataset():
    assert refuse_dataset(TCL, frozenset({"Tree cover loss"})) == PullRefusal(
        "pull_data.dataset_not_available", {"dataset_name": "Tree cover loss"}
    )
    assert refuse_dataset(TCL, frozenset()) is None


async def test_plan_pull_clamps_to_the_dataset_coverage():
    plan = await plan_pull(TCL, [AREA], "1990-01-01", "2010-12-31")
    assert plan == PullRange("2001-01-01", "2010-12-31", True)


async def test_plan_pull_refuses_a_range_outside_the_coverage():
    plan = await plan_pull(TCL, [AREA], "1990-01-01", "1995-12-31")
    assert isinstance(plan, PullRefusal)
    assert plan.key == "pull_data.date_out_of_range"


async def test_plan_pull_keeps_curated_only_datasets_to_one_area(monkeypatch):
    monkeypatch.setattr(
        pull_checks, "is_curated_only", lambda dataset_id: True
    )
    plan = await plan_pull(TCL, [AREA, AREA], None, None)
    assert plan == PullRefusal(
        "pull_data.single_area_only", {"dataset_name": "Tree cover loss"}
    )
    assert isinstance(await plan_pull(TCL, [AREA], None, None), PullRange)


# --- search_aois without custom areas ----------------------------------------


@pytest.fixture
def searched_sources(monkeypatch):
    """Run search_aois to the point of querying and record the sources."""
    seen = []

    class FakeConnection:
        async def rollback(self):
            pass

    @asynccontextmanager
    async def fake_pool():
        yield FakeConnection()

    async def fake_browse(conn, requested, params):
        seen.append(set(requested))
        return pd.DataFrame()

    monkeypatch.setattr(aoi_search, "get_connection_from_pool", fake_pool)
    monkeypatch.setattr(aoi_search, "_browse", fake_browse)
    return seen


async def test_search_without_a_user_raises_by_default():
    with pytest.raises(ValueError, match="user_id required"):
        await aoi_search.search_aois(name=None, sources=None, user_id=None)


async def test_search_can_leave_custom_areas_out(searched_sources):
    await aoi_search.search_aois(
        name=None, sources=None, user_id=None, include_custom=False
    )
    assert "custom" not in searched_sources[0]
    assert "gadm" in searched_sources[0]


async def test_search_refuses_custom_when_left_out():
    with pytest.raises(ValueError, match="not available"):
        await aoi_search.search_aois(
            name=None,
            sources=["custom"],
            user_id="u1",
            include_custom=False,
        )


# --- analytics headers ------------------------------------------------------


def test_analytics_headers_leave_out_an_empty_token(monkeypatch):
    monkeypatch.delenv("WRI_BEARER_TOKEN", raising=False)
    assert "Authorization" not in analytics_api_headers()
    monkeypatch.setenv("WRI_BEARER_TOKEN", "  ")
    assert "Authorization" not in analytics_api_headers()


def test_analytics_headers_send_a_configured_token(monkeypatch):
    monkeypatch.setenv("WRI_BEARER_TOKEN", "secret")
    assert analytics_api_headers()["Authorization"] == "Bearer secret"


# --- zap cards ------------------------------------------------------------


def test_zap_offers_the_same_datasets_from_the_catalog_cards():
    assert sorted(options.DATASET_CARDS) == [1, 2, 3, 4, 5, 6, 7, 8, 10, 11]
    assert options.DATASET_CARDS[4].startswith("Tree cover loss (2001-2025).")


# --- the /mcp path -------------------------------------------------------


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_mcp_answers_on_the_bare_path_without_a_redirect(path):
    mcp_app = build_app()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.lifespan(app):
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/mcp", mcp_app)
    app.add_middleware(ExactMountPath, path="/mcp")
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    with TestClient(app) as client:
        response = client.post(
            path,
            json=initialize,
            headers={"Accept": "application/json, text/event-stream"},
            follow_redirects=False,
        )
    assert response.status_code == 200
    assert '"serverInfo"' in response.text


# --- review fixes: rate-limit key, area checks, zap rule ---------------------


@pytest.mark.parametrize(
    ("forwarded", "hops", "expected"),
    [
        # A client-written entry before the ingress's own is ignored.
        ("6.6.6.6, 203.0.113.7", 1, "203.0.113.7"),
        ("203.0.113.7", 1, "203.0.113.7"),
        ("6.6.6.6, 203.0.113.7, 10.0.0.2", 2, "203.0.113.7"),
        # Shorter than the trusted chain, or no trust: the peer address.
        ("203.0.113.7", 2, "10.0.0.9"),
        ("6.6.6.6", 0, "10.0.0.9"),
        ("", 1, "10.0.0.9"),
    ],
)
def test_rate_limit_key_is_the_trusted_end_of_the_chain(
    forwarded, hops, expected
):
    from src.mcp.server import client_address

    assert client_address(forwarded, "10.0.0.9", hops) == expected


def _areas(source, count):
    return [{"source": source, "src_id": str(i)} for i in range(count)]


def test_refuse_areas_rejects_mixed_sources_and_oversized_sets():
    from src.agent.datasets.pull_checks import (
        SUBREGION_LIMIT,
        SUBREGION_LIMIT_ADMIN,
        refuse_areas,
    )

    mixed = _areas("gadm", 1) + _areas("kba", 1)
    assert refuse_areas(mixed).key == "pick_aoi.multiple_sources"
    assert refuse_areas(_areas("kba", SUBREGION_LIMIT)) is None
    assert (
        refuse_areas(_areas("kba", SUBREGION_LIMIT + 1)).key
        == "pick_aoi.too_many_subregions"
    )
    assert refuse_areas(_areas("gadm", SUBREGION_LIMIT_ADMIN)) is None
    assert (
        refuse_areas(_areas("logging", SUBREGION_LIMIT + 1)).key
        == "pick_aoi.too_many_concessions"
    )


async def test_plan_pull_refuses_mixed_sources():
    plan = await plan_pull(
        TCL, _areas("gadm", 1) + _areas("kba", 1), None, None
    )
    assert plan == PullRefusal("pick_aoi.multiple_sources")


async def test_handler_checks_every_areas_admin_level(monkeypatch):
    from unittest.mock import patch

    from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler

    areas = [
        {
            "source": "gadm",
            "src_id": "BRA",
            "name": "Brazil",
            "subtype": "country",
        },
        {
            "source": "gadm",
            "src_id": "BRA.14.1.1_1",
            "name": "A locality",
            "subtype": "locality",
        },
    ]
    with patch(
        "src.agent.datasets.handlers.analytics_handler.httpx.AsyncClient",
        side_effect=AssertionError("the analytics API must not be called"),
    ):
        result = await AnalyticsHandler().pull_data(
            query="",
            dataset=TCL,
            start_date="2015-01-01",
            end_date="2020-12-31",
            change_over_time_query=False,
            aois=areas,
        )
    assert not result.success
    assert "A locality" in result.message


@pytest.mark.parametrize(
    ("parameters", "sent"),
    [
        # No selection: the dataset default, not max(values) (75%).
        (None, 30),
        ([{"name": "canopy_cover", "values": [50]}], 50),
    ],
)
async def test_handler_sends_the_default_canopy_cover(
    monkeypatch, parameters, sent
):
    from src.agent.datasets.handlers import analytics_handler

    posted = []

    class RecordingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            posted.append(json)
            raise analytics_handler.httpx.ConnectError("recorded")

    monkeypatch.setattr(
        analytics_handler.httpx, "AsyncClient", RecordingClient
    )
    dataset = {**TCL, **({"parameters": parameters} if parameters else {})}
    await analytics_handler.AnalyticsHandler().pull_data(
        query="",
        dataset=dataset,
        start_date="2015-01-01",
        end_date="2020-12-31",
        change_over_time_query=False,
        aois=[{**AREA, "subtype": "country"}],
    )
    assert posted[0]["canopy_cover"] == sent


def test_every_zap_dataset_has_a_card():
    from src.agent.datasets.config import DATASETS

    offered = [
        ds
        for ds in DATASETS
        if ds["dataset_id"] not in options.ZAP_EXCLUDED_DATASET_IDS
    ]
    assert all(ds.get("selection_card") for ds in offered)
