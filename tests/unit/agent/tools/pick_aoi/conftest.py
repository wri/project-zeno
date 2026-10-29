"""Shared pieces for the pick_aoi unit tests.

A candidate row, a patched single-term search, a stubbed small model and a
`Geocoder.lookup` call with its boilerplate filled in — so a test body shows
only the thing it is about.
"""

from importlib import import_module
from typing import Optional

import pandas as pd
from langchain_core.runnables import RunnableLambda

from src.agent import llms
from src.agent.subagents.pick_aoi import Geocoder
from src.shared.aoi_search import PARTIAL_TIER
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
    tier=PARTIAL_TIER,
    leaf=None,
    corrected=False,
    context_hit=False,
):
    """One `search_aois` row.

    The optional columns are present by default because the real search
    always returns them: `bbox` is COALESCEd to the world bbox,
    `similarity_score` is computed for every search by name, `tier` is the
    match tier (a partial match unless given), `leaf` is the stored leaf
    (here the first segment of *name* unless given), `corrected` says
    whether the row came from the miss path and `context_hit` whether a
    typed parent matched it. Pass None for `bbox` or `score` to leave that
    column out, which is how older recorded fixture frames (no `bbox`) are
    reproduced.
    """
    row = {
        "src_id": src_id,
        "name": name,
        "subtype": subtype,
        "source": source,
        "tier": tier,
        "leaf": name.split(",")[0] if leaf is None else leaf,
        "corrected": corrected,
        "context_hit": context_hit,
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
    not among the candidates to play a hallucinated one. `failures` are
    raised by the first calls, in order, before the pick is returned.
    """

    def __init__(self, src_id: Optional[str] = None, failures=()):
        self._src_id = src_id
        self._failures = list(failures)
        self.calls = 0

    def with_structured_output(self, schema):
        if self._src_id is None:
            raise AssertionError("candidate selection must not call a model")
        src_id = self._src_id

        async def _pick(_input):
            self.calls += 1
            if self._failures:
                raise self._failures.pop(0)
            return schema(src_id=src_id)

        return RunnableLambda(_pick)


def _use_small_model(monkeypatch, stub):
    """Route the tool's model calls to `stub`, with no fallback model behind
    it and no wait between retries."""
    monkeypatch.setattr(llms, "SMALL_MODEL", stub)
    monkeypatch.setattr(llms, "SMALL_FALLBACK_MODELS", [])
    monkeypatch.setattr(
        llms, "RETRY_WAIT", {"initial": 0, "max": 0, "jitter": 0}
    )


async def _lookup(places, **kwargs):
    """`Geocoder.lookup`, defaulting the arguments a test is not about."""
    kwargs.setdefault("question", "where is it")
    kwargs.setdefault("tool_call_id", "tc-test")
    return await Geocoder().lookup(places=places, **kwargs)
