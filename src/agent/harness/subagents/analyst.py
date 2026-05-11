import json

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.store.base import BaseStore
from langgraph.types import Command

from src.agent.harness.artifact import Artifact


class AnalystAgent:
    """Stub analyst subagent. Builds a deterministic chart Artifact from
    cached data referenced by stat_ids stored in LangGraph Store.

    Will be replaced by a DSPy agent.
    """

    def __init__(self, store: BaseStore) -> None:
        self.store = store

    async def analyze(
        self,
        task: str,
        stat_ids: list[str],
        dataset_id: str | None = None,
        aoi_refs: list[dict] | None = None,
    ) -> Artifact:
        rows: list[dict] = []
        for sid in stat_ids:
            items = await self.store.aget(("data",), sid)
            if items is not None:
                stored = items.value
                rows.extend(stored.get("rows", []))

        agg: dict[str, float] = {}
        for row in rows:
            key = str(row.get("driver", "unknown"))
            agg[key] = agg.get(key, 0.0) + float(row.get("area_ha", 0.0))

        chart_data = [
            {"driver": k, "area_ha": round(v, 2)}
            for k, v in sorted(agg.items(), key=lambda kv: -kv[1])
        ]
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "mark": "bar",
            "encoding": {
                "x": {"field": "driver", "type": "nominal"},
                "y": {"field": "area_ha", "type": "quantitative"},
            },
        }
        total = round(sum(agg.values()), 2)
        top = chart_data[0]["driver"] if chart_data else "n/a"
        insight = (
            f"Total area: {total} ha across {len(chart_data)} drivers. "
            f"Largest driver: {top}."
        )
        title = task.strip() or "Analysis"

        return Artifact(
            type="chart",
            title=title,
            query=task,
            inputs={
                "stat_ids": list(stat_ids),
                "dataset_id": dataset_id,
                "aoi_refs": list(aoi_refs or []),
            },
            content={"spec": spec, "data": chart_data, "insight": insight},
            code=[
                {
                    "type": "code",
                    "content": (
                        "df.groupby('driver')['area_ha'].sum()"
                        ".sort_values(ascending=False)"
                    ),
                }
            ],
            follow_ups=[
                "Show this as a pie chart",
                "Filter to top 3 drivers",
                "Compare to a neighbouring region",
            ],
        )


@tool
async def analyst_subagent(
    task: str,
    stat_ids: list[str],
    dataset_id: str = "",
    aoi_refs: list[dict] | None = None,
    runtime: ToolRuntime = None,
) -> Command:
    """Build a chart artifact answering `task` from cached data
    referenced by stat_ids. Returns artifact summary and updates
    state.artifact_ids."""
    analyst = AnalystAgent(store=runtime.store)
    artifact = await analyst.analyze(
        task=task,
        stat_ids=stat_ids,
        dataset_id=dataset_id or None,
        aoi_refs=aoi_refs,
    )
    await runtime.store.aput(("artifacts",), artifact.id, artifact.to_dict())
    runtime.stream_writer({
        "type": "artifact",
        "artifact": artifact.to_dict(),
    })
    summary = {
        "artifact_id": artifact.id,
        "title": artifact.title,
        "type": artifact.type,
        "follow_ups": artifact.follow_ups,
    }
    return Command(update={
        "artifact_ids": [artifact.id],
        "messages": [ToolMessage(
            content=json.dumps(summary),
            tool_call_id=runtime.tool_call_id,
        )],
    })
