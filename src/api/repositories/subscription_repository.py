"""Dashboard alert subscriptions (ADR 0012, Option D).

A ``subscriptions`` row means one mode is on for one dataset of a dashboard.
``set_modes`` is the only writer, and it applies the coupling rule: email is
never on without in-app.
"""

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
    SubscriptionRepository,
)
from src.shared.database import get_session_from_pool

EMAIL = SubscriptionMode.EMAIL
IN_APP = SubscriptionMode.IN_APP

# dashboard_aois.source → the pipeline's AOI type.
AOI_TYPES = {
    "gadm": AoiType.ADMIN,
    "wdpa": AoiType.PROTECTED_AREA,
    "kba": AoiType.KEY_BIODIVERSITY_AREA,
    "landmark": AoiType.INDIGENOUS_LAND,
    "custom": AoiType.CUSTOM,
}


def coupled_modes(
    current: set[SubscriptionMode], desired: set[SubscriptionMode]
) -> set[SubscriptionMode]:
    """The modes to store when ``desired`` is asked for over ``current``.

    Turning email on also turns in-app on, and turning in-app off also turns
    email off. Turning email off leaves in-app alone. A request that does
    both (email on, in-app off) turns email on.
    """
    if EMAIL in desired and EMAIL not in current:
        return desired | {IN_APP}
    if IN_APP not in desired:
        return desired - {EMAIL}
    return desired


async def set_modes(
    *,
    dashboard_id: UUID,
    aoi_id: UUID,
    user_id: str,
    dataset: Dataset,
    modes: set[SubscriptionMode],
) -> None:
    """Store exactly ``modes`` (already coupled) for the dashboard's dataset.

    Rows already in the right state are left untouched, so setting the value
    a dashboard already has changes nothing.
    """
    async with get_session_from_pool() as session:
        await session.execute(
            delete(SubscriptionOrm).where(
                SubscriptionOrm.dashboard_id == dashboard_id,
                SubscriptionOrm.dataset == dataset,
                SubscriptionOrm.mode.not_in(modes),
            )
        )
        if modes:
            await session.execute(
                insert(SubscriptionOrm)
                .values(
                    [
                        {
                            "dashboard_id": dashboard_id,
                            "aoi_id": aoi_id,
                            "user_id": user_id,
                            "dataset": dataset,
                            "mode": mode,
                        }
                        for mode in modes
                    ]
                )
                .on_conflict_do_nothing(
                    constraint="uq_subscriptions_dashboard_dataset_mode"
                )
            )
        await session.commit()


class PostgresSubscriptionRepository(SubscriptionRepository):
    async def list_active(self) -> list[Subscription]:
        """Email rows whose dashboard also has in-app on for the dataset.

        Eligibility isn't re-checked here (ADR follow-up F1).
        """
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
                email.mode == EMAIL,
                exists().where(
                    in_app.dashboard_id == email.dashboard_id,
                    in_app.dataset == email.dataset,
                    in_app.mode == IN_APP,
                ),
            )
            .order_by(email.created_at)
        )
        async with get_session_from_pool() as session:
            rows = (await session.execute(query)).all()
        return [
            Subscription(
                subscription_id=row.id,
                dashboard_id=row.dashboard_id,
                user_id=row.user_id,
                user_email=row.email,
                aoi_type=AOI_TYPES[row.source],
                aoi_id=row.src_id,
                dataset=row.dataset,
            )
            for row in rows
        ]


def get_subscription_repository() -> SubscriptionRepository:
    return PostgresSubscriptionRepository()
