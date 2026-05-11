import json

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agent.harness.state import AoiRef

_FIXTURES: dict[str, list[AoiRef]] = {
    "para": [
        {
            "name": "Para",
            "source": "gadm",
            "src_id": "BRA.14_1",
            "subtype": "state",
        }
    ],
    "brazil": [
        {
            "name": "Brazil",
            "source": "gadm",
            "src_id": "BRA",
            "subtype": "country",
        }
    ],
    "peru": [
        {
            "name": "Peru",
            "source": "gadm",
            "src_id": "PER",
            "subtype": "country",
        }
    ],
    "amazon": [
        {
            "name": "Amazon Basin",
            "source": "kba",
            "src_id": "amazon_basin",
            "subtype": "kba",
        }
    ],
}


class GeoAgent:
    """Stub geo subagent. Resolves a place query to AoiRefs.

    Will be replaced by a DSPy agent.

    Returns hard-coded fixtures for known names; otherwise a single
    deterministic ref so downstream tools have something to work with.
    """

    async def resolve(self, query: str) -> list[AoiRef]:
        q = (query or "").strip().lower()
        for key, refs in _FIXTURES.items():
            if key in q:
                return refs
        slug = q.replace(" ", "_") or "unknown"
        return [
            {
                "name": query.strip() or "unknown",
                "source": "gadm",
                "src_id": slug.upper(),
                "subtype": None,
            }
        ]


@tool
async def geo_subagent(query: str, runtime: ToolRuntime) -> Command:
    """Resolve a place-name query (e.g. "Para, Brazil", "neighbours of
    Odisha", "1km buffer around Yellowstone") to one or more AOI refs.
    Returns [{name, source, src_id, subtype}]. Updates state.aoi_refs."""
    refs = await GeoAgent().resolve(query)
    ref_dicts = [dict(r) for r in refs]
    runtime.stream_writer({"type": "aoi_resolved", "aoi_refs": ref_dicts})
    return Command(update={
        "aoi_refs": refs,
        "messages": [ToolMessage(
            content=json.dumps(ref_dicts),
            tool_call_id=runtime.tool_call_id,
        )],
    })
