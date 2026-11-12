"""What the zap planner knows about a dashboard: its area, its sections
and its widgets, each with a short readable label.

The planner reads the dashboard from the database (`load_dashboard`). The
eval and the tests give a `ZapDashboard` directly. A `ZapDashboard` made
with the text lists only (`sections`, `widgets`) gets section and widget
items with made-up ids, so the planner of phase 4 and its tests work with
no change.
"""

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select

from src.api.data_models import InsightChartOrm, InsightOrm, StatisticsOrm
from src.api.repositories import dashboard_writer
from src.api.services.dashboard_aoi import dashboard_aoi
from src.api.services.zap.models import ZapArea
from src.shared.database import get_session_from_pool

# The widget types that take the full width when the config has no `size`.
# The same rule as `topLevelWidgetSize` in the frontend.
FULL_WIDTH_TYPES = ("insight", "map", "alerts")
SIZES = ("single", "double")
SIZE_LABELS = {"single": "half width", "double": "full width"}

TEXT_TYPES = {"chart": "insight", "map": "map", "alerts list": "alerts"}
KIND_LABELS = {
    "insight": "Chart",
    "map": "Map",
    "alerts": "Alerts list",
    "text": "Note",
}


@dataclass
class BoardSection:
    id: str
    title: str
    position: int = 0


@dataclass
class BoardWidget:
    """One widget. `title` is its readable title, `kind` is "Chart",
    "Map", "Imagery", "Alerts list" or "Note". `analysis` holds the data of
    a chart (from its statistics row) or of a dataset map (from its
    config): `dataset_id`, `start_date`, `end_date`, `context_layer` and
    `canopy_cover`. It is None when zap cannot build the widget again."""

    id: str
    widget_type: str
    title: str
    kind: str
    position: int = 0
    section_id: Optional[str] = None
    config: dict[str, Any] = field(default_factory=dict)
    insight_id: Optional[str] = None
    analysis: Optional[dict[str, Any]] = None

    @property
    def size(self) -> str:
        size = self.config.get("size")
        if size in SIZES:
            return size
        return "double" if self.widget_type in FULL_WIDTH_TYPES else "single"


@dataclass
class ZapDashboard:
    """What the planner needs from a dashboard: its id, its name, its first
    area, its sections and its widgets.

    `sections` and `widgets` are the short texts for the jev state, e.g.
    "chart: Tree cover loss per year". `section_items` and `widget_items`
    are the items that an edit selects from. Give one form or both: the
    missing form is made from the other.
    """

    id: str
    name: str
    area: Optional[ZapArea]
    sections: list[str] = field(default_factory=list)
    widgets: list[str] = field(default_factory=list)
    section_items: list[BoardSection] = field(default_factory=list)
    widget_items: list[BoardWidget] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.section_items and self.sections:
            self.section_items = [
                BoardSection(id=f"section-{i + 1}", title=title, position=i)
                for i, title in enumerate(self.sections)
            ]
        if not self.sections:
            self.sections = [s.title for s in self.section_items]
        if not self.widget_items and self.widgets:
            self.widget_items = [
                _widget_from_text(text, f"widget-{i + 1}", i)
                for i, text in enumerate(self.widgets)
            ]
        if not self.widgets:
            self.widgets = [widget_text(w) for w in self.widget_items]

    def section(self, section_id: Optional[str]) -> Optional[BoardSection]:
        return next(
            (s for s in self.section_items if s.id == section_id), None
        )

    def widgets_of(self, section_id: str) -> list[BoardWidget]:
        return [w for w in self.widget_items if w.section_id == section_id]


def _widget_from_text(text: str, widget_id: str, position: int) -> BoardWidget:
    kind_word, _, title = text.partition(": ")
    widget_type = TEXT_TYPES.get(kind_word.strip().lower(), "insight")
    title = title.strip() or kind_word.strip()
    kind = KIND_LABELS.get(widget_type, widget_type.capitalize())
    if widget_type == "map" and re.search(r"sentinel|imagery", title, re.I):
        kind = "Imagery"
    return BoardWidget(
        id=widget_id,
        widget_type=widget_type,
        title=title,
        kind=kind,
        position=position,
    )


def widget_text(widget: BoardWidget) -> str:
    """The short text of a widget for the jev state, as in phase 4."""
    if widget.widget_type == "insight":
        return f"chart: {widget.title}"
    if widget.widget_type == "map":
        return f"map: {widget.title}"
    if widget.widget_type == "alerts":
        return "alerts list"
    return widget.widget_type


def widget_label(board: ZapDashboard, widget: BoardWidget) -> str:
    """The readable label of a widget: its kind, its title and its place,
    e.g. 'Chart "Tree cover loss per year" in section "Overview"'."""
    section = board.section(widget.section_id)
    place = (
        f' in section "{section.title}"' if section else " at the top level"
    )
    return f'{widget.kind} "{widget.title}"{place}'


def section_label(board: ZapDashboard, section: BoardSection) -> str:
    count = len(board.widgets_of(section.id))
    noun = "widget" if count == 1 else "widgets"
    return f'Section "{section.title}" ({count} {noun})'


def _canopy_param(parameters: Any) -> Optional[int]:
    """The canopy cover of a `parameters` list of a dataset or a
    statistics row: [{"name": "canopy_cover", "values": [30]}]."""
    for param in parameters or []:
        if isinstance(param, dict) and param.get("name") == "canopy_cover":
            values = param.get("values") or []
            if values and isinstance(values[0], (int, float)):
                return int(values[0])
    return None


def _map_analysis(config: dict) -> Optional[dict]:
    layer = config.get("dataset")
    if not isinstance(layer, dict) or not layer.get("dataset_id"):
        return None
    return {
        "dataset_id": int(layer["dataset_id"]),
        "start_date": _date_text(layer.get("start_date")),
        "end_date": _date_text(layer.get("end_date")),
        "context_layer": layer.get("context_layer"),
        "canopy_cover": _canopy_param(layer.get("parameters")),
    }


def _date_text(value: Any) -> Optional[str]:
    return str(value)[:10] if value else None


def _widget_title(widget, chart_titles: dict) -> tuple[str, str]:
    """The kind and the title of a database widget."""
    config = widget.config or {}
    title = config.get("title")
    if widget.widget_type == "insight":
        return "Chart", title or chart_titles.get(
            str(widget.insight_id)
        ) or "untitled"
    if widget.widget_type == "map":
        if config.get("imagery"):
            return "Imagery", title or "Sentinel-2 imagery"
        dataset = (config.get("dataset") or {}).get("dataset_name")
        return "Map", title or dataset or "layer"
    if widget.widget_type == "alerts":
        return "Alerts list", title or "Integrated alerts"
    if widget.widget_type == "text":
        text = (config.get("text") or "").strip().splitlines()
        return "Note", title or (text[0][:60] if text else "note")
    return widget.widget_type.capitalize(), title or widget.widget_type


async def _chart_titles(insight_ids: list) -> dict:
    """The title of the first chart of each insight, by insight id text."""
    if not insight_ids:
        return {}
    async with get_session_from_pool() as session:
        rows = await session.execute(
            select(InsightChartOrm.insight_id, InsightChartOrm.title)
            .where(InsightChartOrm.insight_id.in_(insight_ids))
            .order_by(InsightChartOrm.position)
        )
        titles: dict = {}
        for insight_id, title in rows.all():
            titles.setdefault(str(insight_id), title)
        return titles


def _uuid(value: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _insight_analyses(insight_ids: list) -> dict:
    """The analysis of each insight, by insight id text, from the first
    row of its statistics. An insight with no statistics row (a chart that
    the agent wrote with code) has no analysis."""
    if not insight_ids:
        return {}
    async with get_session_from_pool() as session:
        rows = await session.execute(
            select(InsightOrm.id, InsightOrm.statistics_ids).where(
                InsightOrm.id.in_(insight_ids)
            )
        )
        first = {
            str(insight_id): _uuid(ids[0])
            for insight_id, ids in rows.all()
            if ids and _uuid(ids[0])
        }
        if not first:
            return {}
        stats = await session.execute(
            select(StatisticsOrm).where(StatisticsOrm.id.in_(first.values()))
        )
        by_id = {str(row.id): row for row in stats.scalars().all()}
    out = {}
    for insight_id, stat_id in first.items():
        row = by_id.get(str(stat_id))
        if row is None or not row.dataset_id:
            continue
        out[insight_id] = {
            "dataset_id": int(row.dataset_id),
            "start_date": _date_text(row.start_date),
            "end_date": _date_text(row.end_date),
            "context_layer": row.context_layer,
            "canopy_cover": _canopy_param(row.parameters),
        }
    return out


async def load_dashboard(
    dashboard_id: Optional[str], user_id: str
) -> Optional[ZapDashboard]:
    """The dashboard, or None when it does not exist or the user is not its
    owner. Zap edits only the dashboards of the user, also for an admin."""
    if not dashboard_id:
        return None
    row = await dashboard_writer.get_dashboard(dashboard_id)
    if row is None or row.user_id != user_id:
        return None
    aoi = dashboard_aoi(row)
    sections = sorted(row.sections or [], key=lambda s: s.position)
    order = {str(s.id): i for i, s in enumerate(sections)}
    # The top level first, then the sections in their order.
    widgets = sorted(
        row.widgets or [],
        key=lambda w: (
            -1 if w.section_id is None else order.get(str(w.section_id), 0),
            w.position,
        ),
    )
    insight_ids = [w.insight_id for w in widgets if w.insight_id]
    titles = await _chart_titles(insight_ids)
    analyses = await _insight_analyses(insight_ids)
    items = []
    for w in widgets:
        kind, title = _widget_title(w, titles)
        config = dict(w.config or {})
        items.append(
            BoardWidget(
                id=str(w.id),
                widget_type=w.widget_type,
                title=title,
                kind=kind,
                position=w.position,
                section_id=str(w.section_id) if w.section_id else None,
                config=config,
                insight_id=str(w.insight_id) if w.insight_id else None,
                analysis=analyses.get(str(w.insight_id))
                if w.insight_id
                else _map_analysis(config)
                if w.widget_type == "map"
                else None,
            )
        )
    return ZapDashboard(
        id=str(row.id),
        name=row.name,
        area=ZapArea(
            name=aoi["name"],
            source=aoi["source"],
            src_id=str(aoi["src_id"]),
            subtype=aoi["subtype"],
        )
        if aoi
        else None,
        section_items=[
            BoardSection(id=str(s.id), title=s.title, position=s.position)
            for s in sections
        ],
        widget_items=items,
    )
