"""Centralized dashboard persistence shared by the API router and agent tools.

Both paths write the same ``DashboardOrm`` / ``DashboardAoiOrm`` /
``DashboardWidgetOrm`` rows; this is the single place that mapping lives.
Ownership checks live in the callers (router/tools) via ``dashboard_access``
— the same split as insights. Malformed UUIDs are treated as not-found
(None/False) rather than raising.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from src.api.data_models import (
    DashboardAoiOrm,
    DashboardOrm,
    DashboardWidgetOrm,
    InsightOrm,
)
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


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
    """Load a dashboard with its AOIs and widgets; caller applies access check."""
    target = _parse_uuid(dashboard_id)
    if target is None:
        return None
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(DashboardOrm)
            .options(
                selectinload(DashboardOrm.aois),
                selectinload(DashboardOrm.widgets),
            )
            .where(DashboardOrm.id == target)
        )
        return result.scalar_one_or_none()


async def add_widget(
    dashboard_id,
    *,
    widget_type: str,
    insight_id: Optional[str] = None,
    config: Optional[dict] = None,
    position: Optional[int] = None,
) -> Optional[str]:
    """Append a widget to a dashboard; return the new widget id (str).

    Position defaults to max+1 (end of the dashboard). Returns None if the
    dashboard does not exist or an id is malformed.
    """
    target = _parse_uuid(dashboard_id)
    if target is None:
        return None
    insight_uuid = None
    if insight_id is not None:
        insight_uuid = _parse_uuid(insight_id)
        if insight_uuid is None:
            return None

    async with get_session_from_pool() as session:
        exists = await session.scalar(
            select(DashboardOrm.id).where(DashboardOrm.id == target)
        )
        if exists is None:
            return None

        if position is None:
            max_position = await session.scalar(
                select(func.max(DashboardWidgetOrm.position)).where(
                    DashboardWidgetOrm.dashboard_id == target
                )
            )
            position = 0 if max_position is None else max_position + 1

        widget = DashboardWidgetOrm(
            dashboard_id=target,
            widget_type=widget_type,
            insight_id=insight_uuid,
            config=config or {},
            position=position,
        )
        session.add(widget)
        await session.commit()
        widget_id = str(widget.id)

    logger.info(
        "dashboard_widget_added",
        dashboard_id=str(target),
        widget_id=widget_id,
        widget_type=widget_type,
        insight_id=insight_id,
    )
    return widget_id


async def update_widget(
    widget_id,
    *,
    position: Optional[int] = None,
    config: Optional[dict] = None,
) -> bool:
    """Reorder a widget and/or replace its presentation config."""
    target = _parse_uuid(widget_id)
    if target is None:
        return False
    async with get_session_from_pool() as session:
        widget = await session.get(DashboardWidgetOrm, target)
        if widget is None:
            return False
        if position is not None:
            widget.position = position
        if config is not None:
            widget.config = config
        await session.commit()

    logger.info("dashboard_widget_updated", widget_id=str(target))
    return True


async def remove_widget(widget_id) -> bool:
    """Delete a widget; the referenced insight is left intact."""
    target = _parse_uuid(widget_id)
    if target is None:
        return False
    async with get_session_from_pool() as session:
        widget = await session.get(DashboardWidgetOrm, target)
        if widget is None:
            return False
        await session.delete(widget)
        await session.commit()

    logger.info("dashboard_widget_removed", widget_id=str(target))
    return True


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
                selectinload(DashboardOrm.widgets),
            )
            .where(DashboardOrm.id == target)
        )
        dashboard = result.scalar_one_or_none()
        if dashboard is None:
            return False
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
