"""The checks every data pull passes before it reaches the analytics API.

The agent's `pull_data` tool and the MCP server's `pull_data` tool both run
these, so a pull refused in one is refused in the other. A refusal carries
an i18n message key (`src.agent.i18n`) and its arguments rather than text:
each caller renders it in its own language and adds its own context.
"""

from dataclasses import dataclass, field
from typing import Optional

from src.agent.datasets.curated_only import is_curated_only
from src.agent.datasets.dates import revise_date_range


@dataclass(frozen=True)
class PullRefusal:
    """Why a pull is refused: an i18n message key and its arguments."""

    key: str
    kwargs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PullRange:
    """The date range a pull runs with, clamped to the dataset's coverage."""

    start_date: str
    end_date: str
    clamped: bool


def refuse_dataset(
    dataset: dict, excluded_datasets: frozenset[str]
) -> Optional[PullRefusal]:
    """Refuse a dataset the caller's profile hides, whichever path it
    arrived by."""
    if dataset.get("dataset_name") in excluded_datasets:
        return PullRefusal(
            "pull_data.dataset_not_available",
            {"dataset_name": dataset["dataset_name"]},
        )
    return None


async def plan_pull(
    dataset: dict,
    aois: list[dict],
    start_date: Optional[str],
    end_date: Optional[str],
) -> PullRange | PullRefusal:
    """The date range to pull `dataset` for `aois` with, or why not to.

    A curated-only dataset has no comparison view: its charts add up every
    row of a year, so two areas would show as one silent sum. A requested
    range that misses the dataset's coverage entirely is refused rather than
    clamped to an unrelated period.
    """
    if is_curated_only(dataset.get("dataset_id")) and len(aois) > 1:
        return PullRefusal(
            "pull_data.single_area_only",
            {"dataset_name": dataset.get("dataset_name", "")},
        )

    effective_start, effective_end, clamped = await revise_date_range(
        start_date,
        end_date,
        dataset["dataset_id"],
        dataset.get("context_layer"),
    )
    if (end_date is not None and end_date < effective_start) or (
        start_date is not None and start_date > effective_end
    ):
        return PullRefusal(
            "pull_data.date_out_of_range",
            {
                "start_date": start_date,
                "end_date": end_date,
                "dataset_name": dataset["dataset_name"],
                "available_start": effective_start,
                "available_end": effective_end,
            },
        )
    return PullRange(effective_start, effective_end, clamped)
