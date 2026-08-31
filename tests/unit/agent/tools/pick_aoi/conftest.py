"""Shared pieces for the pick_aoi unit tests.

A candidate row, a patched single-term search, a stubbed small model and a
`Geocoder.lookup` call with its boilerplate filled in — so a test body shows
only the thing it is about.
"""

from importlib import import_module
from typing import Optional

import pandas as pd

from src.agent.subagents.pick_aoi import Geocoder
from src.shared.geocoding_helpers import WORLD_BBOX

# The module that imports `query_aoi_database`, which is where it has to be
# patched: patching it on `geocoding_helpers` would pass vacuously.
tool_module = import_module("src.agent.subagents.pick_aoi.tool")


def _row(
    src_id,
    name,
    source="gadm",
    subtype="country",
    score=0.5,
    bbox=WORLD_BBOX,
):
    """One `search_aois` row.

    Both optional columns are present by default because the real search
    always returns them: `bbox` is COALESCEd to the world bbox, and
    `similarity_score` is computed for every search by name. Pass None for
    either to leave that column out, which is how the recorded fixture frames
    (no `bbox`) are reproduced.
    """
    row = {
        "src_id": src_id,
        "name": name,
        "subtype": subtype,
        "source": source,
    }
    if bbox is not None:
        row["bbox"] = bbox
    if score is not None:
        row["similarity_score"] = score
    return row


def _patch_search(monkeypatch, responder):
    """Patch the single-term search and record every call it receives.

    `responder` is either a `{place_name: rows}` mapping, or a callable
    `(place_name, aoi_type) -> rows` for the tests whose answer depends on the
    source the search was narrowed to.

    Returns the list of `(place_name, aoi_type, result_limit)` calls.
    """
    calls: list[tuple] = []
    rows_for = (
        responder
        if callable(responder)
        else lambda place_name, aoi_type: responder.get(place_name, [])
    )

    async def fake_query_aoi_database(place_name, aoi_type, result_limit=10):
        calls.append((place_name, aoi_type, result_limit))
        return pd.DataFrame(rows_for(place_name, aoi_type))

    monkeypatch.setattr(
        tool_module, "query_aoi_database", fake_query_aoi_database
    )
    return calls


class _SmallModelStub:
    """Stands in for SMALL_MODEL.

    Built without a `src_id` it fails the test on any attempt to use it, which
    is how the deterministic path proves no model is reachable during
    selection. Given one, it plays the model's pick — pass a src_id that is
    not among the candidates to play a hallucinated one.
    """

    def __init__(self, src_id: Optional[str] = None):
        self._src_id = src_id

    def with_structured_output(self, schema):
        if self._src_id is None:
            raise AssertionError("candidate selection must not call a model")
        src_id = self._src_id

        async def _pick(_input):
            return schema(src_id=src_id)

        return _pick


async def _lookup(places, **kwargs):
    """`Geocoder.lookup`, defaulting the arguments a test is not about."""
    kwargs.setdefault("question", "where is it")
    kwargs.setdefault("tool_call_id", "tc-test")
    return await Geocoder().lookup(places=places, **kwargs)
