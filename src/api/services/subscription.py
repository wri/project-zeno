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


class SubscriptionMode(str, Enum):
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


class EmailAlertsUnavailableError(Exception):
    def __init__(self):
        super().__init__(
            "Email alerts need an integrated alerts chart or map on the "
            "dashboard"
        )


class SubscriptionRepository(ABC):
    @abstractmethod
    async def list_active(self) -> list[Subscription]: ...


class SubscriptionModeRepository(ABC):
    @abstractmethod
    async def set_modes(
        self,
        target: SubscriptionTarget,
        dataset: Dataset,
        modes: set[SubscriptionMode],
    ) -> None: ...


class SubscriptionService:
    """Turns a dashboard's alert channels on or off."""

    def __init__(self, repository: SubscriptionModeRepository):
        self.repository = repository

    async def update(
        self,
        target: SubscriptionTarget,
        datasets: set[Dataset],
        requested: set[SubscriptionMode],
    ) -> None:
        """Saves the requested channels for each dataset. Nothing is saved
        if email is asked for on a dashboard that can't have email alerts."""
        # ponytail: eligibility is read before the write, without a lock, so
        # a widget removed in between can leave email on; lock the dashboard
        # row if that ever matters.
        if (
            SubscriptionMode.EMAIL in requested
            and not target.eligible_for_subscription
        ):
            raise EmailAlertsUnavailableError()
        for dataset in datasets:
            await self.repository.set_modes(target, dataset, requested)
