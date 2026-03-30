"""
End-to-end agent evals for GADM multi-AOI queries.

Tests exercise the full agent graph (real LLM) with mocked spatial DB queries
and a mocked analytics orchestrator, focusing on:
  1. Correct state-level subregion selection for Brazil (26 states, within limit)
  2. Correct municipality-level subregion selection for Tocantins (within limit)
  3. Guardrail fires when AOI count exceeds SUBREGION_LIMIT
"""

import uuid
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from src.agent.graph import fetch_zeno_anonymous
from src.agent.tools.data_handlers.base import DataPullResult
from src.agent.tools.pick_aoi import SUBREGION_LIMIT
from src.agent.tools.pull_data import data_pull_orchestrator

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="function", autouse=True)
def test_db():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    pass


@pytest.fixture(scope="function", autouse=True)
def user():
    pass


@pytest.fixture(scope="function", autouse=True)
def user_ds():
    pass


BRAZIL_AOI_RESULT = pd.DataFrame(
    {
        "src_id": ["BRA"],
        "name": ["Brazil"],
        "subtype": ["country"],
        "source": ["gadm"],
        "similarity_score": [1.0],
    }
)

TOCANTINS_AOI_RESULT = pd.DataFrame(
    {
        "src_id": ["BRA.27_1"],
        "name": ["Tocantins, Brazil"],
        "subtype": ["state-province"],
        "source": ["gadm"],
        "similarity_score": [0.95],
    }
)

_STATE_NAMES = [
    "Acre", "Alagoas", "Amapá", "Amazonas", "Bahia", "Ceará",
    "Espírito Santo", "Goiás", "Maranhão", "Mato Grosso", "Mato Grosso do Sul",
    "Minas Gerais", "Pará", "Paraíba", "Paraná", "Pernambuco", "Piauí",
    "Rio de Janeiro", "Rio Grande do Norte", "Rio Grande do Sul", "Rondônia",
    "Roraima", "Santa Catarina", "São Paulo", "Sergipe", "Tocantins",
]
BRAZIL_STATES_RESULT = pd.DataFrame(
    {
        "name": [f"{s}, Brazil" for s in _STATE_NAMES],
        "subtype": ["state-province"] * 26,
        "src_id": [f"BRA.{i + 1}_1" for i in range(26)],
        "source": ["gadm"] * 26,
    }
)

_TOCANTINS_MUNIS = [
    "Palmas", "Araguaína", "Gurupi", "Porto Nacional", "Paraíso do Tocantins",
    "Colinas do Tocantins", "Guaraí", "Tocantinópolis", "Dianópolis",
    "Formoso do Araguaia", "Miracema do Tocantins", "Araguatins",
    "Augustinópolis", "Xambioá", "Alvorada", "Natividade", "Pedro Afonso",
    "Arraias", "Peixe", "Lagoa da Confusão",
]
TOCANTINS_MUNIS_RESULT = pd.DataFrame(
    {
        "name": [f"{m}, Tocantins, Brazil" for m in _TOCANTINS_MUNIS],
        "subtype": ["district-county"] * len(_TOCANTINS_MUNIS),
        "src_id": [f"BRA.27.{i + 1}_1" for i in range(len(_TOCANTINS_MUNIS))],
        "source": ["gadm"] * len(_TOCANTINS_MUNIS),
    }
)

BRAZIL_ALL_MUNIS_RESULT = pd.DataFrame(
    {
        "name": [f"Municipality {i}, Brazil" for i in range(SUBREGION_LIMIT + 1)],
        "subtype": ["district-county"] * (SUBREGION_LIMIT + 1),
        "src_id": [f"BRA.muni.{i}_1" for i in range(SUBREGION_LIMIT + 1)],
        "source": ["gadm"] * (SUBREGION_LIMIT + 1),
    }
)

_STUB_PULL_RESULT = DataPullResult(
    success=True,
    data={"data": {}},
    message="Data pulled.",
    analytics_api_url="http://example.com/api",
)


def _collect_tool_messages(steps: list[dict]) -> list[str]:
    messages = []
    for step in steps:
        for node_data in step.values():
            for msg in node_data.get("messages", []):
                if hasattr(msg, "content") and msg.content:
                    messages.append(str(msg.content))
    return messages


def _get_aoi_selection(steps: list[dict]) -> dict | None:
    for step in steps:
        for node_data in step.values():
            if node_data.get("aoi_selection"):
                return node_data["aoi_selection"]
    return None


async def _run_agent(
    query: str,
    mock_aoi_df: pd.DataFrame,
    mock_subregion_df: pd.DataFrame,
) -> list[dict]:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    async def _mock_aoi_db(_place_name, result_limit=10):
        return mock_aoi_df.copy()

    async def _mock_subregion_db(_subregion_name, _source, _src_id):
        return mock_subregion_df.copy()

    zeno_agent = await fetch_zeno_anonymous()
    steps = []

    with (
        patch(
            "src.agent.tools.pick_aoi.query_aoi_database",
            new_callable=AsyncMock,
            side_effect=_mock_aoi_db,
        ),
        patch(
            "src.agent.tools.pick_aoi.query_subregion_database",
            new_callable=AsyncMock,
            side_effect=_mock_subregion_db,
        ),
        patch.object(
            data_pull_orchestrator,
            "pull_data",
            AsyncMock(return_value=_STUB_PULL_RESULT),
        ),
    ):
        async for step in zeno_agent.astream(
            {"messages": [{"role": "user", "content": query}]}, config
        ):
            steps.append(step)

    return steps


async def test_eval_which_state_brazil_most_tcl_2019(structlog_context):
    """
    Agent should select all 26 Brazilian states (within the 500-AOI limit)
    and not trigger the subregion guardrail.
    """
    steps = await _run_agent(
        query="Which state in Brazil had the most tree cover loss in 2019",
        mock_aoi_df=BRAZIL_AOI_RESULT,
        mock_subregion_df=BRAZIL_STATES_RESULT,
    )

    assert len(steps) > 0

    aoi_selection = _get_aoi_selection(steps)
    assert aoi_selection is not None, "Agent should have selected AOIs"
    assert len(aoi_selection["aois"]) == 26, (
        f"Expected 26 states, got {len(aoi_selection['aois'])}"
    )

    tool_messages = _collect_tool_messages(steps)
    assert not any(
        "too many" in m.lower() or "narrow down" in m.lower()
        for m in tool_messages
    ), f"Guardrail should NOT fire for 26 states. Messages: {tool_messages}"


async def test_eval_which_municipality_tocantins_most_grassland_loss(structlog_context):
    """
    Agent should select Tocantins municipalities (within the 500-AOI limit)
    and not trigger the subregion guardrail.
    """
    steps = await _run_agent(
        query="Which municipality of Tocantins, Brazil lost the most natural grassland between 2018 and 2022",
        mock_aoi_df=TOCANTINS_AOI_RESULT,
        mock_subregion_df=TOCANTINS_MUNIS_RESULT,
    )

    assert len(steps) > 0

    aoi_selection = _get_aoi_selection(steps)
    assert aoi_selection is not None, "Agent should have selected AOIs"
    assert len(aoi_selection["aois"]) == len(_TOCANTINS_MUNIS), (
        f"Expected {len(_TOCANTINS_MUNIS)} municipalities, got {len(aoi_selection['aois'])}"
    )

    tool_messages = _collect_tool_messages(steps)
    assert not any(
        "too many" in m.lower() or "narrow down" in m.lower()
        for m in tool_messages
    ), f"Guardrail should NOT fire for {len(_TOCANTINS_MUNIS)} municipalities. Messages: {tool_messages}"


async def test_eval_antipattern_all_municipalities_brazil_triggers_guardrail(structlog_context):
    """
    Anti-pattern: querying all municipalities in Brazil (>500) should trigger
    the GADM subregion limit guardrail. The agent must not proceed to data analysis.
    """
    steps = await _run_agent(
        query="Compare tree cover loss for all municipalities in Brazil since 2015",
        mock_aoi_df=BRAZIL_AOI_RESULT,
        mock_subregion_df=BRAZIL_ALL_MUNIS_RESULT,
    )

    assert len(steps) > 0

    tool_messages = _collect_tool_messages(steps)
    assert any(
        "too many" in m.lower() or "narrow down" in m.lower()
        for m in tool_messages
    ), f"Guardrail should fire for {SUBREGION_LIMIT + 1} municipalities. Messages: {tool_messages}"

    assert _get_aoi_selection(steps) is None, (
        "Agent must NOT set aoi_selection when guardrail fires"
    )
