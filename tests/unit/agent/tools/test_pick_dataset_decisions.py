"""select_best_dataset asks the jev decision model: the dataset from all
datasets of the profile, then the options of that dataset. RAG and the
selection LLM are the fallback when a decision call fails."""

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from src.agent.datasets.config import DATASETS
from src.agent.subagents.pick_dataset import tool as tool_module
from src.agent.subagents.pick_dataset.schema import DatasetSelectionResponse
from src.shared.decisions import Answer, DecisionError

BY_ID = {ds["dataset_id"]: ds for ds in DATASETS}
TREE_COVER_LOSS = 4
FIRES = 10
LAND_COVER = 1
LGMS = 12


def _candidates(*ids):
    return pd.DataFrame([BY_ID[i] for i in ids])


def _key(dataset_id):
    return BY_ID[dataset_id]["decision_key"]


def _answer(choice, probabilities=None):
    probabilities = probabilities or {choice: 0.9}
    return Answer(
        choice=choice,
        probability=probabilities[choice],
        probabilities=probabilities,
    )


def _decide_returns(answers):
    """A fake decide that answers each question it is asked from `answers`
    and records each call."""
    calls = []

    async def fake_decide(state, questions, client=None):
        calls.append((state, questions))
        return {k: v for k, v in answers.items() if k in questions}

    return fake_decide, calls


def test_every_catalog_dataset_has_a_decision_key_and_card():
    keys = [ds.get("decision_key") for ds in DATASETS]
    assert all(keys) and len(set(keys)) == len(keys)
    assert all(k.replace("_", "").isalnum() and k.islower() for k in keys)
    assert all(ds.get("decision_card") for ds in DATASETS)
    assert tool_module.NO_DATASET not in keys


async def test_picks_the_dataset_then_asks_its_options():
    fake, calls = _decide_returns(
        {
            "dataset": _answer(_key(TREE_COVER_LOSS)),
            "context": _answer("primary_forest"),
            "param_canopy_cover": _answer("50"),
        }
    )
    with patch.object(tool_module, "decide", fake):
        result = await tool_module.select_best_dataset(
            "primary forest loss at 50% canopy",
            _candidates(TREE_COVER_LOSS, FIRES, LAND_COVER),
            start_date="2020-01-01",
            end_date="2023-12-31",
        )

    option = result.selected_dataset
    assert option.dataset_id == TREE_COVER_LOSS
    assert option.context_layer == "primary_forest"
    assert [(p.name, p.values) for p in option.parameters] == [
        ("canopy_cover", [50])
    ]
    assert result.suggested_datasets is None

    # Call 1 asks the dataset alone, with the catalog cards as options.
    (state, first), (state2, second) = calls
    assert set(first) == {"dataset"}
    assert (
        first["dataset"].options[_key(TREE_COVER_LOSS)]
        == (BY_ID[TREE_COVER_LOSS]["decision_card"])
    )
    assert tool_module.NO_DATASET in first["dataset"].options
    assert "primary forest loss at 50% canopy" in state
    assert "2020-01-01 to 2023-12-31" in state
    # Call 2 asks only the options of the chosen dataset.
    assert set(second) == {"context", "param_canopy_cover"}
    assert state2 == state


async def test_a_dataset_without_options_needs_one_call():
    fake, calls = _decide_returns({"dataset": _answer(_key(LAND_COVER))})
    with patch.object(tool_module, "decide", fake):
        result = await tool_module.select_best_dataset(
            "land cover", _candidates(TREE_COVER_LOSS, LAND_COVER)
        )

    assert result.selected_dataset.dataset_id == LAND_COVER
    assert len(calls) == 1


async def test_default_answers_leave_the_options_unset():
    fake, _ = _decide_returns(
        {
            "dataset": _answer(_key(TREE_COVER_LOSS)),
            "context": _answer(tool_module.NO_CONTEXT),
            "param_canopy_cover": _answer(tool_module.NO_PARAMETER),
        }
    )
    with patch.object(tool_module, "decide", fake):
        result = await tool_module.select_best_dataset(
            "tree cover loss", _candidates(TREE_COVER_LOSS, FIRES)
        )

    option = result.selected_dataset
    assert option.context_layer is None
    assert option.parameters is None


async def test_asks_for_the_map_layer_of_a_multi_layer_dataset():
    fake, calls = _decide_returns(
        {"dataset": _answer(_key(LGMS)), "layer": _answer("livestock")}
    )
    with patch.object(tool_module, "decide", fake):
        result = await tool_module.select_best_dataset(
            "livestock emissions", _candidates(LGMS, LAND_COVER)
        )

    assert result.selected_dataset.selected_layer == "livestock"
    (_, second) = calls[1]
    assert set(second["layer"].options) == {
        layer["name"] for layer in BY_ID[LGMS]["layers"]
    }


async def test_a_low_top_probability_offers_the_closest_datasets():
    fake, calls = _decide_returns(
        {
            "dataset": _answer(
                _key(FIRES),
                {
                    _key(FIRES): 0.45,
                    _key(TREE_COVER_LOSS): 0.4,
                    _key(LAND_COVER): 0.03,
                    tool_module.NO_DATASET: 0.12,
                },
            ),
        }
    )
    with patch.object(tool_module, "decide", fake):
        result = await tool_module.select_best_dataset(
            "fire emissions",
            _candidates(TREE_COVER_LOSS, FIRES, LAND_COVER),
        )

    assert result.selected_dataset is None
    assert [o.dataset_id for o in result.suggested_datasets] == [
        FIRES,
        TREE_COVER_LOSS,
    ]
    assert all(o.reason for o in result.suggested_datasets)
    assert len(calls) == 1


async def test_a_decline_suggests_the_closest_candidates():
    fake, _ = _decide_returns(
        {
            "dataset": _answer(
                tool_module.NO_DATASET,
                {
                    tool_module.NO_DATASET: 0.6,
                    _key(FIRES): 0.3,
                    _key(TREE_COVER_LOSS): 0.08,
                    _key(LAND_COVER): 0.02,
                },
            ),
        }
    )
    with patch.object(tool_module, "decide", fake):
        result = await tool_module.select_best_dataset(
            "fire emissions on grassland",
            _candidates(TREE_COVER_LOSS, FIRES, LAND_COVER),
        )

    assert result.selected_dataset is None
    assert [o.dataset_id for o in result.suggested_datasets] == [
        FIRES,
        TREE_COVER_LOSS,
    ]
    assert result.reason


async def test_a_decline_with_no_close_candidate_suggests_nothing():
    fake, _ = _decide_returns(
        {
            "dataset": _answer(
                tool_module.NO_DATASET,
                {tool_module.NO_DATASET: 0.98, _key(LAND_COVER): 0.02},
            ),
        }
    )
    with patch.object(tool_module, "decide", fake):
        result = await tool_module.select_best_dataset(
            "ocean temperature", _candidates(LAND_COVER, FIRES)
        )

    assert result.selected_dataset is None
    assert result.suggested_datasets is None


@pytest.mark.parametrize(
    "failure",
    [
        AsyncMock(side_effect=DecisionError("decisions call failed (503)")),
        AsyncMock(return_value={}),
    ],
)
async def test_falls_back_to_rag_and_the_selection_model(failure):
    fallback = DatasetSelectionResponse(reason="from the model")
    shortlist = _candidates(TREE_COVER_LOSS, FIRES)
    with (
        patch.object(tool_module, "decide", failure),
        patch.object(
            tool_module,
            "rag_candidate_datasets",
            AsyncMock(return_value=shortlist),
        ) as rag,
        patch.object(
            tool_module, "_select_with_llm", AsyncMock(return_value=fallback)
        ) as llm,
    ):
        result = await tool_module.select_best_dataset(
            "tree cover loss", _candidates(TREE_COVER_LOSS, FIRES, LAND_COVER)
        )

    assert result is fallback
    rag.assert_awaited_once()
    llm.assert_awaited_once()
    assert list(llm.await_args.args[1]["dataset_id"]) == [
        TREE_COVER_LOSS,
        FIRES,
    ]
