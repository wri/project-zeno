"""Sentinel-2 mosaic imagery provider."""

from datetime import date, timedelta

from cogeo_mosaic.errors import MosaicNotFoundError

from src.agent.i18n import t
from src.agent.imagery.base import ImageryProviderResult, ImageryRequest
from src.agent.models import ImageryState
from src.api.services.mosaic import (
    AoiTooLargeError,
    MosaicRecipe,
    MosaicResult,
    NoScenesFoundError,
    StacSearchError,
    create_sentinel2_mosaic,
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

        imagery = ImageryState(
            provider="sentinel-2",
            tile_url=result.tile_url,
            tilejson_url=result.tilejson_url,
            mosaic_id=result.mosaic_id,
            item_count=result.item_count,
            start_date=(
                result.date_start.isoformat() if result.date_start else None
            ),
            end_date=result.date_end.isoformat() if result.date_end else None,
            mean_cloud_cover=result.mean_cloud_cover,
            min_cloud_cover=result.min_cloud_cover,
            max_cloud_cover_observed=result.max_cloud_cover,
            target_date=recipe.target_date.isoformat(),
            window_days=recipe.window_days,
            max_cloud_cover=recipe.max_cloud_cover,
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
    async def _feedback(
        key: str, request: ImageryRequest, **values
    ) -> ImageryProviderResult:
        return ImageryProviderResult(
            status="error",
            message=await t(key, request.language, **values),
        )
