"""Run an analysis template against a dashboard.

``apply_template`` is the one builder for every template. The API endpoint
and the agent tool both call it.

1. Take the first AOI of the dashboard.
2. Resolve "today" one time for the request, and get the period from the
   template arguments.
3. Build every widget concurrently. Each widget builder clamps the period to
   its dataset and gets its own copy of the AOI, because the analytics
   handler changes its input in place (it strips the GADM level suffix).
   A builder returns data. It does not write to the database.
4. A failed required widget stops the build with nothing written. A failed
   optional widget adds a warning and is left out.
5. Write the title and the description (``text``).
6. Write the section, its widgets and the new insights in one transaction.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime
from types import SimpleNamespace
from typing import Awaitable, Callable, Optional

import pandas as pd

from src.agent.datasets.config import DATASETS
from src.agent.datasets.dates import revise_date_range
from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler
from src.agent.imagery import ImageryRequest, Sentinel2ImageryProvider
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.subagents.analyst.charts import Insight, InsightChart
from src.agent.subagents.pick_dataset.tool import (
    get_tile_services_for_dataset,
)
from src.api.data_models import DashboardOrm
from src.api.repositories import dashboard_writer
from src.api.repositories.dashboard_writer import SectionWidget
from src.api.services.analysis_templates.models import (
    AnalysisTemplate,
    ChartWidgetSpec,
    ImageryWidgetSpec,
    LayerWidgetSpec,
    TemplateArgs,
)
from src.api.services.analysis_templates.text import generate_section_text
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import DETERMINISTIC_GENERATORS
from src.api.services.charts.curated import build_curated_charts
from src.api.services.widget_configs import (
    dataset_config,
    imagery_config,
    widget_config,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class TemplateError(Exception):
    """The build cannot finish. Nothing was written."""


class NoAreaError(TemplateError):
    """The dashboard has no AOI to build the section for."""


class WidgetFailedError(TemplateError):
    """A required widget failed, for example the analytics pull."""


class DashboardGoneError(TemplateError):
    """The dashboard was deleted during the build."""


@dataclass
class TemplateResult:
    section_id: str
    widget_ids: list[str]
    title: str
    description: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BuildContext:
    """What every widget builder reads. ``aoi`` is the dashboard's first
    AOI as a reference dict; a builder must copy it before use."""

    aoi: dict
    start: date
    end: date
    language: str


@dataclass
class BuiltWidget:
    """A widget ready to write, and the facts the text model reads."""

    widget: SectionWidget
    # One line for the text prompt, e.g. "chart: Integrated alerts".
    summary: str
    charts: list[InsightChart] = field(default_factory=list)


def _dataset_record(dataset_id: int) -> dict:
    record = next((d for d in DATASETS if d["dataset_id"] == dataset_id), None)
    if record is None:
        raise WidgetFailedError(f"Dataset {dataset_id} is not in the catalog.")
    return record


async def _period(dataset_id: int, context: BuildContext) -> tuple[str, str]:
    """The requested period, clamped to the dataset's range."""
    start, end, _ = await revise_date_range(
        context.start.isoformat(),
        context.end.isoformat(),
        dataset_id,
    )
    return start, end


async def _build_chart(
    spec: ChartWidgetSpec, context: BuildContext
) -> BuiltWidget:
    record = _dataset_record(spec.dataset_id)
    start, end = await _period(spec.dataset_id, context)
    service = AnalyzeService(AnalyticsHandler(), DETERMINISTIC_GENERATORS)
    result = await service.analyze(
        aois=[dict(context.aoi)],
        dataset_id=spec.dataset_id,
        start_date=start,
        end_date=end,
        language=context.language,
    )
    if not result.data.success:
        raise WidgetFailedError(
            f"Could not get {record['dataset_name']} data for "
            f"'{context.aoi['name']}': {result.data.message}"
        )
    charts = result.charts
    if not charts:
        # A successful pull with no rows: nothing happened in the period.
        # That is a result, so the chart is built empty.
        charts = await build_curated_charts(
            spec.dataset_id, [], context.language
        )
    if not charts:
        raise WidgetFailedError(
            f"No chart is available for {record['dataset_name']}."
        )
    return BuiltWidget(
        widget=SectionWidget(
            widget_type="insight",
            config={},
            insight=Insight(charts=charts),
        ),
        summary=f"chart: {record['dataset_name']}, {start} to {end}",
        charts=charts,
    )


async def _build_layer(
    spec: LayerWidgetSpec, context: BuildContext
) -> BuiltWidget:
    """The same tile layer the chat path resolves: ``pick_dataset`` passes
    its selection and the catalog row to ``get_tile_services_for_dataset``.
    Here the selection is a stub with no context layer and no parameters,
    which gives the dataset defaults (for example a canopy threshold of 30).
    """
    record = _dataset_record(spec.dataset_id)
    start, end = await _period(spec.dataset_id, context)
    selection = SimpleNamespace(
        dataset_id=spec.dataset_id, context_layer=None, parameters=None
    )
    tile_url, context_layers, layers = get_tile_services_for_dataset(
        selection, pd.Series(record), start, end
    )
    snapshot = dataset_config(
        {
            "dataset": {
                "dataset_id": spec.dataset_id,
                "dataset_name": record["dataset_name"],
                "tile_url": tile_url,
                "context_layer": None,
                "selected_layer": None,
                "context_layers": [
                    layer.model_dump() for layer in context_layers
                ],
                "parameters": None,
                "layers": [layer.model_dump() for layer in layers],
                "start_date": start,
                "end_date": end,
            }
        }
    )
    if snapshot is None:
        raise WidgetFailedError(
            f"{record['dataset_name']} has no map layer to show."
        )
    return BuiltWidget(
        widget=SectionWidget(
            widget_type="map", config=widget_config("dataset", snapshot, None)
        ),
        summary=f"map layer: {record['dataset_name']}, {start} to {end}",
    )


_IMAGERY_PROVIDER = Sentinel2ImageryProvider()


async def _build_imagery(
    spec: ImageryWidgetSpec, context: BuildContext
) -> BuiltWidget:
    result = await _IMAGERY_PROVIDER.get_imagery(
        ImageryRequest(
            aois=[dict(context.aoi)],
            target_date=context.end,
            language=context.language,
            window_days=spec.window_days,
            max_cloud_cover=spec.max_cloud_cover,
        )
    )
    snapshot = (
        imagery_config({"imagery": result.imagery.model_dump()})
        if result.imagery is not None
        else None
    )
    if snapshot is None:
        raise WidgetFailedError(result.message)
    return BuiltWidget(
        widget=SectionWidget(
            widget_type="map", config=widget_config("imagery", snapshot, None)
        ),
        summary=(
            "map: Sentinel-2 satellite imagery around "
            f"{snapshot['target_date']}"
        ),
    )


_BUILDERS: dict[str, Callable[..., Awaitable[BuiltWidget]]] = {
    "chart": _build_chart,
    "layer": _build_layer,
    "imagery": _build_imagery,
}


async def _run_builder(spec, context: BuildContext):
    """A built widget, or the exception that stopped it."""
    try:
        return await _BUILDERS[spec.kind](spec, context)
    except Exception as error:
        logger.warning(
            "analysis_template_widget_failed",
            kind=spec.kind,
            required=spec.required,
            error=str(error),
        )
        return error


def _first_aoi(dashboard: DashboardOrm) -> Optional[dict]:
    """The AOI a template covers. Portfolios are not in v1."""
    if not dashboard.aois:
        return None
    aoi = min(dashboard.aois, key=lambda a: a.position)
    return {
        "source": aoi.source,
        "src_id": aoi.src_id,
        "subtype": aoi.subtype,
        "name": aoi.name,
    }


async def apply_template(
    dashboard: DashboardOrm,
    template: AnalysisTemplate,
    args: TemplateArgs,
    user_id: str,
    language: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> TemplateResult:
    """Build ``template`` on ``dashboard`` as one new section.

    The caller checks that ``user_id`` owns the dashboard and validates
    ``args`` with ``template.parse_args``. Raises a ``TemplateError`` subclass when
    the build cannot finish; nothing is written then.
    """
    aoi = _first_aoi(dashboard)
    if aoi is None:
        raise NoAreaError(
            f"Dashboard '{dashboard.name}' has no area. Add an area first."
        )
    start, end = args.period(date.today())
    context = BuildContext(
        aoi=aoi,
        start=start,
        end=end,
        language=language or DEFAULT_LANGUAGE,
    )
    logger.info(
        "analysis_template_build_started",
        template=template.name,
        dashboard_id=str(dashboard.id),
        aoi=f"{aoi['source']}/{aoi['src_id']}",
        args=args.model_dump(mode="json"),
    )

    outcomes = await asyncio.gather(
        *(_run_builder(spec, context) for spec in template.widgets)
    )

    built: list[BuiltWidget] = []
    warnings: list[str] = []
    for spec, outcome in zip(template.widgets, outcomes):
        if isinstance(outcome, BuiltWidget):
            built.append(outcome)
            continue
        message = (
            str(outcome)
            if isinstance(outcome, TemplateError)
            else f"The {spec.kind} widget failed."
        )
        if spec.required:
            raise WidgetFailedError(message) from outcome
        warnings.append(message)

    start_date = start.isoformat()
    end_date = end.isoformat()
    title, description = await generate_section_text(
        template,
        aoi_name=aoi["name"],
        start_date=start_date,
        end_date=end_date,
        widget_summaries=[widget.summary for widget in built],
        charts=[chart for widget in built for chart in widget.charts],
        language=context.language,
    )

    written = await dashboard_writer.add_section_with_widgets(
        str(dashboard.id),
        title=title,
        description=description,
        widgets=[widget.widget for widget in built],
        user_id=user_id,
        thread_id=thread_id,
        template={
            "name": template.name,
            "args": args.model_dump(mode="json"),
            "start_date": start_date,
            "end_date": end_date,
            "built_at": datetime.now().isoformat(),
        },
    )
    if written is None:
        raise DashboardGoneError(
            f"Dashboard {dashboard.id} was deleted during the build."
        )
    section_id, widget_ids = written
    logger.info(
        "analysis_template_build_finished",
        template=template.name,
        dashboard_id=str(dashboard.id),
        section_id=section_id,
        widgets=len(widget_ids),
        warnings=len(warnings),
    )
    return TemplateResult(
        section_id=section_id,
        widget_ids=widget_ids,
        title=title,
        description=description,
        warnings=warnings,
    )
