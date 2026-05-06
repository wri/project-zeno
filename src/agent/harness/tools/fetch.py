import hashlib
from datetime import date, timedelta

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.agent.harness.protocol import DataFetchedEvent

_DRIVERS = ["clearing", "fire", "logging", "settlements", "roads"]


def _stat_id(aoi_refs: list[dict], dataset_id: str, dates: tuple) -> str:
    payload = (
        ",".join(sorted(r.get("src_id", "") for r in aoi_refs))
        + f"|{dataset_id}|{dates[0]}|{dates[1]}"
    )
    h = hashlib.sha1(payload.encode()).hexdigest()[:10]
    return f"stat_{h}"


def _synthetic_rows(seed: str, start: str, end: str) -> list[dict]:
    try:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
    except ValueError:
        d0, d1 = date(2024, 1, 1), date(2024, 6, 1)
    if d1 < d0:
        d1 = d0 + timedelta(days=180)

    digest = hashlib.sha1(seed.encode()).digest()
    rows: list[dict] = []
    step = max(1, (d1 - d0).days // max(len(_DRIVERS), 1))
    cur = d0
    for i, driver in enumerate(_DRIVERS):
        area = 100 + digest[i % len(digest)] * (i + 1)
        rows.append(
            {
                "date": cur.isoformat(),
                "driver": driver,
                "area_ha": float(area),
                "confidence": "high",
            }
        )
        cur = min(d1, cur + timedelta(days=step))
    return rows


@tool
async def fetch(
    aoi_refs: list[dict],
    dataset_id: str,
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
    config: RunnableConfig = None,
) -> dict:
    """Pull data for the given AOIs and dataset over the date range.
    Stores rows in the data cache and returns {stat_id, row_count,
    columns, date_range}. The agent never sees raw rows here."""
    session = (config or {}).get("configurable", {}).get("session")
    if session is None:
        raise RuntimeError("fetch tool requires a session in config")

    stat_id = _stat_id(aoi_refs, dataset_id, (start_date, end_date))
    rows = _synthetic_rows(stat_id, start_date, end_date)
    meta = {
        "row_count": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "date_range": [start_date, end_date],
        "dataset_id": dataset_id,
        "aoi_refs": aoi_refs,
    }
    await session.backend.cache_data(stat_id, rows, meta)
    session.emit(DataFetchedEvent(stat_id=stat_id, meta=meta))
    return {"stat_id": stat_id, **meta}
