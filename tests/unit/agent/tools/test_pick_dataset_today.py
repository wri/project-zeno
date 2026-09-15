"""The dataset selector sees each dataset's coverage as free text ("1 December
2023 - present") and nothing else about time. Without a date in its prompt the
model read "present" against its own training-time present and refused
disturbance alerts for the current year as "in the future" (production trace
099ba22993ccae4e61056626213ee5f0, 2026-09-15). The selector must be told
today's date, and the date it is told must be the one the caller chose.
"""

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest
from langchain_core.runnables import RunnableLambda

from src.agent.datasets.config import DATASETS
from src.agent.subagents.pick_dataset import tool as pick_dataset_tool
from src.agent.subagents.pick_dataset.schema import DatasetSelectionResponse

pytestmark = pytest.mark.asyncio


def _capturing_model(captured: list):
    """Stands in for SMALL_MODEL: records the rendered prompt, answers case C."""

    def _run(prompt_value):
        captured.append(prompt_value.to_messages())
        return DatasetSelectionResponse(
            selected_dataset=None, suggested_datasets=None, reason="captured"
        )

    class _Model:
        def with_structured_output(self, schema):
            return RunnableLambda(_run)

    return _Model()


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [d for d in DATASETS if d["dataset_name"] == "Integrated alerts"]
    )


async def _system_prompt(**kwargs) -> str:
    captured: list = []
    with patch.object(
        pick_dataset_tool, "SMALL_MODEL", _capturing_model(captured)
    ):
        await pick_dataset_tool.select_best_dataset(
            "disturbance alerts for 2026",
            _candidates(),
            "2026-01-01",
            "2026-12-31",
            **kwargs,
        )
    (messages,) = captured
    return messages[0].content


async def test_selector_prompt_states_the_date_it_was_given():
    system = await _system_prompt(today=date(2026, 9, 15))
    assert "Today is 2026-09-15" in system


async def test_selector_prompt_reads_present_against_today():
    system = await _system_prompt(today=date(2026, 9, 15))
    assert 'ends in "present" runs up to today' in system


async def test_selector_prompt_defaults_to_the_real_today():
    system = await _system_prompt()
    assert f"Today is {date.today().isoformat()}" in system
