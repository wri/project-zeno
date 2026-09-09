"""Near-real-time monitoring: what has been disturbed here, recently.

One build, one section: a chart of integrated disturbance alerts over the
period, a map of those alerts, and satellite imagery of the same area and
period. Everything comes from parts that already exist — the curated alerts
chart generator, the dataset layer resolver, the Sentinel-2 mosaic service —
so no model chooses anything except the words.

What can fail, and what happens:

- the analytics pull fails → the build fails, since a section without its
  data says nothing;
- the mosaic fails (the area is too large, no scenes, STAC down) → the
  section is built without the imagery widget, and the reason is reported
  in ``warnings``;
- the summary call fails → a templated title and description are used
  (``summary.fallback_summary``);
- the dashboard is deleted mid-build → the insight row is already written
  and is left orphaned. Harmless dead data no dashboard points at, the same
  trade the deterministic analysis job makes.
"""

from dataclasses import asdict
from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agent.datasets.dates import revise_date_range
from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    AnalyticsHandler,
)
from src.agent.datasets.layers import (
    get_dataset_record,
    resolve_dataset_layer,
)
from src.agent.imagery import ImageryRequest, Sentinel2ImageryProvider
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.subagents.analyst.charts.model import Insight
from src.api.data_models import DashboardOrm, DashboardSectionOrm
from src.api.repositories.insight_writer import persist_insight
from src.api.services.analysis_templates import writer
from src.api.services.analysis_templates.base import (
    AlreadyBuiltError,
    DataUnavailableError,
    SectionContent,
    TemplateResult,
    aoi_ref,
    first_aoi,
    templated_sections,
)
from src.api.services.analysis_templates.nrt_monitoring.summary import (
    generate_section_summary,
)
from src.api.services.analysis_templates.registry import ENTRIES_BY_NAME
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import DETERMINISTIC_GENERATORS
from src.api.services.widget_configs import (
    dataset_snapshot,
    imagery_snapshot,
    map_widget_config,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

NAME = "nrt-monitoring"

#: Satellite imagery search window, ±N days around the end of the period,
#: and the cloud limit for a scene. Constants, not parameters: the point of
#: this template is that a caller asks for a period and nothing else.
_IMAGERY_WINDOW_DAYS = 7
_MAX_CLOUD_COVER = 20

_IMAGERY_PROVIDER = Sentinel2ImageryProvider()


class NrtParams(BaseModel):
    """The one thing a caller chooses: how far back to look."""

    model_config = ConfigDict(extra="forbid")

    days: int = Field(
        default=14,
        ge=1,
        le=365,
        description=(
            "Length of the alert window, counted back from today. Two weeks "
            "by default: these sections are for what is happening now. "
            "Clamped to the dataset's own coverage."
        ),
    )


async def resolve_period(days: int) -> tuple[str, str]:
    """The alert window: ``days`` back from today, clamped to the dataset.

    Integrated alerts start on 2023-12-01 and have no fixed end, so the
    clamp normally only moves the start of a very long window. It happens
    here, once, because the "already built" check matches on the period a
    previous build *stored*: comparing an unclamped range against a clamped
    one would never match, and every request would build again.
    """
    today = date.today()
    start, end, _ = await revise_date_range(
        (today - timedelta(days=days)).isoformat(),
        today.isoformat(),
        INTEGRATED_ALERTS_ID,
    )
    return start, end


def _find_built(
    dashboard: DashboardOrm, start_date: str, end_date: str
) -> Optional[DashboardSectionOrm]:
    """A monitoring section already on this dashboard for the same period."""
    for section in templated_sections(dashboard, NAME):
        config = dict(section.config or {})
        if (
            config.get("start_date") == start_date
            and config.get("end_date") == end_date
        ):
            return section
    return None


async def _gather(
    aoi: dict,
    *,
    user_id: str,
    days: int,
    language: str,
) -> SectionContent:
    """Pull the data, build the widgets, write the words — no section yet.

    Shared by the build and every refresh, so a refreshed section is
    assembled exactly like a new one.
    """
    language = language or DEFAULT_LANGUAGE
    start_date, end_date = await resolve_period(days)
    warnings: list[str] = []

    # Each consumer below gets its own copy of the AOI (``dict(aoi)`` at
    # every call site). The analytics handler rewrites its input in place —
    # it strips the GADM level suffix, so "BRA.16.197_2" becomes
    # "BRA.16.197" — and the imagery lookup that follows needs the canonical
    # id the dashboard stored, not that one.

    # 1. Alert data, and the curated chart for it.
    service = AnalyzeService(AnalyticsHandler(), DETERMINISTIC_GENERATORS)
    analysis = await service.analyze(
        aois=[dict(aoi)],
        dataset_id=INTEGRATED_ALERTS_ID,
        start_date=start_date,
        end_date=end_date,
        language=language,
    )
    if not analysis.data.success:
        raise DataUnavailableError(
            f"Could not retrieve alert data for '{aoi['name']}': "
            f"{analysis.data.message}"
        )

    # Charts only, no narrative: the section's description carries the words.
    insight_id = await persist_insight(
        Insight(charts=analysis.charts),
        user_id=user_id,
        thread_id="",
    )

    # 2. The alerts layer, over the same period as the chart.
    alerts_layer = resolve_dataset_layer(
        INTEGRATED_ALERTS_ID, start_date, end_date
    )

    # 3. Satellite imagery for the end of the period. Optional: a failure
    #    here costs the third widget, not the section.
    imagery = await _IMAGERY_PROVIDER.get_imagery(
        ImageryRequest(
            aois=[dict(aoi)],
            target_date=date.fromisoformat(end_date),
            language=language,
            window_days=_IMAGERY_WINDOW_DAYS,
            max_cloud_cover=_MAX_CLOUD_COVER,
        )
    )
    if imagery.imagery is None:
        warnings.append(imagery.message)
        logger.info("nrt_section_imagery_unavailable", reason=imagery.message)

    # 4. The words. They state the period, so a refresh rewrites them.
    summary = await generate_section_summary(
        analysis.charts,
        aoi_name=aoi["name"],
        start_date=start_date,
        end_date=end_date,
        presentation_instructions=get_dataset_record(INTEGRATED_ALERTS_ID).get(
            "presentation_instructions"
        ),
        language=language,
    )

    widgets: list[dict] = [
        {"widget_type": "insight", "insight_id": insight_id},
        {
            "widget_type": "map",
            "config": map_widget_config(
                "dataset",
                dataset_snapshot(asdict(alerts_layer)),
                alerts_layer.dataset_name,
            ),
        },
    ]
    if imagery.imagery is not None:
        widgets.append(
            {
                "widget_type": "map",
                "config": map_widget_config(
                    "imagery",
                    imagery_snapshot(imagery.imagery.model_dump()),
                    "Satellite imagery",
                ),
            }
        )

    return SectionContent(
        title=summary.title,
        description=summary.description,
        widgets=widgets,
        config={
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
        },
        summary=(
            f"a near-real-time monitoring section for '{aoi['name']}' "
            f"covering {start_date} to {end_date}, with "
            f"{len(widgets)} widgets"
        ),
        warnings=warnings,
    )


class NrtMonitoringTemplate:
    """The template object the registry hands out."""

    entry = ENTRIES_BY_NAME[NAME]
    params_model = NrtParams

    async def build(
        self,
        dashboard: DashboardOrm,
        *,
        user_id: str,
        params: NrtParams,
        language: str = DEFAULT_LANGUAGE,
    ) -> TemplateResult:
        aoi = first_aoi(dashboard)
        if aoi is None:
            raise DataUnavailableError(
                f"Dashboard '{dashboard.name}' has no area to monitor."
            )

        start_date, end_date = await resolve_period(params.days)
        built = _find_built(dashboard, start_date, end_date)
        if built is not None:
            raise AlreadyBuiltError(
                f"Dashboard '{dashboard.name}' already has the monitoring "
                f"section '{built.title}' for {start_date} to {end_date}.",
                str(built.id),
            )

        logger.info(
            "nrt_section_build_started",
            dashboard_id=str(dashboard.id),
            aoi=f"{aoi.source}/{aoi.src_id}",
            days=params.days,
        )
        content = await _gather(
            aoi_ref(aoi),
            user_id=user_id,
            days=params.days,
            language=language,
        )
        return await writer.write_section(str(dashboard.id), self, content)

    async def refresh(
        self,
        section: DashboardSectionOrm,
        dashboard: DashboardOrm,
        *,
        user_id: str,
        params: NrtParams,
        language: str = DEFAULT_LANGUAGE,
    ) -> TemplateResult:
        """Rebuild the section for a new window, in place.

        Everything the section shows moves to the new period together — the
        chart, the alerts layer and the imagery — and its title and
        description are rewritten, because they state the period.
        """
        aoi = first_aoi(dashboard)
        if aoi is None:
            raise DataUnavailableError(
                f"Dashboard '{dashboard.name}' has no area to monitor."
            )

        logger.info(
            "nrt_section_refresh_started",
            section_id=str(section.id),
            aoi=f"{aoi.source}/{aoi.src_id}",
            days=params.days,
        )
        content = await _gather(
            aoi_ref(aoi),
            user_id=user_id,
            days=params.days,
            language=language,
        )
        content.summary = (
            f"moved the monitoring section onto {content.config['start_date']}"
            f" to {content.config['end_date']} ({params.days} days); every "
            f"widget in it now covers that period"
        )
        return await writer.replace_section(str(section.id), self, content)


TEMPLATE = NrtMonitoringTemplate()
