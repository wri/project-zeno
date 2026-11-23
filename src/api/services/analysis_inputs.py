"""Build ``analysis_inputs``, the pulls an insight was computed from.

Each entry describes one data pull (see ``AnalysisInput`` in
``src.api.schemas`` for the shape and the absence convention). Nothing is
stored: an entry is built from a ``Statistics`` dict in agent state or from
the ``statistics`` row an insight links, through the one builder
``input_from_statistics``. The builders return JSON-ready dicts, which the
chat stream and agent state carry.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.base import DataPullResult
from src.api.data_models import InsightOrm, StatisticsOrm
from src.api.repositories.statistics_writer import PulledStatistics
from src.api.schemas import AnalysisInput
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _areas(statistics: dict) -> list[dict]:
    """The areas of a pull, with ids paired to names by position.

    An id is only unique per source, so an area gets an id only with its
    source. When either list is missing or the lengths differ, pairing by
    position could name the wrong area, so every area gets null ids.
    """
    names = statistics.get("aoi_names") or []
    ids = statistics.get("aoi_ids") or []
    sources = statistics.get("aoi_sources") or []
    if len(ids) == len(sources) == len(names):
        return [
            {"name": name, "source": source, "src_id": src_id}
            for name, source, src_id in zip(names, sources, ids)
        ]
    if ids or sources:
        logger.warning(
            "analysis_inputs_area_ids_mismatch",
            statistics_id=statistics.get("id"),
            names=len(names),
            ids=len(ids),
            sources=len(sources),
        )
    return [{"name": name, "source": None, "src_id": None} for name in names]


def input_from_statistics(statistics: dict) -> dict:
    """The entry for one pull, from its ``Statistics`` dict (see
    ``statistics_dict`` for a database row). The dates are the pull's;
    the canopy cover is the threshold it sent, as stored, never worked out
    again."""
    return AnalysisInput(
        areas=_areas(statistics),
        dataset_id=statistics.get("dataset_id"),
        dataset_name=statistics["dataset_name"],
        pulled_start_date=statistics["start_date"],
        pulled_end_date=statistics["end_date"],
        canopy_cover=statistics.get("canopy_cover"),
        context_layer=statistics.get("context_layer"),
    ).model_dump(mode="json")


def named_areas(
    pairs: list[tuple[str, str]], names: dict[tuple[str, str], str]
) -> list[dict]:
    """Areas for ``(source, src_id)`` pairs, named from ``names``.

    An area with no name found is named by its src_id, as the analytics
    handler names it, and the gap is logged.
    """
    areas = []
    for source, src_id in pairs:
        name = names.get((source, src_id))
        if name is None:
            logger.warning(
                "analysis_inputs_area_name_missing",
                source=source,
                src_id=src_id,
            )
            name = src_id
        areas.append({"name": name, "source": source, "src_id": src_id})
    return areas


def pulled_statistics(
    result: DataPullResult,
    *,
    dataset_id: int,
    areas: list[dict],
    start_date: str,
    end_date: str,
    context_layer: Optional[str],
    canopy_cover: Optional[int],
) -> PulledStatistics:
    """The statistics record of a pull made from explicit options
    (``/api/analyze``, dashboard templates).

    ``canopy_cover`` is the threshold the caller asked for, which the
    selection records as ``parameters``; the threshold the pull sent is
    ``result.canopy_cover``. The dataset name is the catalog's.
    """
    record = next((d for d in DATASETS if d["dataset_id"] == dataset_id), None)
    if record is None:
        raise ValueError(f"Dataset not found: {dataset_id}")
    return PulledStatistics(
        dataset_id=dataset_id,
        dataset_name=record["dataset_name"],
        start_date=start_date,
        end_date=end_date,
        source_url=result.analytics_api_url,
        areas=areas,
        parameters=(
            None
            if canopy_cover is None
            else [{"name": "canopy_cover", "values": [canopy_cover]}]
        ),
        context_layer=context_layer,
        canopy_cover=result.canopy_cover,
    )


def inputs_from_statistics(statistics: list[dict]) -> Optional[list[dict]]:
    """The entries for these pulls, in order, with repeats dropped.

    The same pull can be in state twice (the user asked for it again), and
    one entry says it. None when there are no pulls: an empty list would
    read as "computed from nothing".
    """
    entries: list[dict] = []
    for stat in statistics:
        entry = input_from_statistics(stat)
        if entry not in entries:
            entries.append(entry)
    return entries or None


def statistics_dict(row: StatisticsOrm) -> dict:
    """The keys of a ``Statistics`` dict that ``input_from_statistics``
    reads, from a ``statistics`` row."""
    return {
        "id": str(row.id),
        "dataset_id": row.dataset_id,
        "dataset_name": row.dataset_name,
        "start_date": row.start_date,
        "end_date": row.end_date,
        "aoi_names": row.aoi_names,
        "aoi_ids": row.aoi_ids,
        "aoi_sources": row.aoi_sources,
        "context_layer": row.context_layer,
        "canopy_cover": row.canopy_cover,
    }


async def inputs_by_insight(
    session, rows: list[InsightOrm]
) -> dict[UUID, Optional[list[dict]]]:
    """The ``analysis_inputs`` of each insight, from the pulls it links, in
    one query.

    None for an insight whose links are not exact (see
    ``InsightOrm.statistics_ids_exact``) or whose linked rows are not all
    found: entries for only some of the pulls would label the insight with
    a partial set. Otherwise one entry per linked row, in
    ``statistics_ids`` order, a repeated id once.
    """
    wanted = {
        statistics_id
        for row in rows
        if row.statistics_ids_exact
        for statistics_id in row.statistics_ids or []
    }
    found: dict[str, StatisticsOrm] = {}
    if wanted:
        result = await session.execute(
            select(StatisticsOrm).where(
                StatisticsOrm.id.in_([UUID(i) for i in wanted])
            )
        )
        found = {str(stat.id): stat for stat in result.scalars().all()}

    inputs: dict[UUID, Optional[list[dict]]] = {}
    for row in rows:
        if not row.statistics_ids_exact:
            inputs[row.id] = None
            continue
        ids = list(dict.fromkeys(row.statistics_ids or []))
        missing = [i for i in ids if i not in found]
        if missing:
            logger.warning(
                "analysis_inputs_statistics_missing",
                insight_id=str(row.id),
                statistics_ids=missing,
            )
            inputs[row.id] = None
            continue
        inputs[row.id] = inputs_from_statistics(
            [statistics_dict(found[i]) for i in ids]
        )
    return inputs


async def recorded_inputs(row: InsightOrm) -> Optional[list[dict]]:
    """The ``analysis_inputs`` of one insight, for the agent tools that put
    a stored insight back on screen."""
    async with get_session_from_pool() as session:
        return (await inputs_by_insight(session, [row]))[row.id]
