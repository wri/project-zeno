from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


@tool
async def execute(
    code: str,
    stat_ids: list[str],
    config: RunnableConfig = None,
) -> dict:
    """Run a short pandas snippet against cached data referenced by
    stat_ids. Returns a small JSON-serialisable result. Stub implementation:
    computes summary stats so the orchestrator can answer quick questions
    without invoking the analyst subagent."""
    session = (config or {}).get("configurable", {}).get("session")
    if session is None:
        raise RuntimeError("execute tool requires a session in config")

    rows: list[dict] = []
    for sid in stat_ids:
        r, _meta = await session.backend.get_data(sid)
        rows.extend(r)

    total = sum(float(r.get("area_ha", 0.0)) for r in rows)
    by_driver: dict[str, float] = {}
    for r in rows:
        d = str(r.get("driver", "unknown"))
        by_driver[d] = by_driver.get(d, 0.0) + float(r.get("area_ha", 0.0))

    return {
        "code": code,
        "total_area_ha": round(total, 2),
        "by_driver": {k: round(v, 2) for k, v in by_driver.items()},
        "row_count": len(rows),
    }
