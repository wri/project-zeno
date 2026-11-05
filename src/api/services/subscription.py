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


class Dataset(str, Enum):
    INTEGRATED_ALERTS = "integrated_alerts"


class SubscriptionMode(str, Enum):
    EMAIL = "email"
    IN_APP = "in-app"


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


class EmailAlertsUnavailableError(Exception):
    def __init__(self):
        super().__init__(
            "Email alerts need an integrated alerts chart and a GADM admin "
            "area on the dashboard"
        )


class SubscriptionRepository(ABC):
    @abstractmethod
    async def list_active(self) -> list[Subscription]: ...


class SubscriptionModeRepository(ABC):
    @abstractmethod
    async def list_modes(
        self, dashboard_id: UUID, dataset: Dataset
    ) -> set[SubscriptionMode]: ...

    @abstractmethod
    async def set_modes(
        self,
        target: SubscriptionTarget,
        dataset: Dataset,
        modes: set[SubscriptionMode],
    ) -> None: ...


class EmailEligibility(ABC):
    @abstractmethod
    async def allows_email(self, dashboard_id: UUID) -> bool: ...


def modes_to_store(requested: set[SubscriptionMode]) -> set[SubscriptionMode]:
    """The modes to save for a request. Email can't be on without in-app, so
    asking for email turns in-app on too."""
    if SubscriptionMode.EMAIL in requested:
        return requested | {SubscriptionMode.IN_APP}
    return requested


class SubscriptionService:
    """Turns a dashboard's alert modes on or off."""

    def __init__(
        self,
        repository: SubscriptionModeRepository,
        eligibility: EmailEligibility,
    ):
        self.repository = repository
        self.eligibility = eligibility

    async def update(
        self,
        target: SubscriptionTarget,
        datasets: set[Dataset],
        requested: set[SubscriptionMode],
    ) -> None:
        """Saves the requested modes for each dataset. Nothing is saved if
        email would turn on for a dashboard that can't have email alerts."""
        changes = {}
        email_turns_on = False
        for dataset in datasets:
            current = await self.repository.list_modes(
                target.dashboard_id, dataset
            )
            changes[dataset] = modes_to_store(requested)
            if SubscriptionMode.EMAIL in changes[dataset] - current:
                email_turns_on = True

        if email_turns_on and not await self.eligibility.allows_email(
            target.dashboard_id
        ):
            raise EmailAlertsUnavailableError()

        for dataset, modes in changes.items():
            await self.repository.set_modes(target, dataset, modes)
