"""Sentinel-2 imagery provider: the request, rendered in the browser.

The provider does no I/O. It resolves the request (target date, search
window, cloud limit) into a recipe and writes its token as ``mosaic_id``
with ``render="client"``. The frontend decodes the token, searches
earth-search and draws the scenes' COGs itself (project-zeno-next
``src/features/imagery``). There is no STAC search, no S3 mosaic and no tile
URL on the server.

The scene search result (count, dates, or "no scenes" / "area too large")
exists only in the browser. The frontend reports it in the view context
(``visible_imagery``), so the agent sees it on the next message.
"""

from datetime import date, timedelta

from src.agent.i18n import t
from src.agent.imagery.base import ImageryProviderResult, ImageryRequest
from src.agent.models import ImageryState
from src.shared.imagery_recipe import MosaicRecipe, encode_recipe
from src.shared.request_context import current_user_id

DEFAULT_WINDOW_DAYS = 7
DEFAULT_MAX_CLOUD_COVER = 20


def resolve_recipe(request: ImageryRequest) -> MosaicRecipe:
    """The request with the backend defaults and limits applied.

    No date means about the past two weeks: target a week ago, ±7 days.
    """
    aoi_refs = tuple((aoi["source"], aoi["src_id"]) for aoi in request.aois)
    user_id = None
    if any(source == "custom" for source, _ in aoi_refs):
        # Custom areas belong to a user: the geometry endpoint scopes the
        # lookup by owner, and the token carries the owner (as before).
        user_id = current_user_id()
    return MosaicRecipe(
        aois=aoi_refs,
        target_date=request.target_date
        or (date.today() - timedelta(days=DEFAULT_WINDOW_DAYS)),
        window_days=max(1, min(request.window_days, 183))
        if request.window_days is not None
        else DEFAULT_WINDOW_DAYS,
        max_cloud_cover=max(1, min(request.max_cloud_cover, 100))
        if request.max_cloud_cover is not None
        else DEFAULT_MAX_CLOUD_COVER,
        user_id=user_id,
    )


class Sentinel2ImageryProvider:
    """Resolve a Sentinel-2 request into a client-rendered imagery state."""

    async def get_imagery(
        self, request: ImageryRequest
    ) -> ImageryProviderResult:
        recipe = resolve_recipe(request)
        aoi_names = [aoi["name"] for aoi in request.aois]
        imagery = ImageryState(
            provider="sentinel-2",
            render="client",
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
