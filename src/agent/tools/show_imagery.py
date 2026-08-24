from datetime import date
from typing import Annotated, Dict, Literal, Optional

import httpx
from cogeo_mosaic.errors import MosaicNotFoundError
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.models import ImageryState
from src.agent.tool_spec import ToolCategory, ToolSpec
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

PLANET_BASE_URL = "https://tfo-wmts-proxy-5ufe6llh5a-uc.a.run.app"
PLANET_COVERAGE = (-70.0, -10.0, -60.0, 0.0)


async def _fetch_planet_mosaics() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{PLANET_BASE_URL}/wmts/v1/mosaics")
        response.raise_for_status()
        return response.json()


def _planet_covers(aois: list[dict]) -> bool:
    west, south, east, north = PLANET_COVERAGE
    return bool(aois) and all(
        (bbox := aoi.get("bbox"))
        and bbox[0] <= east
        and bbox[2] >= west
        and bbox[1] <= north
        and bbox[3] >= south
        for aoi in aois
    )


def _planet_mosaic(
    mosaics: list[dict], target: Optional[date]
) -> Optional[dict]:
    if not mosaics:
        return None
    if target is None:
        return max(mosaics, key=lambda mosaic: mosaic["first_acquired"])
    target_iso = target.isoformat()
    return next(
        (
            mosaic
            for mosaic in mosaics
            if mosaic["first_acquired"][:10]
            <= target_iso
            < mosaic["last_acquired"][:10]
        ),
        None,
    )


def _feedback(message: str, tool_call_id: Optional[str]) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    message,
                    tool_call_id=tool_call_id,
                    status="success",
                    response_metadata={"msg_type": "human_feedback"},
                )
            ],
        },
    )


@tool("show_imagery")
async def show_imagery(
    state: Annotated[Dict, InjectedState],
    provider: Optional[Literal["sentinel-2", "planet"]] = None,
    target_date: Optional[str] = None,
    window_days: Optional[int] = None,
    max_cloud_cover: Optional[int] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Show a satellite imagery layer on the map for the AOI in state.

    provider may be planet or sentinel-2. When omitted, Planet is preferred
    where its limited coverage and requested month are available, otherwise
    Sentinel-2 is used. target_date (YYYY-MM-DD) selects the Planet monthly
    mosaic or the date Sentinel-2 imagery should be closest to. window_days
    (default 7, max 183) widens the Sentinel-2
    search to ±N days around target_date; max_cloud_cover (default 20,
    percent) loosens the cloud filter. Only raise them when the defaults
    find no scenes and the user agrees. Run pick_aoi first. Regional
    areas only.
    """
    logger.info("show_imagery tool called")
    language = (state or {}).get("language") or DEFAULT_LANGUAGE
    aois = ((state or {}).get("aoi_selection") or {}).get("aois") or []
    if not aois:
        return _feedback(
            await t("show_imagery.no_aoi", language),
            tool_call_id,
        )

    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            return _feedback(
                await t(
                    "show_imagery.invalid_date",
                    language,
                    target_date=target_date,
                ),
                tool_call_id,
            )

    aoi_names = [a["name"] for a in aois]
    logger.info(
        f"SHOW-IMAGERY-TOOL: AOI: {aoi_names}, Target date: {target_date}"
    )

    if provider != "sentinel-2" and _planet_covers(aois):
        try:
            mosaic = _planet_mosaic(await _fetch_planet_mosaics(), parsed_date)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            logger.warning("Planet mosaic lookup failed", exc_info=True)
            mosaic = None
        if mosaic is not None:
            mosaic_name = mosaic["name"]
            imagery_state = ImageryState(
                provider="planet",
                tile_url=(
                    f"{PLANET_BASE_URL}/wmts/v1/{mosaic_name}"
                    "/{z}/{x}/{y}.png"
                ),
                mosaic_id=mosaic_name,
                date_start=mosaic["first_acquired"][:10],
                date_end=mosaic["last_acquired"][:10],
                target_date=parsed_date.isoformat() if parsed_date else None,
                aoi_names=aoi_names,
            )
            return Command(
                update={
                    "imagery": imagery_state.model_dump(),
                    "messages": [
                        ToolMessage(
                            "Limited-coverage Planet imagery is shown on the "
                            "map. Sentinel-2 imagery is also available if "
                            "you'd like to compare it.",
                            tool_call_id=tool_call_id,
                        )
                    ],
                }
            )
        if provider == "planet":
            return _feedback(
                "Planet imagery is not available for this area and month. "
                "Sentinel-2 imagery is available instead.",
                tool_call_id,
            )

    if provider == "planet":
        return _feedback(
            "Planet imagery is not available for this area and month. "
            "Sentinel-2 imagery is available instead.",
            tool_call_id,
        )

    aoi_refs = tuple((a["source"], a["src_id"]) for a in aois)
    user_id = None
    if any(source == "custom" for source, _ in aoi_refs):
        user_id = current_user_id()

    recipe = MosaicRecipe(
        aois=aoi_refs,
        target_date=parsed_date or date.today(),
        window_days=max(1, min(window_days, 183))
        if window_days is not None
        else 7,
        max_cloud_cover=max(1, min(max_cloud_cover, 100))
        if max_cloud_cover is not None
        else 20,
        user_id=user_id,
    )

    try:
        result: MosaicResult = await create_sentinel2_mosaic(recipe)
    except MosaicNotFoundError:
        return _feedback(
            await t("show_imagery.geometry_error", language), tool_call_id
        )
    except AoiTooLargeError as e:
        return _feedback(
            await t("show_imagery.aoi_too_large", language, error=str(e)),
            tool_call_id,
        )
    except NoScenesFoundError:
        return _feedback(
            await t(
                "show_imagery.no_scenes_found",
                language,
                cloud_cover=recipe.max_cloud_cover,
                window_days=recipe.window_days,
                target_date=recipe.target_date,
            ),
            tool_call_id,
        )
    except StacSearchError:
        return _feedback(
            await t("show_imagery.stac_unavailable", language),
            tool_call_id,
        )
    except Exception as e:
        # Anything else (e.g. S3 read/write failure, missing mosaic bucket
        # config, credentials) would otherwise propagate unlogged. Surface it
        # in the logs and hand the agent a graceful message.
        logger.exception(
            "show_imagery failed unexpectedly",
            error=str(e),
            aoi_names=aoi_names,
            target_date=recipe.target_date.isoformat(),
        )
        return _feedback(
            await t("show_imagery.unexpected_error", language),
            tool_call_id,
        )

    imagery_state = ImageryState(
        provider="sentinel-2",
        tile_url=result.tile_url,
        tilejson_url=result.tilejson_url,
        mosaic_id=result.mosaic_id,
        item_count=result.item_count,
        date_start=result.date_start.isoformat()
        if result.date_start
        else None,
        date_end=result.date_end.isoformat() if result.date_end else None,
        mean_cloud_cover=result.mean_cloud_cover,
        min_cloud_cover=result.min_cloud_cover,
        max_cloud_cover_observed=result.max_cloud_cover,
        target_date=recipe.target_date.isoformat(),
        window_days=recipe.window_days,
        max_cloud_cover=recipe.max_cloud_cover,
        aoi_names=aoi_names,
    )

    # item_count / dates are absent when the mosaic was served from cache.
    if result.item_count is not None:
        summary = await t(
            "show_imagery.success_summary",
            language,
            count=result.item_count,
            start=result.date_start,
            end=result.date_end,
        )
    else:
        summary = ""

    return Command(
        update={
            "imagery": imagery_state.model_dump(),
            "messages": [
                ToolMessage(
                    await t(
                        "show_imagery.success",
                        language,
                        aois=", ".join(aoi_names),
                        summary=summary,
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


SPEC = ToolSpec(
    tool=show_imagery,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- show_imagery(provider, target_date): show Planet imagery when "
        "available, otherwise Sentinel-2, for the AOI in state. provider is "
        "optional ('planet' or 'sentinel-2'). Run pick_aoi first."
    ),
)
