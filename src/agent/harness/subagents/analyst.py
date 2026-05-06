from src.agent.harness.artifact import Artifact
from src.agent.harness.backends.protocol import ZenoBackend


class AnalystAgent:
    """Stub analyst subagent. Builds a deterministic chart Artifact from
    cached data referenced by stat_ids."""

    def __init__(self, backend: ZenoBackend) -> None:
        self.backend = backend

    async def analyze(
        self,
        task: str,
        stat_ids: list[str],
        dataset_id: str | None = None,
        aoi_refs: list[dict] | None = None,
    ) -> Artifact:
        rows: list[dict] = []
        for sid in stat_ids:
            r, _meta = await self.backend.get_data(sid)
            rows.extend(r)

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
