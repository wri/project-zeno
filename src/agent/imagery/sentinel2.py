"""Sentinel-2 mosaic imagery provider."""

from datetime import date, timedelta
from typing import Optional

from cogeo_mosaic.errors import MosaicNotFoundError

from src.agent.i18n import t
from src.agent.imagery.base import (
    ImageryProviderResult,
    ImageryRequest,
    aoi_bounds,
)
from src.api.services.mosaic import (
    MOSAIC_MAXZOOM,
    MOSAIC_MINZOOM,
    AoiTooLargeError,
    MosaicRecipe,
    MosaicResult,
    NoScenesFoundError,
    StacSearchError,
    create_sentinel2_mosaic,
)
from src.shared.imagery.contract import RasterSource
from src.shared.imagery.sentinel2 import (
    SceneSummary,
    SearchWindowPeriod,
    Sentinel2Imagery,
)
from src.shared.logging_config import get_logger
from src.shared.request_context import current_user_id

logger = get_logger(__name__)


class Sentinel2ImageryProvider:
    """Create and normalize Sentinel-2 mosaics."""

    async def get_imagery(
        self, request: ImageryRequest
    ) -> ImageryProviderResult:
        aoi_refs = tuple(
            (aoi["source"], aoi["src_id"]) for aoi in request.aois
        )
        user_id = None
        if any(source == "custom" for source, _ in aoi_refs):
            user_id = current_user_id()

        recipe = MosaicRecipe(
            aois=aoi_refs,
            target_date=request.target_date
            or (date.today() - timedelta(days=7)),
            window_days=max(1, min(request.window_days, 183))
            if request.window_days is not None
            else 7,
            max_cloud_cover=max(1, min(request.max_cloud_cover, 100))
            if request.max_cloud_cover is not None
            else 20,
            user_id=user_id,
        )
        try:
            result: MosaicResult = await create_sentinel2_mosaic(recipe)
        except MosaicNotFoundError:
            return await self._feedback("show_imagery.geometry_error", request)
        except AoiTooLargeError as error:
            return await self._feedback(
                "show_imagery.aoi_too_large", request, error=str(error)
            )
        except NoScenesFoundError:
            return await self._feedback(
                "show_imagery.no_scenes_found",
                request,
                cloud_cover=recipe.max_cloud_cover,
                window_days=recipe.window_days,
                target_date=recipe.target_date,
            )
        except StacSearchError:
            return await self._feedback(
                "show_imagery.stac_unavailable", request
            )
        except Exception as error:
            logger.exception(
                "show_imagery failed unexpectedly",
                error=str(error),
                aoi_names=[aoi["name"] for aoi in request.aois],
                target_date=recipe.target_date.isoformat(),
            )
            return await self._feedback(
                "show_imagery.unexpected_error", request
            )

        imagery = Sentinel2Imagery(
            period=SearchWindowPeriod.from_search(
                recipe.target_date, recipe.window_days, today=date.today()
            ),
            layer_id=result.mosaic_id,
            tile_url=result.tile_url,
            source=RasterSource(
                tiles=[result.tile_url],
                bounds=aoi_bounds(request.aois),
                minzoom=MOSAIC_MINZOOM,
                maxzoom=MOSAIC_MAXZOOM,
            ),
            mosaic_id=result.mosaic_id,
            max_cloud_cover=recipe.max_cloud_cover,
            scenes=self._scenes(result),
            aoi_names=[aoi["name"] for aoi in request.aois],
        )
        summary = ""
        if result.item_count is not None:
            summary = await t(
                "show_imagery.success_summary",
                request.language,
                count=result.item_count,
                start=result.date_start,
                end=result.date_end,
            )
        message = await t(
            "show_imagery.success",
            request.language,
            aois=", ".join(imagery.aoi_names),
            summary=summary,
        )
        return ImageryProviderResult(
            status="success", imagery=imagery, message=message
        )

    @staticmethod
    def _scenes(result: MosaicResult) -> Optional[SceneSummary]:
        stats = {
            "item_count": result.item_count,
            "start_date": result.date_start,
            "end_date": result.date_end,
            "mean_cloud_cover": result.mean_cloud_cover,
            "min_cloud_cover": result.min_cloud_cover,
            "max_cloud_cover": result.max_cloud_cover,
        }
        if any(stat is None for stat in stats.values()):
            return None
        return SceneSummary(**stats)

    @staticmethod
    async def _feedback(
        key: str, request: ImageryRequest, **values
    ) -> ImageryProviderResult:
        return ImageryProviderResult(
            status="error",
            message=await t(key, request.language, **values),
        )
