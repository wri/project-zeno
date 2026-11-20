from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class AoiType(str, Enum):
    ADMIN = "admin"
    PROTECTED_AREA = "protected_area"
    KEY_BIODIVERSITY_AREA = "key_biodiversity_area"
    INDIGENOUS_LAND = "indigenous_land"
    CUSTOM = "custom"
    CONCESSION = "concession"


class Dataset(str, Enum):
    INTEGRATED_ALERTS = "integrated_alerts"


class SubscriptionChannel(str, Enum):
    EMAIL = "email"


@dataclass
class Subscription:
    subscription_id: UUID
    dashboard_id: UUID
    user_id: str
    user_email: str
    aoi_type: AoiType
    aoi_id: str
    dataset: Dataset


@dataclass
class SubscriptionTarget:
    """The dashboard, its area and its owner that a subscription belongs to."""

    dashboard_id: UUID
    aoi_id: UUID
    user_id: str
    eligible_for_subscription: bool


class NotEligibleForSubscriptionError(Exception):
    def __init__(self):
        super().__init__(
            "Notification emails need an integrated alerts chart or map on "
            "the dashboard"
        )


class SubscriptionRepository(ABC):
    @abstractmethod
    async def list_active(self) -> list[Subscription]: ...


@dataclass
class BulkSubscribeResult:
    subscribed: list[UUID]
    skipped: list[UUID]


class SubscriptionChannelRepository(ABC):
    @abstractmethod
    async def set_channels(
        self,
        target: SubscriptionTarget,
        dataset: Dataset,
        channels: set[SubscriptionChannel],
    ) -> None: ...

    @abstractmethod
    async def remove_channel_for_user(
        self, user_id: str, channel: SubscriptionChannel
    ) -> list[UUID]:
        """Removes the channel from all of the user's dashboards and returns
        the dashboards that had it."""

    @abstractmethod
    async def find_owned_targets(
        self, user_id: str, dashboard_ids: list[UUID]
    ) -> list[SubscriptionTarget]:
        """The listed dashboards that the user owns and that have an area."""

    @abstractmethod
    async def add_channel(
        self,
        targets: list[SubscriptionTarget],
        dataset: Dataset,
        channel: SubscriptionChannel,
    ) -> None: ...


class SubscriptionService:
    """Subscribes a dashboard to channels or unsubscribes it."""

    def __init__(self, repository: SubscriptionChannelRepository):
        self.repository = repository

    async def update(
        self,
        target: SubscriptionTarget,
        datasets: set[Dataset],
        requested: set[SubscriptionChannel],
    ) -> None:
        """Saves the requested channels for each dataset. Nothing is saved
        if email is asked for on a dashboard not eligible for subscription."""
        # Eligibility is read before the write without a lock, so a widget
        # removed in between can leave email on. Lock the dashboard row if
        # that matters.
        if (
            SubscriptionChannel.EMAIL in requested
            and not target.eligible_for_subscription
        ):
            raise NotEligibleForSubscriptionError()
        for dataset in datasets:
            await self.repository.set_channels(target, dataset, requested)

    async def remove_for_user(
        self, user_id: str, channel: SubscriptionChannel
    ) -> list[UUID]:
        """Turns the channel off for every dashboard the user subscribed."""
        return await self.repository.remove_channel_for_user(user_id, channel)

    async def add_for_user(
        self,
        user_id: str,
        channel: SubscriptionChannel,
        dashboard_ids: list[UUID],
    ) -> BulkSubscribeResult:
        """Turns the channel on for the user's own dashboards in the list.
        Dashboards that are not eligible, or not the user's, are skipped."""
        targets = await self.repository.find_owned_targets(
            user_id, dashboard_ids
        )
        eligible = [t for t in targets if t.eligible_for_subscription]
        if eligible:
            for dataset in Dataset:
                await self.repository.add_channel(eligible, dataset, channel)
        subscribed = [t.dashboard_id for t in eligible]
        return BulkSubscribeResult(
            subscribed=subscribed,
            skipped=[i for i in dashboard_ids if i not in subscribed],
        )
