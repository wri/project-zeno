"""Dashboard subscriptions stored in Postgres. Each row is one channel a
dashboard is subscribed to for one dataset."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.data_models import (
    DashboardAoiOrm,
    DashboardOrm,
    SubscriptionOrm,
    UserOrm,
)
from src.api.services.subscription import (
    AoiType,
    Dataset,
    Subscription,
    SubscriptionChannel,
    SubscriptionChannelRepository,
    SubscriptionRepository,
    SubscriptionTarget,
)
from src.shared.database import get_session_from_pool
from src.shared.geocoding_helpers import CONCESSION_SOURCES


class PostgresSubscriptionRepository(
    SubscriptionRepository, SubscriptionChannelRepository
):
    async def list_active(self) -> list[Subscription]:
        """Lists the email subscriptions."""
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
            .where(SubscriptionOrm.channel == SubscriptionChannel.EMAIL)
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

    async def set_channels(
        self,
        target: SubscriptionTarget,
        dataset: Dataset,
        channels: set[SubscriptionChannel],
    ) -> None:
        """Saves exactly these channels for the dashboard's dataset. Rows
        that are already in that state are left alone."""
        async with get_session_from_pool() as session:
            await session.execute(
                delete(SubscriptionOrm).where(
                    SubscriptionOrm.dashboard_id == target.dashboard_id,
                    SubscriptionOrm.dataset == dataset,
                    SubscriptionOrm.channel.not_in(channels),
                )
            )
            if channels:
                rows = [
                    {
                        "dashboard_id": target.dashboard_id,
                        "aoi_id": target.aoi_id,
                        "user_id": target.user_id,
                        "dataset": dataset,
                        "channel": channel,
                    }
                    for channel in channels
                ]
                await session.execute(
                    insert(SubscriptionOrm)
                    .values(rows)
                    .on_conflict_do_nothing(
                        constraint="uq_subscriptions_dashboard_dataset_channel"
                    )
                )
            await session.commit()

    async def remove_channel_for_user(
        self, user_id: str, channel: SubscriptionChannel
    ) -> list[UUID]:
        async with get_session_from_pool() as session:
            result = await session.execute(
                delete(SubscriptionOrm)
                .where(
                    SubscriptionOrm.user_id == user_id,
                    SubscriptionOrm.channel == channel,
                )
                .returning(SubscriptionOrm.dashboard_id)
            )
            dashboard_ids = list(dict.fromkeys(result.scalars().all()))
            await session.commit()
        return dashboard_ids

    async def find_owned_targets(
        self, user_id: str, dashboard_ids: list[UUID]
    ) -> list[SubscriptionTarget]:
        query = (
            select(
                DashboardOrm.id,
                DashboardOrm.eligible_for_subscription,
                DashboardAoiOrm.id.label("aoi_id"),
            )
            .join(
                DashboardAoiOrm,
                DashboardAoiOrm.dashboard_id == DashboardOrm.id,
            )
            .where(
                DashboardOrm.user_id == user_id,
                DashboardOrm.id.in_(dashboard_ids),
            )
            .order_by(DashboardOrm.id, DashboardAoiOrm.position)
            .distinct(DashboardOrm.id)
        )
        async with get_session_from_pool() as session:
            rows = (await session.execute(query)).all()
        return [
            SubscriptionTarget(
                dashboard_id=row.id,
                aoi_id=row.aoi_id,
                user_id=user_id,
                eligible_for_subscription=row.eligible_for_subscription,
            )
            for row in rows
        ]

    async def add_channel(
        self,
        targets: list[SubscriptionTarget],
        dataset: Dataset,
        channel: SubscriptionChannel,
    ) -> None:
        rows = [
            {
                "dashboard_id": target.dashboard_id,
                "aoi_id": target.aoi_id,
                "user_id": target.user_id,
                "dataset": dataset,
                "channel": channel,
            }
            for target in targets
        ]
        async with get_session_from_pool() as session:
            await session.execute(
                insert(SubscriptionOrm)
                .values(rows)
                .on_conflict_do_nothing(
                    constraint="uq_subscriptions_dashboard_dataset_channel"
                )
            )
            await session.commit()


async def remove_email_subscriptions(
    session: AsyncSession, dashboard_id: UUID
) -> None:
    """Unsubscribes a dashboard from email for every dataset, inside the
    caller's transaction."""
    await session.execute(
        delete(SubscriptionOrm).where(
            SubscriptionOrm.dashboard_id == dashboard_id,
            SubscriptionOrm.channel == SubscriptionChannel.EMAIL,
        )
    )


def get_subscription_repository() -> SubscriptionRepository:
    return PostgresSubscriptionRepository()
