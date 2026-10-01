"""Planet monthly mosaic imagery provider."""

import hashlib
import json
from datetime import date, timedelta
from typing import Optional

from src.agent.imagery.base import ImageryProviderResult, ImageryRequest
from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery


class PlanetImageryProvider:
    """Build imagery state for the limited-coverage Planet tile service."""

    BASE_URL = "https://tiles.globalforestwatch.org"
    COVERAGE = (-80.0, -30.0, -40.0, 20.0)

    def covers(self, aois: list[dict]) -> bool:
        west, south, east, north = self.COVERAGE
        return bool(aois) and all(
            (bbox := aoi.get("bbox"))
            and bbox[0] <= east
            and bbox[2] >= west
            and bbox[1] <= north
            and bbox[3] >= south
            for aoi in aois
        )

    def is_newer_than_last_full_month(
        self, target: Optional[date], *, today: Optional[date] = None
    ) -> bool:
        if target is None:
            return False
        return target >= (today or date.today()).replace(day=1)

    def month(
        self, target: Optional[date], *, today: Optional[date] = None
    ) -> str:
        if target is None:
            target = (today or date.today()).replace(day=1) - timedelta(days=1)
        return target.strftime("%Y-%m")

    @staticmethod
    def _bounds(aois: list[dict]) -> list[float]:
        bboxes = [aoi["bbox"] for aoi in aois]
        return [
            min(bbox[0] for bbox in bboxes),
            min(bbox[1] for bbox in bboxes),
            max(bbox[2] for bbox in bboxes),
            max(bbox[3] for bbox in bboxes),
        ]

    @staticmethod
    def _layer_id(month: str, aois: list[dict]) -> str:
        refs = sorted([aoi["source"], aoi["src_id"]] for aoi in aois)
        payload = json.dumps([month, refs])
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    async def get_imagery(
        self, request: ImageryRequest
    ) -> ImageryProviderResult:
        month = self.month(request.target_date)
        period = MonthlyPeriod.from_month(month)
        imagery = PlanetImagery(
            period=period,
            layer_id=self._layer_id(month, request.aois),
            tile_url=(
                f"{self.BASE_URL}/integrated_alerts_planet_imagery/"
                f"{{z}}/{{x}}/{{y}}.png?month={month}"
            ),
            bounds=self._bounds(request.aois),
            min_zoom=10,
            max_zoom=18,
            aoi_names=[aoi["name"] for aoi in request.aois],
        )
        message = (
            "Showing the limited-coverage Planet monthly mosaic for "
            f"{period.start.strftime('%B')} {period.start.day}–{period.end.day}, "
            f"{period.start.year}. Sentinel-2 imagery is also available if "
            "you'd like to compare it."
        )
        return ImageryProviderResult(
            status="success", imagery=imagery, message=message
        )
