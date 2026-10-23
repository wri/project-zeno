"""The checks every data pull passes before it reaches the analytics API.

The agent's `pull_data` tool and the MCP server's `pull_data` tool both run
these, so a pull refused in one is refused in the other. `pick_aoi` runs the
area check on a selection before it makes one. A refusal carries an i18n
message key (`src.agent.i18n`) and its arguments rather than text: each
caller renders it in its own language and adds its own context.
"""

from dataclasses import dataclass, field
from typing import Optional

from src.agent.datasets.curated_only import is_curated_only
from src.agent.datasets.dates import revise_date_range
from src.shared.geocoding_helpers import CONCESSION_SOURCES

# The most areas one selection, and so one pull, may hold: administrative
# areas, and every other source (key biodiversity areas, protected areas,
# indigenous lands, concessions).
SUBREGION_LIMIT_ADMIN = 1000
SUBREGION_LIMIT = 50


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


def refuse_areas(aois: list[dict]) -> Optional[PullRefusal]:
    """Refuse a set of areas the analytics handler cannot pull as one.

    The handler takes the area type of the request from the first area, so
    every area must come from one source; and a source has a size limit.
    """
    sources = {aoi["source"] for aoi in aois}
    if len(sources) > 1:
        return PullRefusal("pick_aoi.multiple_sources")
    source = next(iter(sources), None)
    if source in {"kba", "wdpa", "landmark", *CONCESSION_SOURCES}:
        limit = SUBREGION_LIMIT
    else:
        limit = SUBREGION_LIMIT_ADMIN
    if len(aois) <= limit:
        return None
    # A concession expansion stops one row past the limit, so its true
    # count is unknown. The message says so, and that no figure across the
    # area is possible, so the agent does not offer one.
    if source in CONCESSION_SOURCES:
        return PullRefusal("pick_aoi.too_many_concessions", {"limit": limit})
    return PullRefusal(
        "pick_aoi.too_many_subregions",
        {
            "count": len(aois),
            "subregion_limit": SUBREGION_LIMIT,
            "subregion_limit_admin": SUBREGION_LIMIT_ADMIN,
        },
    )


async def plan_pull(
    dataset: dict,
    aois: list[dict],
    start_date: Optional[str],
    end_date: Optional[str],
) -> PullRange | PullRefusal:
    """The date range to pull `dataset` for `aois` with, or why not to.

    The areas must pass `refuse_areas`. A curated-only dataset has no
    comparison view: its charts add up every row of a year, so two areas
    would show as one silent sum. A requested
    range that misses the dataset's coverage entirely is refused rather than
    clamped to an unrelated period.
    """
    refusal = refuse_areas(aois)
    if refusal:
        return refusal
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
