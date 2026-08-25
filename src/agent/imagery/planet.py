"""Planet monthly mosaic imagery provider."""

from datetime import date, timedelta
from typing import Optional

from src.agent.imagery.base import ImageryProviderResult, ImageryRequest
from src.agent.models import ImageryState


class PlanetImageryProvider:
    """Build imagery state for the limited-coverage Planet tile service."""

    BASE_URL = "https://tiles.globalforestwatch.org"
    COVERAGE = (-70.0, -10.0, -60.0, 0.0)

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

    async def get_imagery(
        self, request: ImageryRequest
    ) -> ImageryProviderResult:
        month = self.month(request.target_date)
        month_start = date.fromisoformat(f"{month}-01")
        next_month = date(
            month_start.year + (month_start.month == 12),
            month_start.month % 12 + 1,
            1,
        )
        month_end = next_month - timedelta(days=1)
        imagery = ImageryState(
            provider="planet",
            tile_url=(
                f"{self.BASE_URL}/integrated_alerts_planet_imagery/"
                f"{{z}}/{{x}}/{{y}}.png?month={month}"
            ),
            bounds=self._bounds(request.aois),
            min_zoom=5,
            max_zoom=15,
            mosaic_id=f"planet:{month}",
            start_date=month_start.isoformat(),
            end_date=month_end.isoformat(),
            target_date=(
                request.target_date.isoformat()
                if request.target_date
                else None
            ),
            aoi_names=[aoi["name"] for aoi in request.aois],
        )
        message = (
            "Showing the limited-coverage Planet monthly mosaic for "
            f"{month_start.strftime('%B')} {month_start.day}–{month_end.day}, "
            f"{month_start.year}. Sentinel-2 imagery is also available if "
            "you'd like to compare it."
        )
        return ImageryProviderResult(
            status="success", imagery=imagery, message=message
        )
