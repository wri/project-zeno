"""Dashboard alert subscriptions stored in Postgres. Each row is one alert
channel turned on for one dataset of a dashboard."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.data_models import DashboardAoiOrm, SubscriptionOrm, UserOrm
from src.api.services.subscription import (
    AoiType,
    Dataset,
    Subscription,
    SubscriptionMode,
    SubscriptionModeRepository,
    SubscriptionRepository,
    SubscriptionTarget,
)
from src.shared.database import get_session_from_pool
from src.shared.geocoding_helpers import CONCESSION_SOURCES


class PostgresSubscriptionRepository(
    SubscriptionRepository, SubscriptionModeRepository
):
    async def list_active(self) -> list[Subscription]:
        """Lists the subscriptions with email on."""
        query = (
            select(
                SubscriptionOrm.id,
                SubscriptionOrm.dashboard_id,
                SubscriptionOrm.user_id,
                UserOrm.email,
                DashboardAoiOrm.source,
                DashboardAoiOrm.src_id,
                SubscriptionOrm.dataset,
            )
            .join(UserOrm, UserOrm.id == SubscriptionOrm.user_id)
            .join(
                DashboardAoiOrm, DashboardAoiOrm.id == SubscriptionOrm.aoi_id
            )
            .where(SubscriptionOrm.mode == SubscriptionMode.EMAIL)
            .order_by(SubscriptionOrm.created_at)
        )
        async with get_session_from_pool() as session:
            rows = (await session.execute(query)).all()

        aoi_types = {
            "gadm": AoiType.ADMIN,
            "wdpa": AoiType.PROTECTED_AREA,
            "kba": AoiType.KEY_BIODIVERSITY_AREA,
            "landmark": AoiType.INDIGENOUS_LAND,
            "custom": AoiType.CUSTOM,
        }
        for source in CONCESSION_SOURCES:
            aoi_types[source] = AoiType.CONCESSION
        return [
            Subscription(
                subscription_id=row.id,
                dashboard_id=row.dashboard_id,
                user_id=row.user_id,
                user_email=row.email,
                aoi_type=aoi_types[row.source],
                aoi_id=row.src_id,
                dataset=row.dataset,
            )
            for row in rows
        ]

    async def set_modes(
        self,
        target: SubscriptionTarget,
        dataset: Dataset,
        modes: set[SubscriptionMode],
    ) -> None:
        """Saves exactly these channels for the dashboard's dataset. Rows
        that are already in that state are left alone."""
        async with get_session_from_pool() as session:
            await session.execute(
                delete(SubscriptionOrm).where(
                    SubscriptionOrm.dashboard_id == target.dashboard_id,
                    SubscriptionOrm.dataset == dataset,
                    SubscriptionOrm.mode.not_in(modes),
                )
            )
            if modes:
                rows = [
                    {
                        "dashboard_id": target.dashboard_id,
                        "aoi_id": target.aoi_id,
                        "user_id": target.user_id,
                        "dataset": dataset,
                        "mode": mode,
                    }
                    for mode in modes
                ]
                await session.execute(
                    insert(SubscriptionOrm)
                    .values(rows)
                    .on_conflict_do_nothing(
                        constraint="uq_subscriptions_dashboard_dataset_mode"
                    )
                )
            await session.commit()


async def remove_email_subscriptions(
    session: AsyncSession, dashboard_id: UUID
) -> None:
    """Turns email off for every dataset of a dashboard, inside the
    caller's transaction."""
    await session.execute(
        delete(SubscriptionOrm).where(
            SubscriptionOrm.dashboard_id == dashboard_id,
            SubscriptionOrm.mode == SubscriptionMode.EMAIL,
        )
    )


def get_subscription_repository() -> SubscriptionRepository:
    return PostgresSubscriptionRepository()
