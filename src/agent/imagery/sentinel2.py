"""Sentinel-2 imagery provider: the request, rendered in the browser.

The provider does no I/O. It resolves the request (target date, search
window, cloud limit) into a recipe and writes its token as ``mosaic_id``.
The frontend decodes the token, searches earth-search and draws the scenes
itself (project-zeno-next ``src/features/imagery``). The scene search result
exists only in the browser; it reports it in ``view_context.visible_imagery``.
"""

from datetime import date, timedelta

from src.agent.i18n import t
from src.agent.imagery.base import ImageryProviderResult, ImageryRequest
from src.agent.models import ImageryState
from src.shared.imagery_recipe import ImageryRecipe, encode_recipe

DEFAULT_WINDOW_DAYS = 7
# Loose on purpose: the map ranks scenes least cloudy first, so a high limit
# only adds fallback scenes where nothing clearer covers the area.
DEFAULT_MAX_CLOUD_COVER = 50


def resolve_recipe(request: ImageryRequest) -> ImageryRecipe:
    """The request with the backend defaults and limits applied.

    No date means about the past two weeks: target a week ago, ±7 days.
    """
    # src_id as a string: some sources have numeric ids, and the frontend
    # reads (and rebuilds) the token with string ids.
    aoi_refs = tuple(
        (aoi["source"], str(aoi["src_id"])) for aoi in request.aois
    )
    return ImageryRecipe(
        aois=aoi_refs,
        target_date=request.target_date
        or (date.today() - timedelta(days=DEFAULT_WINDOW_DAYS)),
        window_days=max(1, min(request.window_days, 183))
        if request.window_days is not None
        else DEFAULT_WINDOW_DAYS,
        max_cloud_cover=max(1, min(request.max_cloud_cover, 100))
        if request.max_cloud_cover is not None
        else DEFAULT_MAX_CLOUD_COVER,
    )


class Sentinel2ImageryProvider:
    """Resolve a Sentinel-2 request into the imagery state the map renders."""

    async def get_imagery(
        self, request: ImageryRequest
    ) -> ImageryProviderResult:
        recipe = resolve_recipe(request)
        aoi_names = [aoi["name"] for aoi in request.aois]
        imagery = ImageryState(
            provider="sentinel-2",
            mosaic_id=encode_recipe(recipe),
            target_date=recipe.target_date.isoformat(),
            window_days=recipe.window_days,
            max_cloud_cover=recipe.max_cloud_cover,
            aoi_names=aoi_names,
        )
        message = await t(
            "show_imagery.success_client",
            request.language,
            aois=", ".join(aoi_names),
            target_date=recipe.target_date.isoformat(),
            window_days=recipe.window_days,
            cloud_cover=recipe.max_cloud_cover,
        )
        return ImageryProviderResult(
            status="success", imagery=imagery, message=message
        )
