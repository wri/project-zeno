"""Build the ``analysis_inputs`` snapshot an insight is saved with.

Each entry describes one data pull (see ``AnalysisInput`` in
``src/api/schemas.py`` for the shape and the absence convention). The
builders return JSON-ready dicts: the one value that is stored on the
insight, sent on the chat stream and kept in agent state.
"""

from typing import Optional

from src.agent.datasets.handlers.analytics_handler import (
    canopy_cover_threshold,
    with_catalog_record,
)
from src.api.schemas import AnalysisInput
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def analysis_input(
    *,
    areas: list[dict],
    dataset_id: Optional[int],
    dataset_name: str,
    start_date: str,
    end_date: str,
    canopy_cover: Optional[int],
    context_layer: Optional[str],
) -> dict:
    """One entry. ``areas`` items carry ``name``, ``source`` and
    ``src_id``."""
    return AnalysisInput(
        areas=areas,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        start_date=start_date,
        end_date=end_date,
        canopy_cover=canopy_cover,
        context_layer=context_layer,
    ).model_dump(mode="json")


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
    """The entry for one pull, from its ``Statistics`` dict in state.

    ``pull_data`` stores the selection's ``parameters`` as it sent them,
    so the canopy rule reads them without a catalog merge.
    """
    return analysis_input(
        areas=_areas(statistics),
        dataset_id=statistics.get("dataset_id"),
        dataset_name=statistics["dataset_name"],
        start_date=statistics["start_date"],
        end_date=statistics["end_date"],
        canopy_cover=canopy_cover_threshold(
            statistics.get("dataset_id"),
            statistics.get("context_layer"),
            statistics.get("parameters"),
        ),
        context_layer=statistics.get("context_layer"),
    )


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


def input_for_analysis(
    *,
    areas: list[dict],
    dataset_id: int,
    start_date: str,
    end_date: str,
    canopy_cover: Optional[int],
    context_layer: Optional[str],
) -> dict:
    """The entry for a pull made from explicit options (``/api/analyze``,
    dashboard templates). ``canopy_cover`` is the threshold the pull sent
    (see ``sent_canopy_cover`` in ``src.api.services.analyze``)."""
    return analysis_input(
        areas=areas,
        dataset_id=dataset_id,
        dataset_name=with_catalog_record({"dataset_id": dataset_id})[
            "dataset_name"
        ],
        start_date=start_date,
        end_date=end_date,
        canopy_cover=canopy_cover,
        context_layer=context_layer,
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
