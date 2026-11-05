"""Dashboard alert subscriptions stored in Postgres. Each row is one alert
mode turned on for one dataset of a dashboard."""

from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

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


class PostgresSubscriptionRepository(
    SubscriptionRepository, SubscriptionModeRepository
):
    async def list_active(self) -> list[Subscription]:
        """Lists active subscriptions: email on, with in-app also on."""
        email = aliased(SubscriptionOrm)
        in_app = aliased(SubscriptionOrm)
        query = (
            select(
                email.id,
                email.dashboard_id,
                email.user_id,
                UserOrm.email,
                DashboardAoiOrm.source,
                DashboardAoiOrm.src_id,
                email.dataset,
            )
            .join(UserOrm, UserOrm.id == email.user_id)
            .join(DashboardAoiOrm, DashboardAoiOrm.id == email.aoi_id)
            .where(
                email.mode == SubscriptionMode.EMAIL,
                exists().where(
                    in_app.dashboard_id == email.dashboard_id,
                    in_app.dataset == email.dataset,
                    in_app.mode == SubscriptionMode.IN_APP,
                ),
            )
            .order_by(email.created_at)
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

    async def list_modes(
        self, dashboard_id: UUID, dataset: Dataset
    ) -> set[SubscriptionMode]:
        async with get_session_from_pool() as session:
            result = await session.execute(
                select(SubscriptionOrm.mode).where(
                    SubscriptionOrm.dashboard_id == dashboard_id,
                    SubscriptionOrm.dataset == dataset,
                )
            )
            return set(result.scalars().all())

    async def set_modes(
        self,
        target: SubscriptionTarget,
        dataset: Dataset,
        modes: set[SubscriptionMode],
    ) -> None:
        """Saves exactly these modes for the dashboard's dataset. Rows that
        are already in that state are left alone."""
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


def get_subscription_repository() -> SubscriptionRepository:
    return PostgresSubscriptionRepository()
