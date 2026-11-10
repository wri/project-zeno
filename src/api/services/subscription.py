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


@dataclass
class Subscription:
    subscription_id: UUID
    dashboard_id: UUID
    user_id: str
    user_email: str
    aoi_type: AoiType
    aoi_id: str
    dataset: Dataset


class SubscriptionRepository(ABC):
    @abstractmethod
    async def list_active(self) -> list[Subscription]: ...
