"""Turn pulled rows into finished curated charts.

The one place a generator is matched and its message keys are localised.
`AnalyzeService` (REST) and the agent's `generate_insights` both call it,
so the two paths cannot fork.

Chart colors are not resolved here: `resolve_chart_colors` keys `color_map`
off a `{column}__slug` sibling column that only the code-executor path
emits, so calling it here after localisation would key the map off
already-translated display labels instead of stable slugs. Colors for
curated charts are follow-up work.
"""

from typing import Optional, Sequence

from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator
from src.api.services.charts.registry import DETERMINISTIC_GENERATORS


async def _localise(
    charts: list[InsightChart],
    generator: ChartGenerator,
    language: Optional[str],
) -> None:
    """Resolve the message keys a generator emits into display text.

    Generators stay synchronous and dataset-focused; rendering their
    titles and category labels in the reader's language belongs here.
    An unknown key keeps the generator's own text rather than blanking.
    """
    language = language or DEFAULT_LANGUAGE
    for chart in charts:
        chart.title = await t(chart.title, language) or chart.title
        for column in generator.label_fields:
            for row in chart.chart_data:
                if column in row:
                    row[column] = await t(row[column], language) or row[column]


async def build_curated_charts(
    dataset_id: int,
    rows: list[dict],
    language: Optional[str] = None,
    generators: Sequence[ChartGenerator] = DETERMINISTIC_GENERATORS,
) -> list[InsightChart]:
    """Curated charts for `dataset_id` from `rows`; [] when no generator
    handles the dataset. Charts carry `dataset_id`."""
    for generator in generators:
        if generator.can_handle(dataset_id):
            charts = generator.generate(rows)
            await _localise(charts, generator, language)
            for chart in charts:
                chart.dataset_id = dataset_id
            return charts
    return []
