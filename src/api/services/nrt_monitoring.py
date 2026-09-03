"""Build a near-real-time monitoring section in one call.

One click on the frontend, one section on the dashboard: a chart of
disturbance alerts over the period, a map of those alerts, and satellite
imagery of the same area and period. The recipe assembles all three from
parts that already exist — the deterministic alerts chart generator, the
dataset layer resolver, the Sentinel-2 mosaic service — and writes them as a
sealed section, so a reader only ever sees the section complete.

What can fail, and what happens:

- the analytics pull fails → the whole build fails, since a section without
  its data says nothing;
- the mosaic fails (the area is too large, no scenes, STAC down) → the
  section is built without the imagery widget and the reason is reported in
  ``warnings``;
- the summary call fails → a templated title and description are used
  (``nrt_summary.fallback_summary``);
- the dashboard is deleted mid-build → the insight row is already written and
  is left orphaned. Harmless dead data that no dashboard points at, the same
  trade the deterministic analysis job makes.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

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
from src.api.repositories import dashboard_writer
from src.api.repositories.insight_writer import persist_insight
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import DETERMINISTIC_GENERATORS
from src.api.services.nrt_summary import generate_section_summary
from src.api.services.widget_configs import (
    dataset_snapshot,
    imagery_snapshot,
    map_widget_config,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: The section type that marks — and seals — a monitoring section.
SECTION_TYPE = "nrt-monitoring"

#: Length of the alert window when the caller names none. Two weeks: these
#: sections are for what is happening now, and a reader changes the window
#: on demand when they want more history.
DEFAULT_DAYS = 14

#: The widest window the recipe will build. Alerts are near-real-time, so a
#: year is already well past what the section is for.
MAX_DAYS = 365

_IMAGERY_PROVIDER = Sentinel2ImageryProvider()


class AnalyticsFailedError(Exception):
    """The alert data could not be pulled, so there is no section to build."""


@dataclass
class NrtSectionResult:
    section_id: str
    insight_id: str
    widget_ids: list[str]
    start_date: str
    end_date: str
    days: int
    #: Why a widget is missing, in words a caller can show the user.
    warnings: list[str] = field(default_factory=list)


@dataclass
class NrtContent:
    """Everything a section needs, gathered but not yet written.

    Building and refreshing differ only in where this lands, so both go
    through one gather step. Nothing here has touched the database except
    the insight, which has to exist before a widget can reference it.
    """

    title: str
    description: str
    insight_id: str
    widgets: list[dict]
    start_date: str
    end_date: str
    days: int
    warnings: list[str] = field(default_factory=list)

    def section_config(self) -> dict:
        """What gets recorded on the section row: the window it covers."""
        return {
            "recipe": SECTION_TYPE,
            "days": self.days,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


async def resolve_period(days: int = DEFAULT_DAYS) -> tuple[str, str]:
    """The alert window: ``days`` back from today, clamped to the dataset.

    Integrated alerts start on 2023-12-01 and have no fixed end, so the
    clamp normally only moves the start of a very long window. The clamp
    belongs here rather than in the builder alone, because the double-click
    guard matches on the period a previous build *stored* — comparing an
    unclamped range against a clamped one would never match, and every click
    would build again.
    """
    today = date.today()
    start, end, _ = await revise_date_range(
        (today - timedelta(days=days)).isoformat(),
        today.isoformat(),
        INTEGRATED_ALERTS_ID,
    )
    return start, end


async def gather_nrt_content(
    aoi: dict,
    *,
    user_id: str,
    days: int = DEFAULT_DAYS,
    window_days: int = 7,
    max_cloud_cover: int = 20,
    title: Optional[str] = None,
    description: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
) -> NrtContent:
    """Pull the data, build the widgets, write the words — no section yet.

    Shared by the first build and every refresh, so a refreshed section is
    assembled exactly like a new one. Raises ``AnalyticsFailedError`` when
    the data pull fails: a section without its data says nothing.
    """
    language = language or DEFAULT_LANGUAGE

    # Every consumer gets its own copy of the AOI. The analytics handler
    # rewrites its input in place — it strips the GADM level suffix, so
    # "BRA.16.197_2" becomes "BRA.16.197" — and the imagery lookup that
    # follows needs the canonical id the dashboard stored, not that one.
    aoi = dict(aoi)
    start_date, end_date = await resolve_period(days)
    warnings: list[str] = []

    # 1. Alert data and the default chart for it.
    service = AnalyzeService(AnalyticsHandler(), DETERMINISTIC_GENERATORS)
    analysis = await service.analyze(
        aois=[dict(aoi)],
        dataset_id=INTEGRATED_ALERTS_ID,
        start_date=start_date,
        end_date=end_date,
        language=language,
    )
    if not analysis.data.success:
        raise AnalyticsFailedError(analysis.data.message)

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
    imagery = None
    result = await _IMAGERY_PROVIDER.get_imagery(
        ImageryRequest(
            aois=[dict(aoi)],
            target_date=date.fromisoformat(end_date),
            language=language,
            window_days=window_days,
            max_cloud_cover=max_cloud_cover,
        )
    )
    if result.imagery is not None:
        imagery = result.imagery.model_dump()
    else:
        warnings.append(result.message)
        logger.info("nrt_section_imagery_unavailable", reason=result.message)

    # 4. The words. Generated unless the caller supplied them. They state
    #    the period, so a refresh regenerates them rather than keeping the
    #    previous ones.
    if title and description:
        section_title, section_description = title, description
    else:
        summary = await generate_section_summary(
            analysis.charts,
            aoi_name=aoi["name"],
            start_date=start_date,
            end_date=end_date,
            presentation_instructions=get_dataset_record(
                INTEGRATED_ALERTS_ID
            ).get("presentation_instructions"),
            language=language,
        )
        section_title = title or summary.title
        section_description = description or summary.description

    widgets: list[dict] = [
        {"widget_type": "insight", "insight_id": insight_id},
        {
            "widget_type": "map",
            "config": map_widget_config(
                "dataset",
                dataset_snapshot(alerts_layer),
                alerts_layer.dataset_name,
            ),
        },
    ]
    if imagery is not None:
        widgets.append(
            {
                "widget_type": "map",
                "config": map_widget_config(
                    "imagery", imagery_snapshot(imagery), "Satellite imagery"
                ),
            }
        )

    return NrtContent(
        title=section_title,
        description=section_description,
        insight_id=insight_id,
        widgets=widgets,
        start_date=start_date,
        end_date=end_date,
        days=days,
        warnings=warnings,
    )


async def build_nrt_section(
    dashboard_id: str,
    aoi: dict,
    *,
    user_id: str,
    days: int = DEFAULT_DAYS,
    window_days: int = 7,
    max_cloud_cover: int = 20,
    title: Optional[str] = None,
    description: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
) -> NrtSectionResult:
    """Build a new monitoring section and return what was written.

    ``aoi`` is one of the dashboard's AOI references — ``source``, ``src_id``,
    ``subtype`` and ``name``. ``title`` / ``description`` override the
    generated text. Raises ``AnalyticsFailedError`` when the data pull fails,
    and ``ValueError`` when the dashboard has gone.
    """
    logger.info(
        "nrt_section_build_started",
        dashboard_id=dashboard_id,
        aoi=f"{aoi['source']}/{aoi['src_id']}",
        days=days,
    )
    content = await gather_nrt_content(
        aoi,
        user_id=user_id,
        days=days,
        window_days=window_days,
        max_cloud_cover=max_cloud_cover,
        title=title,
        description=description,
        language=language,
    )

    # One transaction, so the section is never seen half-built.
    written = await dashboard_writer.add_section_with_widgets(
        dashboard_id,
        title=content.title,
        description=content.description,
        type=SECTION_TYPE,
        config=content.section_config(),
        widgets=content.widgets,
    )
    if written is None:
        raise ValueError(f"Dashboard {dashboard_id} not found")
    section_id, widget_ids = written

    logger.info(
        "nrt_section_build_completed",
        dashboard_id=dashboard_id,
        section_id=section_id,
        insight_id=content.insight_id,
        widgets=len(widget_ids),
        warnings=len(content.warnings),
    )
    return NrtSectionResult(
        section_id=section_id,
        insight_id=content.insight_id,
        widget_ids=widget_ids,
        start_date=content.start_date,
        end_date=content.end_date,
        days=content.days,
        warnings=content.warnings,
    )


async def refresh_nrt_section(
    section_id: str,
    aoi: dict,
    *,
    user_id: str,
    days: int = DEFAULT_DAYS,
    window_days: int = 7,
    max_cloud_cover: int = 20,
    language: str = DEFAULT_LANGUAGE,
) -> NrtSectionResult:
    """Rebuild an existing section for a new window, in place.

    Everything the section shows moves to the new period together — the
    chart, the alerts layer and the imagery — and its title and description
    are rewritten, because they state the period. The section row itself
    survives, so its id and its place on the dashboard hold.

    The previous chart insight is deleted once nothing points at it: it was
    this section's own content, for a period the section no longer covers.
    """
    logger.info(
        "nrt_section_refresh_started",
        section_id=section_id,
        aoi=f"{aoi['source']}/{aoi['src_id']}",
        days=days,
    )
    content = await gather_nrt_content(
        aoi,
        user_id=user_id,
        days=days,
        window_days=window_days,
        max_cloud_cover=max_cloud_cover,
        language=language,
    )

    written = await dashboard_writer.replace_section_widgets(
        section_id,
        title=content.title,
        description=content.description,
        config=content.section_config(),
        widgets=content.widgets,
    )
    if written is None:
        raise ValueError(f"Section {section_id} not found")
    widget_ids, replaced_insight_ids = written
    await dashboard_writer.delete_unreferenced_insights(replaced_insight_ids)

    logger.info(
        "nrt_section_refresh_completed",
        section_id=section_id,
        insight_id=content.insight_id,
        widgets=len(widget_ids),
        warnings=len(content.warnings),
    )
    return NrtSectionResult(
        section_id=section_id,
        insight_id=content.insight_id,
        widget_ids=widget_ids,
        start_date=content.start_date,
        end_date=content.end_date,
        days=content.days,
        warnings=content.warnings,
    )


def nrt_sections(dashboard: DashboardOrm) -> list[DashboardSectionOrm]:
    """The monitoring sections on a dashboard, in render order."""
    return [
        section
        for section in dashboard.sections or []
        if section.type == SECTION_TYPE
    ]


def find_existing_section(
    dashboard: DashboardOrm, start_date: str, end_date: str
) -> Optional[DashboardSectionOrm]:
    """A monitoring section already on this dashboard for the same period.

    The guard against a double click: building twice costs a data pull, a
    STAC search and a model call, and leaves the reader two identical
    sections. Matched on the window the section itself records, so a second
    recipe over the same dataset cannot collide with this one.
    """
    for section in nrt_sections(dashboard):
        window = section.config or {}
        if (
            window.get("start_date") == start_date
            and window.get("end_date") == end_date
        ):
            return section
    return None
