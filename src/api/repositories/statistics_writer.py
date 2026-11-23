"""The one place a data pull is written as a `StatisticsOrm` row.

The agent's `pull_data`, `/api/analyze` and the dashboard templates all pull
data, and an insight links the rows of the pulls it was computed from through
`statistics_ids`. One writer keeps those rows alike.
"""

from typing import NamedTuple, Optional

from src.api.data_models import StatisticsOrm
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class PulledStatistics(NamedTuple):
    """What one pull records: the dates it used, where its result is, and
    what it asked for. `areas` are dicts with `name`, `source` and `src_id`.
    `canopy_cover` is the threshold the pull sent, `parameters` what the
    selection set."""

    dataset_id: Optional[int]
    dataset_name: str
    start_date: str
    end_date: str
    source_url: Optional[str]
    areas: list[dict]
    parameters: Optional[list[dict]]
    context_layer: Optional[str]
    canopy_cover: Optional[int]


def add_statistics_row(
    session,
    pull: PulledStatistics,
    *,
    user_id: Optional[str],
    thread_id: Optional[str],
) -> StatisticsOrm:
    """Add the row of one pull to `session`; the caller commits.

    Lets another writer put the row in the transaction of the insight that
    links it. The row keeps the areas as three parallel lists.
    """
    row = StatisticsOrm(
        user_id=user_id,
        thread_id=thread_id,
        dataset_id=pull.dataset_id,
        dataset_name=pull.dataset_name,
        start_date=pull.start_date,
        end_date=pull.end_date,
        source_url=pull.source_url,
        aoi_names=[a["name"] for a in pull.areas],
        aoi_ids=[a["src_id"] for a in pull.areas],
        aoi_sources=[a["source"] for a in pull.areas],
        parameters=pull.parameters,
        context_layer=pull.context_layer,
        canopy_cover=pull.canopy_cover,
    )
    session.add(row)
    return row


async def persist_statistics(
    pull: PulledStatistics, *, user_id: Optional[str], thread_id: Optional[str]
) -> str:
    """Write the row of one pull in its own transaction; return its id."""
    async with get_session_from_pool() as session:
        row = add_statistics_row(
            session, pull, user_id=user_id, thread_id=thread_id
        )
        await session.flush()
        statistics_id = str(row.id)
        await session.commit()
    logger.info("statistics_persisted", statistics_id=statistics_id)
    return statistics_id
