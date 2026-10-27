from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass
class Subscription:
    subscription_id: UUID
    dashboard_id: UUID
    aoi_id: UUID
    dataset_id: int


class SubscriptionRepository(ABC):
    @abstractmethod
    async def list_active(self) -> list[Subscription]: ...
