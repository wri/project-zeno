"""Centralized dashboard persistence shared by the API router and agent tools.

Both paths write the same ``DashboardOrm`` / ``DashboardAoiOrm`` /
``DashboardSectionOrm`` / ``DashboardWidgetOrm`` rows; this is the single
place that mapping lives.
Ownership checks live in the callers (router/tools) via ``dashboard_access``
— the same split as insights. Malformed UUIDs are treated as not-found
(None/False) rather than raising.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.api.data_models import (
    DashboardAoiOrm,
    DashboardOrm,
    DashboardSectionOrm,
    DashboardWidgetOrm,
    InsightOrm,
)
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger
from src.shared.tile_urls import relativize_widget_config

logger = get_logger(__name__)


class DuplicateInsightWidgetError(Exception):
    """The dashboard already has a widget for this insight.

    Raised by ``add_widget`` when the partial unique index on
    ``(dashboard_id, insight_id)`` rejects the insert — the signal that a
    retry (agent or REST) is re-adding rather than adding.
    """

    def __init__(self, dashboard_id: str, insight_id: str):
        self.dashboard_id = dashboard_id
        self.insight_id = insight_id
        super().__init__(
            f"insight {insight_id} is already on dashboard {dashboard_id}"
        )


class UnknownSectionError(Exception):
    """The section does not exist on the target dashboard.

    Raised by ``add_widget`` / ``update_widget`` / ``move_widget`` when a
    caller passes a ``section_id`` belonging to another dashboard (or to
    nothing at all) — a widget must never be grouped under a section of a
    different dashboard.
    """

    def __init__(self, dashboard_id: str, section_id: str):
        self.dashboard_id = dashboard_id
        self.section_id = section_id
        super().__init__(
            f"section {section_id} is not on dashboard {dashboard_id}"
        )


#: Section types written by a recipe in one piece. Their content is a record
#: of one build — an area, a date range, the data as it was — so editing it
#: would make the section's own title and description untrue. Everything that
#: changes a sealed section or its widgets raises ``SealedSectionError``;
#: deleting the whole section stays allowed (it takes its widgets with it,
#: see ``remove_section``). The rule lives here, not in a DB constraint,
#: because it is product policy that grows types and exceptions — and because
#: the builder that writes these sections has to get past it.
SEALED_SECTION_TYPES = frozenset({"nrt-monitoring"})


class SealedSectionError(Exception):
    """The write targets a section whose type is read-only.

    Raised by the section and widget writers for every caller — the API
    router maps it to 409, the agent tools to a tool error. The builder that
    creates such a section passes ``allow_sealed=True``.
    """

    def __init__(self, section_id: str, section_type: str):
        self.section_id = section_id
        self.section_type = section_type
        super().__init__(
            f"section {section_id} is read-only (type: {section_type})"
        )


class _Unset:
    """Marker for "argument not supplied" where None is a real value."""


#: Sentinel default for ``section_id``: passing ``None`` moves a widget to
#: the ungrouped top level, omitting it leaves the widget where it is.
UNSET = _Unset()


def _guard_sealed(section: Optional[DashboardSectionOrm]) -> None:
    """Raise if the section is one a recipe built and sealed."""
    if section is not None and section.type in SEALED_SECTION_TYPES:
        raise SealedSectionError(str(section.id), section.type)


async def _guard_sealed_id(session, section_id) -> None:
    """Raise if ``section_id`` names a sealed section (None is never one)."""
    if section_id is None:
        return
    _guard_sealed(await session.get(DashboardSectionOrm, section_id))


def _parse_uuid(value) -> Optional[UUID]:
    """UUID or None for malformed input — not-found, never an exception."""
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


async def create_dashboard(
    *,
    user_id: str,
    name: str,
    description: Optional[str] = None,
    aois: list[dict],
) -> str:
    """Create a dashboard with its AOI references; return the new id (str).

    Each entry in ``aois`` carries the canonical address plus display name:
    ``{"source", "src_id", "subtype", "name"}``. Positions follow list order.
    """
    async with get_session_from_pool() as session:
        dashboard = DashboardOrm(
            user_id=user_id,
            name=name,
            description=description,
        )
        session.add(dashboard)
        await session.flush()

        session.add_all(
            DashboardAoiOrm(
                dashboard_id=dashboard.id,
                source=aoi["source"],
                src_id=aoi["src_id"],
                subtype=aoi["subtype"],
                name=aoi["name"],
                position=position,
            )
            for position, aoi in enumerate(aois)
        )

        await session.commit()
        dashboard_id = str(dashboard.id)

    logger.info(
        "dashboard_created",
        dashboard_id=dashboard_id,
        user_id=user_id,
        aois_count=len(aois),
    )
    return dashboard_id


async def get_dashboard(dashboard_id) -> Optional[DashboardOrm]:
    """Load a dashboard with its AOIs, sections and widgets; caller applies
    the access check."""
    target = _parse_uuid(dashboard_id)
    if target is None:
        return None
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(DashboardOrm)
            .options(
                selectinload(DashboardOrm.aois),
                selectinload(DashboardOrm.sections),
                selectinload(DashboardOrm.widgets),
            )
            .where(DashboardOrm.id == target)
        )
        return result.scalar_one_or_none()


async def get_widget(widget_id) -> Optional[DashboardWidgetOrm]:
    """Load a single widget by id; the caller applies access checks via the
    owning dashboard. Malformed ids are not-found (None), never an error."""
    target = _parse_uuid(widget_id)
    if target is None:
        return None
    async with get_session_from_pool() as session:
        return await session.get(DashboardWidgetOrm, target)


async def _section_belongs_to(session, dashboard_id: UUID, section_id: UUID):
    """True when the section exists on this dashboard."""
    found = await session.scalar(
        select(DashboardSectionOrm.id).where(
            DashboardSectionOrm.id == section_id,
            DashboardSectionOrm.dashboard_id == dashboard_id,
        )
    )
    return found is not None


async def _next_position(session, dashboard_id: UUID, section_id) -> int:
    """End of the container the widget lands in: its section, or the
    ungrouped top-level list when ``section_id`` is None."""
    max_position = await session.scalar(
        select(func.max(DashboardWidgetOrm.position)).where(
            DashboardWidgetOrm.dashboard_id == dashboard_id,
            DashboardWidgetOrm.section_id == section_id
            if section_id is not None
            else DashboardWidgetOrm.section_id.is_(None),
        )
    )
    return 0 if max_position is None else max_position + 1


async def add_widget(
    dashboard_id,
    *,
    widget_type: str,
    insight_id: Optional[str] = None,
    config: Optional[dict] = None,
    position: Optional[int] = None,
    section_id: Optional[str] = None,
    allow_sealed: bool = False,
) -> Optional[str]:
    """Append a widget to a dashboard; return the new widget id (str).

    ``section_id`` groups the widget under one of the dashboard's sections;
    None (the default) leaves it ungrouped at the top level. Position
    defaults to max+1 *within that container*. Returns None if the dashboard
    does not exist or an id is malformed; raises ``UnknownSectionError`` when
    the section is not on this dashboard, and ``SealedSectionError`` when it
    is one a recipe sealed. ``allow_sealed`` is for the recipe builders that
    fill their own section — no other caller passes it.
    """
    target = _parse_uuid(dashboard_id)
    if target is None:
        return None
    insight_uuid = None
    if insight_id is not None:
        insight_uuid = _parse_uuid(insight_id)
        if insight_uuid is None:
            return None
    section_uuid = None
    if section_id is not None:
        section_uuid = _parse_uuid(section_id)
        if section_uuid is None:
            raise UnknownSectionError(str(dashboard_id), str(section_id))

    async with get_session_from_pool() as session:
        exists = await session.scalar(
            select(DashboardOrm.id).where(DashboardOrm.id == target)
        )
        if exists is None:
            return None

        if section_uuid is not None and not await _section_belongs_to(
            session, target, section_uuid
        ):
            raise UnknownSectionError(str(target), str(section_id))

        if not allow_sealed:
            await _guard_sealed_id(session, section_uuid)

        if position is None:
            position = await _next_position(session, target, section_uuid)

        widget = DashboardWidgetOrm(
            dashboard_id=target,
            widget_type=widget_type,
            insight_id=insight_uuid,
            config=relativize_widget_config(config) or {},
            position=position,
            section_id=section_uuid,
        )
        session.add(widget)
        try:
            await session.commit()
        except IntegrityError as exc:
            if "uq_dashboard_widgets_dashboard_insight" not in str(exc.orig):
                raise
            logger.warning(
                "dashboard_widget_duplicate",
                dashboard_id=str(target),
                insight_id=insight_id,
            )
            raise DuplicateInsightWidgetError(
                str(target), str(insight_id)
            ) from exc
        widget_id = str(widget.id)

    logger.info(
        "dashboard_widget_added",
        dashboard_id=str(target),
        widget_id=widget_id,
        widget_type=widget_type,
        insight_id=insight_id,
        section_id=section_id,
    )
    return widget_id


async def update_widget(
    widget_id,
    *,
    position: Optional[int] = None,
    config: Optional[dict] = None,
    section_id=UNSET,
) -> bool:
    """Reorder a widget, move it between sections, and/or replace its config.

    ``section_id`` is three-valued: omit it to leave the grouping alone, pass
    a section id to move the widget into that section, or pass None to move
    it back to the ungrouped top level. Moving without an explicit
    ``position`` appends the widget to the end of its new container. Raises
    ``UnknownSectionError`` when the section is not on the widget's own
    dashboard, and ``SealedSectionError`` when the widget sits in a sealed
    section or would be moved into one.
    """
    target = _parse_uuid(widget_id)
    if target is None:
        return False
    async with get_session_from_pool() as session:
        widget = await session.get(DashboardWidgetOrm, target)
        if widget is None:
            return False

        # Both ends of a move are guarded: a widget cannot leave a sealed
        # section, and cannot join one.
        await _guard_sealed_id(session, widget.section_id)

        if not isinstance(section_id, _Unset):
            section_uuid = None
            if section_id is not None:
                section_uuid = _parse_uuid(section_id)
                if section_uuid is None or not await _section_belongs_to(
                    session, widget.dashboard_id, section_uuid
                ):
                    raise UnknownSectionError(
                        str(widget.dashboard_id), str(section_id)
                    )
                await _guard_sealed_id(session, section_uuid)
            if section_uuid != widget.section_id:
                widget.section_id = section_uuid
                if position is None:
                    position = await _next_position(
                        session, widget.dashboard_id, section_uuid
                    )

        if position is not None:
            widget.position = position
        if config is not None:
            widget.config = relativize_widget_config(config)
        await session.commit()

    logger.info("dashboard_widget_updated", widget_id=str(target))
    return True


async def remove_widget(widget_id) -> bool:
    """Delete a widget; the referenced insight is left intact.

    Raises ``SealedSectionError`` for a widget in a sealed section: those go
    only with the whole section (``remove_section``).
    """
    target = _parse_uuid(widget_id)
    if target is None:
        return False
    async with get_session_from_pool() as session:
        widget = await session.get(DashboardWidgetOrm, target)
        if widget is None:
            return False
        await _guard_sealed_id(session, widget.section_id)
        await session.delete(widget)
        await session.commit()

    logger.info("dashboard_widget_removed", widget_id=str(target))
    return True


async def add_section(
    dashboard_id,
    *,
    title: str,
    description: Optional[str] = None,
    position: Optional[int] = None,
    type: str = "default",
) -> Optional[str]:
    """Append a section to a dashboard; return the new section id (str).

    Position defaults to max+1 (last section on the dashboard). ``type``
    records how the section was built; anything in
    ``SEALED_SECTION_TYPES`` is read-only from then on. Returns None if the
    dashboard does not exist or the id is malformed.
    """
    target = _parse_uuid(dashboard_id)
    if target is None:
        return None
    async with get_session_from_pool() as session:
        exists = await session.scalar(
            select(DashboardOrm.id).where(DashboardOrm.id == target)
        )
        if exists is None:
            return None

        if position is None:
            max_position = await session.scalar(
                select(func.max(DashboardSectionOrm.position)).where(
                    DashboardSectionOrm.dashboard_id == target
                )
            )
            position = 0 if max_position is None else max_position + 1

        section = DashboardSectionOrm(
            dashboard_id=target,
            title=title,
            description=description,
            position=position,
            type=type,
        )
        session.add(section)
        await session.commit()
        section_id = str(section.id)

    logger.info(
        "dashboard_section_added",
        dashboard_id=str(target),
        section_id=section_id,
        title=title,
        type=type,
    )
    return section_id


async def add_section_with_widgets(
    dashboard_id,
    *,
    title: str,
    description: Optional[str] = None,
    type: str = "default",
    widgets: Optional[list[dict]] = None,
) -> Optional[tuple[str, list[str]]]:
    """Create a section and its widgets in one transaction.

    The write path for the recipe builders: a section that a reader may only
    ever see complete must not appear widget by widget, and a failure
    half-way must leave nothing behind. Each entry of ``widgets`` is
    ``{"widget_type": ..., "insight_id": ..., "config": ...}``; they take
    positions 0..n-1 in the order given. Returns ``(section_id, widget_ids)``,
    or None if the dashboard does not exist.

    Sealed types are expected here — this is the door ``allow_sealed`` opens
    for the widget writers.
    """
    target = _parse_uuid(dashboard_id)
    if target is None:
        return None

    async with get_session_from_pool() as session:
        exists = await session.scalar(
            select(DashboardOrm.id).where(DashboardOrm.id == target)
        )
        if exists is None:
            return None

        max_position = await session.scalar(
            select(func.max(DashboardSectionOrm.position)).where(
                DashboardSectionOrm.dashboard_id == target
            )
        )
        section = DashboardSectionOrm(
            dashboard_id=target,
            title=title,
            description=description,
            position=0 if max_position is None else max_position + 1,
            type=type,
        )
        session.add(section)
        await session.flush()

        rows = []
        for position, spec in enumerate(widgets or []):
            insight_id = spec.get("insight_id")
            rows.append(
                DashboardWidgetOrm(
                    dashboard_id=target,
                    widget_type=spec["widget_type"],
                    insight_id=(
                        _parse_uuid(insight_id) if insight_id else None
                    ),
                    config=relativize_widget_config(spec.get("config")) or {},
                    position=position,
                    section_id=section.id,
                )
            )
        session.add_all(rows)
        try:
            await session.commit()
        except IntegrityError as exc:
            if "uq_dashboard_widgets_dashboard_insight" not in str(exc.orig):
                raise
            # The insight is already on this dashboard, so the whole section
            # is rolled back rather than built without its chart.
            logger.warning(
                "dashboard_section_widget_duplicate",
                dashboard_id=str(target),
                type=type,
            )
            raise DuplicateInsightWidgetError(str(target), "") from exc

        section_id = str(section.id)
        widget_ids = [str(row.id) for row in rows]

    logger.info(
        "dashboard_section_added_with_widgets",
        dashboard_id=str(target),
        section_id=section_id,
        type=type,
        widgets=len(widget_ids),
    )
    return section_id, widget_ids


async def get_section(section_id) -> Optional[DashboardSectionOrm]:
    """Load a single section by id; the caller applies access checks via the
    owning dashboard. Malformed ids are not-found (None), never an error."""
    target = _parse_uuid(section_id)
    if target is None:
        return None
    async with get_session_from_pool() as session:
        return await session.get(DashboardSectionOrm, target)


async def update_section(
    section_id,
    *,
    title: Optional[str] = None,
    description=UNSET,
    position: Optional[int] = None,
) -> bool:
    """Retitle a section, restate its intent and/or reorder it.

    ``description`` is three-valued like ``update_widget``'s ``section_id``:
    omit it to leave the text alone, pass None to clear it.

    A sealed section takes a ``position`` change — that orders the dashboard
    rather than editing the section — but raises ``SealedSectionError`` for
    its title or description.
    """
    target = _parse_uuid(section_id)
    if target is None:
        return False
    async with get_session_from_pool() as session:
        section = await session.get(DashboardSectionOrm, target)
        if section is None:
            return False
        if title is not None or not isinstance(description, _Unset):
            _guard_sealed(section)
        if title is not None:
            section.title = title
        if not isinstance(description, _Unset):
            section.description = description
        if position is not None:
            section.position = position
        await session.commit()

    logger.info("dashboard_section_updated", section_id=str(target))
    return True


async def remove_section(section_id, *, delete_widgets: bool = False) -> bool:
    """Delete a section. By default its widgets survive, ungrouped.

    ``delete_widgets=True`` removes the section's widgets with it — the
    destructive variant, requested explicitly by the caller. Insights the
    deleted widgets referenced are left intact, as with ``remove_widget``.

    Deleting a sealed section is allowed, but it always takes its widgets:
    ungrouping them would leave loose, editable copies of content that is
    only meaningful — and only sealed — inside its own section.
    """
    target = _parse_uuid(section_id)
    if target is None:
        return False
    async with get_session_from_pool() as session:
        section = await session.get(DashboardSectionOrm, target)
        if section is None:
            return False

        if section.type in SEALED_SECTION_TYPES:
            delete_widgets = True

        if delete_widgets:
            result = await session.execute(
                delete(DashboardWidgetOrm).where(
                    DashboardWidgetOrm.section_id == target
                )
            )
            affected = result.rowcount or 0
        else:
            affected = await _ungroup_widgets(
                session, section.dashboard_id, target
            )

        await session.delete(section)
        await session.commit()

    logger.info(
        "dashboard_section_removed",
        section_id=str(target),
        delete_widgets=delete_widgets,
        widgets_affected=affected,
    )
    return True


async def _ungroup_widgets(session, dashboard_id, section_id) -> int:
    """Move a section's widgets to the ungrouped top level; return the count.

    Positions are container-scoped, so the orphans cannot keep the numbers
    they had inside the section — those collide with the top level's. They
    are renumbered as a block after the current last top-level widget, which
    preserves their order relative to each other and to what is already
    there. Done explicitly rather than by the ON DELETE SET NULL, so widgets
    already loaded in this session see the same state as the DB.
    """
    result = await session.execute(
        select(DashboardWidgetOrm)
        .where(DashboardWidgetOrm.section_id == section_id)
        .order_by(DashboardWidgetOrm.position)
    )
    orphans = list(result.scalars())
    if not orphans:
        return 0

    position = await _next_position(session, dashboard_id, None)
    for widget in orphans:
        widget.section_id = None
        widget.position = position
        position += 1
    await session.flush()
    return len(orphans)


async def update_dashboard(
    dashboard_id,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> bool:
    """Rename a dashboard and/or replace its description."""
    target = _parse_uuid(dashboard_id)
    if target is None:
        return False
    async with get_session_from_pool() as session:
        dashboard = await session.get(DashboardOrm, target)
        if dashboard is None:
            return False
        if name is not None:
            dashboard.name = name
        if description is not None:
            dashboard.description = description
        await session.commit()

    logger.info("dashboard_updated", dashboard_id=str(target))
    return True


async def delete_dashboard(dashboard_id) -> bool:
    """Delete a dashboard with its AOIs and widgets; insights are left intact."""
    target = _parse_uuid(dashboard_id)
    if target is None:
        return False
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(DashboardOrm)
            .options(
                selectinload(DashboardOrm.aois),
                selectinload(DashboardOrm.sections),
                selectinload(DashboardOrm.widgets),
            )
            .where(DashboardOrm.id == target)
        )
        dashboard = result.scalar_one_or_none()
        if dashboard is None:
            return False
        # The cascade deletes widgets before sections (SQLAlchemy follows the
        # section_id FK), so the ON DELETE SET NULL never fires here.
        await session.delete(dashboard)
        await session.commit()

    logger.info("dashboard_deleted", dashboard_id=str(target))
    return True


async def set_dashboard_public(
    dashboard_id, is_public: bool
) -> Optional[list[str]]:
    """Set a dashboard's is_public flag; return the insight ids it publicized.

    Publishing cascades ``is_public=True`` to all insights referenced by the
    dashboard's widgets in the same transaction — otherwise a public dashboard
    renders empty for viewers. Unpublishing does NOT cascade (the insights may
    be shared elsewhere). Returns the list of newly-publicized insight ids
    (empty when unsetting or nothing needed flipping), or None if the
    dashboard does not exist / the id is malformed.
    """
    target = _parse_uuid(dashboard_id)
    if target is None:
        return None
    async with get_session_from_pool() as session:
        dashboard = await session.get(DashboardOrm, target)
        if dashboard is None:
            return None

        dashboard.is_public = is_public

        publicized: list[str] = []
        if is_public:
            referenced = select(DashboardWidgetOrm.insight_id).where(
                DashboardWidgetOrm.dashboard_id == target,
                DashboardWidgetOrm.insight_id.is_not(None),
            )
            result = await session.execute(
                update(InsightOrm)
                .where(
                    InsightOrm.id.in_(referenced),
                    InsightOrm.is_public.is_(False),
                )
                .values(is_public=True)
                .returning(InsightOrm.id)
            )
            publicized = [str(row_id) for row_id in result.scalars()]

        await session.commit()

    logger.info(
        "dashboard_public_set",
        dashboard_id=str(target),
        is_public=is_public,
        publicized_insights=len(publicized),
    )
    return publicized
