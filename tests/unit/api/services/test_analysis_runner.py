import asyncio

import pytest

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.analysis_runner import (
    AnalysisError,
    AnalysisRunner,
    AnalysisTimeoutError,
)
from src.api.services.analyze import AnalyzeResult

USER_ID = "user123"
AOI = {"source": "gadm", "src_id": "BRA", "subtype": "country"}

CHARTS = [
    InsightChart(
        position=0,
        title="Annual Tree Cover Loss",
        chart_type="bar",
        x_axis="tree_cover_loss_year",
        y_axis="area_ha",
        chart_data=[{"tree_cover_loss_year": 2020, "area_ha": 1000.0}],
    )
]


class _Result:
    def __init__(self, success, message=""):
        self.success = success
        self.message = message


class FakeService:
    def __init__(
        self, *, success: bool = True, charts=CHARTS, delay: float = 0
    ):
        self._success = success
        self._charts = charts
        self._delay = delay

    async def analyze(self, aois, dataset_id, start_date, end_date):
        if self._delay:
            await asyncio.sleep(self._delay)
        return AnalyzeResult(
            data=_Result(self._success, "upstream error"),
            charts=self._charts if self._success else [],
        )


class FakePersist:
    """Stands in for `persist_insight`; records calls, returns a fixed id."""

    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, insight, *, user_id, thread_id):
        self.calls.append(
            {"insight": insight, "user_id": user_id, "thread_id": thread_id}
        )
        return "insight-123"


def make_runner(persist, service=None, **kwargs):
    return AnalysisRunner(service or FakeService(), persist=persist, **kwargs)


async def _run(runner, **overrides):
    kwargs = {
        "user_id": USER_ID,
        "aois": [AOI],
        "dataset_id": 4,
        "start_date": "2020-01-01",
        "end_date": "2022-12-31",
    }
    return await runner.run(**{**kwargs, **overrides})


async def test_run_returns_persisted_insight_id():
    persist = FakePersist()
    insight_id = await _run(make_runner(persist))

    assert insight_id == "insight-123"
    assert len(persist.calls) == 1
    assert persist.calls[0]["user_id"] == USER_ID


async def test_run_persists_charts_only_insight():
    persist = FakePersist()
    await _run(make_runner(persist))

    insight = persist.calls[0]["insight"]
    assert len(insight.charts) == 1
    # The /api/analyze path persists charts only; no LLM-generated narrative.
    assert insight.primary_insight == ""
    assert insight.follow_up_suggestions == []


async def test_run_passes_thread_id_through():
    persist = FakePersist()
    await _run(make_runner(persist), thread_id="t-1")

    assert persist.calls[0]["thread_id"] == "t-1"


async def test_run_without_thread_id_persists_empty_string():
    persist = FakePersist()
    await _run(make_runner(persist))

    assert persist.calls[0]["thread_id"] == ""


async def test_run_on_analytics_failure_raises_and_persists_nothing():
    persist = FakePersist()
    runner = make_runner(persist, FakeService(success=False))

    with pytest.raises(AnalysisError):
        await _run(runner)
    assert persist.calls == []


async def test_run_on_service_exception_raises_and_persists_nothing():
    class BoomService:
        async def analyze(self, aois, dataset_id, start_date, end_date):
            raise RuntimeError("analytics api down")

    persist = FakePersist()
    with pytest.raises(AnalysisError):
        await _run(make_runner(persist, BoomService()))
    assert persist.calls == []


async def test_run_on_timeout_raises_timeout_error():
    persist = FakePersist()
    runner = make_runner(persist, FakeService(delay=5), timeout_seconds=0.01)

    with pytest.raises(AnalysisTimeoutError):
        await _run(runner)
    assert persist.calls == []


async def test_run_persistence_error_propagates():
    """A failed persist rolls back atomically and must surface as an error
    (router → 500), not be swallowed into a phantom success."""

    async def boom(insight, *, user_id, thread_id):
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError, match="db down"):
        await _run(make_runner(boom))
