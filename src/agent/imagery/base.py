"""Shared contract for satellite imagery providers."""

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional, Protocol

from src.agent.models import ImageryState


@dataclass(frozen=True)
class ImageryRequest:
    """Provider-independent inputs resolved by the imagery tool."""

    aois: list[dict]
    target_date: Optional[date]
    language: str
    window_days: Optional[int] = None
    max_cloud_cover: Optional[int] = None


@dataclass(frozen=True)
class ImageryProviderResult:
    """Normalized result returned by every imagery provider."""

    status: Literal["success", "error"]
    message: str
    imagery: Optional[ImageryState] = None


class ImageryProvider(Protocol):
    """Contract implemented by imagery systems."""

    async def get_imagery(
        self, request: ImageryRequest
    ) -> ImageryProviderResult: ...
