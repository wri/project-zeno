"""Turn pulled rows into finished curated charts.

The one place a generator is matched and its message keys are localised.
`AnalyzeService` (REST) and the agent's `generate_insights` both call it,
so the two paths cannot fork.

Chart colors are not resolved here: `resolve_chart_colors` keys `color_map`
off a `{column}__slug` sibling column that only the code-executor path
emits, so calling it here after localisation would key the map off
already-translated display labels instead of stable slugs. Colors for
curated charts are follow-up work. A generator may set its own `color_map`
keyed by its series; `_localise` renames those keys with the series.
"""

from typing import Optional, Sequence

from src.agent.datasets.config import DATASETS
from src.agent.i18n import MESSAGES, t
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator
from src.api.services.charts.registry import DETERMINISTIC_GENERATORS
from src.api.services.charts.views import view_for_title


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
        if generator.label_series:
            await _localise_series(chart, language)


async def _localise_series(chart: InsightChart, language: str) -> None:
    """Rename each series key to its display text in `series_fields`, in
    the row columns and in `color_map` at once, so the three keep matching.
    Two keys with the same text would merge their columns, so that raises.
    """
    names = {key: await t(key, language) or key for key in chart.series_fields}
    if len(set(names.values())) != len(names):
        raise ValueError(f"Series names are not unique: {names}")
    chart.series_fields = [names[key] for key in chart.series_fields]
    chart.chart_data = [
        {names.get(key, key): value for key, value in row.items()}
        for row in chart.chart_data
    ]
    chart.color_map = {
        names.get(key, key): color for key, color in chart.color_map.items()
    }


async def context_layer_label(
    context_layer: Optional[str], language: Optional[str]
) -> Optional[str]:
    """The name of a context layer in `language`; the raw value without
    underscores when it has no message."""
    if not context_layer:
        return None
    key = f"context_layer.{context_layer}"
    if key in MESSAGES:
        return await t(key, language or DEFAULT_LANGUAGE)
    return context_layer.replace("_", " ")


def dataset_context_layer(
    dataset_id: Optional[int], context_layer: Optional[str]
) -> Optional[str]:
    """`context_layer` when it is one of the dataset's context layers in
    the catalog; else None. A pull can carry another value: the driver
    dataset always has "driver", which selects the driver intersection
    (src/agent/subagents/pick_dataset/schema.py). A title, a caption or a
    tool message must not name it as a context layer."""
    if not context_layer or dataset_id is None:
        return None
    dataset = next(
        (d for d in DATASETS if d["dataset_id"] == dataset_id), None
    )
    layers = (dataset or {}).get("context_layers") or []
    if any(layer.get("value") == context_layer for layer in layers):
        return context_layer
    return None


async def build_curated_charts(
    dataset_id: int,
    rows: list[dict],
    language: Optional[str] = None,
    generators: Sequence[ChartGenerator] = DETERMINISTIC_GENERATORS,
    titles: Optional[Sequence[str]] = None,
    period: Optional[tuple[str, str]] = None,
    context_layer: Optional[str] = None,
) -> list[InsightChart]:
    """Curated charts for `dataset_id` from `rows`; [] when no generator
    handles the dataset. Charts carry `dataset_id` and, for a chart in the
    view registry, `view_id` and `view_revision`. `titles` keeps only
    the charts with those title keys; None keeps them all. `period` is the
    start and end date of the pull, for a chart whose axis spans it.
    `context_layer` is the context layer of the pull: each title then
    names it, as in "Annual Tree Cover Loss (primary forest)"."""
    for generator in generators:
        if generator.can_handle(dataset_id):
            if period is not None:
                generator = generator.for_period(*period)
            charts = generator.generate(rows)
            # Before _localise, while the titles are still keys.
            for chart in charts:
                view = view_for_title(chart.title)
                if view is not None:
                    chart.view_id = view.id
                    chart.view_revision = view.revision
            if titles is not None:
                charts = [chart for chart in charts if chart.title in titles]
                for position, chart in enumerate(charts):
                    chart.position = position
            await _localise(charts, generator, language)
            layer = await context_layer_label(
                dataset_context_layer(dataset_id, context_layer), language
            )
            for chart in charts:
                chart.dataset_id = dataset_id
                if layer:
                    chart.title = f"{chart.title} ({layer})"
            return charts
    return []
