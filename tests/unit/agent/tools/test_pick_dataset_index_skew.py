"""The dataset embeddings index is published separately from the catalog it is
built from (see src/ingest/embed_datasets.py), so the two can fall out of step:
an index built before a dataset was removed keeps returning that dataset's
document. Retrieval must drop such a document and keep the valid candidates,
and it must report the skew.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from src.agent.datasets.config import DATASETS
from src.agent.subagents.pick_dataset.tool import (
    DatasetSelector,
    _log_index_catalog_skew,
    rag_candidate_datasets,
)

CATALOG_IDS = sorted(ds["dataset_id"] for ds in DATASETS)
# An id no catalog dataset uses. 0 was DIST-ALERT, removed in #802, and is
# still present in every index published up to v9.
STALE_ID = 0

pytestmark = pytest.mark.asyncio


def _doc(doc_id):
    return SimpleNamespace(id=str(doc_id))


def _retriever(doc_ids):
    return SimpleNamespace(
        ainvoke=AsyncMock(return_value=[_doc(i) for i in doc_ids])
    )


async def test_stale_document_is_skipped_and_valid_candidates_kept(caplog):
    doc_ids = [STALE_ID] + CATALOG_IDS[:3]
    with patch(
        "src.agent.subagents.pick_dataset.tool._get_retriever",
        AsyncMock(return_value=_retriever(doc_ids)),
    ):
        with caplog.at_level(logging.WARNING):
            candidates = await rag_candidate_datasets(
                "daily deforestation alerts"
            )

    assert list(candidates["dataset_id"]) == CATALOG_IDS[:3]
    assert "Skipped 1 retrieved document" in caplog.text


async def test_non_numeric_document_id_is_skipped():
    with patch(
        "src.agent.subagents.pick_dataset.tool._get_retriever",
        AsyncMock(
            return_value=_retriever(["not-a-dataset-id", CATALOG_IDS[0]])
        ),
    ):
        candidates = await rag_candidate_datasets("tree cover loss")

    assert list(candidates["dataset_id"]) == [CATALOG_IDS[0]]


async def test_no_valid_candidates_returns_message_instead_of_raising():
    """Every retrieved document stale: the turn ends with a plain message, not
    an exception that surfaces a dataset id to the user."""
    with patch(
        "src.agent.subagents.pick_dataset.tool.rag_candidate_datasets",
        AsyncMock(return_value=pd.DataFrame()),
    ):
        command = await DatasetSelector().resolve(
            "daily deforestation alerts", tool_call_id="call-1"
        )

    (message,) = command.update["messages"]
    assert "dataset" not in command.update
    assert "No dataset could be matched" in message.content


async def test_index_catalog_skew_is_reported(caplog):
    index = SimpleNamespace(
        store={str(i): {} for i in [STALE_ID] + CATALOG_IDS[:-1]}
    )
    with caplog.at_level(logging.ERROR):
        _log_index_catalog_skew(index)

    assert "out of step with the catalog" in caplog.text
    assert str(STALE_ID) in caplog.text
    assert str(CATALOG_IDS[-1]) in caplog.text


async def test_matching_index_reports_no_skew(caplog):
    index = SimpleNamespace(store={str(i): {} for i in CATALOG_IDS})
    with caplog.at_level(logging.ERROR):
        _log_index_catalog_skew(index)

    assert "out of step" not in caplog.text
