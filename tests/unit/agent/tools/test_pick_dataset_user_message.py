"""The dataset selection reads the user's latest message, and the
orchestrator's query is context.

The orchestrator rewrites requests into dataset phrases ("tree cover loss by
driver (fire)"), and the selection then offered a choice where the user's
words fit one dataset (BENCHMARK 2026-draft-5, 2026-11-17).
"""

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.subagents.pick_dataset.tool import (
    _interleave,
    latest_user_message,
    pick_dataset,
    selection_query,
)
from src.agent.tool_spec import Availability, set_bound_availability


def test_latest_user_message_is_the_last_human_text():
    messages = [
        HumanMessage("first question"),
        AIMessage("an answer"),
        HumanMessage(
            [{"type": "text", "text": "Tree cover loss due to fires"}]
        ),
        AIMessage("calling a tool"),
    ]
    assert latest_user_message(messages) == "Tree cover loss due to fires"
    assert latest_user_message([AIMessage("only the agent")]) is None
    assert latest_user_message(None) is None


def test_selection_query_puts_the_user_message_first():
    text = selection_query(
        "tree cover loss by driver (fire)",
        "Has fire-driven tree cover loss in Bolivia gone down since 2019?",
    )
    assert text.startswith("Has fire-driven tree cover loss in Bolivia")
    assert (
        "The agent's request for this selection: tree cover loss by " in text
    )


def test_selection_query_names_the_part_for_a_multi_dataset_message():
    """The second pick_dataset call of "compare A and B" must select B."""
    text = selection_query(
        "fire alerts in Riau",
        "Compare tree cover loss and fire alerts in Riau",
    )
    assert "more than one dataset" in text
    assert "the part that the agent's request names" in text


def test_selection_query_without_a_different_message_is_the_query():
    assert selection_query("tree cover loss", None) == "tree cover loss"
    assert selection_query("tree cover loss", " tree cover loss ") == (
        "tree cover loss"
    )


@pytest.mark.asyncio
async def test_pick_dataset_passes_the_user_message():
    state = {
        "messages": [HumanMessage("Was 2020 loss in Indonesia from fires?")],
        "language": "en",
    }
    resolve = AsyncMock(return_value=None)
    with patch(
        "src.agent.subagents.pick_dataset.tool.DatasetSelector.resolve",
        resolve,
    ):
        await pick_dataset.coroutine(
            query="tree cover loss by driver and fires",
            state=state,
            tool_call_id="call-1",
        )
    assert resolve.await_args.kwargs["user_message"] == (
        "Was 2020 loss in Indonesia from fires?"
    )


def test_the_user_message_rules_keep_the_layer_default_for_deforestation():
    """A plain "tree cover loss" request gets no context layer, but
    "deforestation" keeps the default of the dataset hints (BENCHMARK
    2026-11-17)."""
    from src.agent.subagents.pick_dataset.tool import (
        SELECTION_RULES,
        USER_MESSAGE_SELECTION_RULES,
    )

    added = USER_MESSAGE_SELECTION_RULES.split("\n")[-1]
    assert added not in SELECTION_RULES
    assert '"tree cover loss"' in added
    assert "deforestation" in added
    assert "dataset hints" in added


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_message", "rules_name"),
    [
        ("Why did Brazil lose so much primary forest in 2016?", "user"),
        (None, "default"),
    ],
)
async def test_the_user_message_selection_uses_its_own_rules(
    user_message, rules_name
):
    """A "why" or a purpose in the user's message must not make the
    selection decline: the agent explains that part."""
    from src.agent.datasets.config import DATASETS
    from src.agent.subagents.pick_dataset import tool as pd_tool

    set_bound_availability(Availability(skills=frozenset(), tools=frozenset()))
    candidates = pd.DataFrame([DATASETS[0]])
    select = AsyncMock(side_effect=RuntimeError("stop after the call"))
    with (
        patch.object(
            pd_tool,
            "rag_candidate_datasets",
            AsyncMock(return_value=candidates),
        ),
        patch.object(pd_tool, "select_best_dataset", select),
        pytest.raises(RuntimeError),
    ):
        await pd_tool.DatasetSelector().resolve(
            "primary forest loss in Brazil in 2016",
            user_message=user_message,
        )
    expected = (
        pd_tool.USER_MESSAGE_SELECTION_RULES
        if rules_name == "user"
        else pd_tool.SELECTION_RULES
    )
    assert select.await_args.kwargs["rules"] == expected


def test_interleave_takes_the_best_of_each_list_first():
    assert _interleave([[1, 2, 3], [4, 2, 5]], 5) == [1, 4, 2, 3, 5]
    assert _interleave([[1, 2, 3], [4, 5, 6]], 3) == [1, 4, 2]
    assert _interleave([[], [7]], 5) == [7]


@pytest.mark.asyncio
async def test_retrieval_uses_the_message_and_the_agent_request():
    """A follow-up such as "same for 2015" names no dataset: the agent's
    request must still reach the retrieval."""
    from langchain_core.documents import Document

    from src.agent.datasets.config import DATASETS
    from src.agent.subagents.pick_dataset import tool as pd_tool

    ids = [str(d["dataset_id"]) for d in DATASETS[:4]]
    by_query = {
        "same for 2015": [Document("a", id=ids[0]), Document("b", id=ids[1])],
        "tree cover loss by driver": [
            Document("c", id=ids[2]),
            Document("a", id=ids[0]),
            Document("d", id=ids[3]),
        ],
    }
    retriever = AsyncMock()
    retriever.ainvoke.side_effect = lambda q: by_query[q]
    with patch.object(
        pd_tool, "_get_retriever", AsyncMock(return_value=retriever)
    ):
        candidates = await pd_tool.rag_candidate_datasets(
            ["same for 2015", "tree cover loss by driver"]
        )
    assert [str(i) for i in candidates.dataset_id] == [
        ids[0],
        ids[2],
        ids[1],
        ids[3],
    ]


@pytest.mark.asyncio
async def test_resolve_retrieves_with_both_texts():
    from src.agent.subagents.pick_dataset import tool as pd_tool

    rag = AsyncMock(side_effect=RuntimeError("stop after the call"))
    with (
        patch.object(pd_tool, "rag_candidate_datasets", rag),
        pytest.raises(RuntimeError),
    ):
        await pd_tool.DatasetSelector().resolve(
            "tree cover loss by driver", user_message="same for 2015"
        )
    assert rag.await_args.args[0] == [
        "same for 2015",
        "tree cover loss by driver",
    ]
