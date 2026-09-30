"""Suggest GNW profile fields from the person's MyGFW profile.

GFW and GNW share the Resource Watch user. MyGFW keeps its profile on that
user under ``applicationData.gfw``. The suggestion is best-effort: MyGFW
profiles are often thin, and a value with no GNW equivalent is left out, not
treated as an error. Nothing here writes to the GNW user.
"""

import re
from typing import Any, Optional
from urllib.parse import quote

import httpx

from src.api.auth.machine_user import MACHINE_USER_PREFIX
from src.api.data_models import UserType
from src.api.schemas import (
    ProfilePrefillResponse,
    ProfilePrefillSuggestion,
    UserModel,
)
from src.api.user_profile_configs.countries import COUNTRIES
from src.api.user_profile_configs.gfw import (
    GADM_ISO3_TO_COUNTRY_CODE,
    GFW_INTERESTS,
    GFW_SECTORS,
    GFW_SUBSECTORS,
)
from src.api.user_profile_configs.languages import LANGUAGES
from src.api.user_profile_configs.sectors import SECTOR_ROLES, SECTORS
from src.api.user_profile_configs.topics import TOPICS
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

RW_API_URL = "https://api.resourcewatch.org"
RW_TIMEOUT_SECONDS = 10

# GFW writes "Other" or "Other: <free text>" for a write-in sector or role.
_OTHER = "other"


class ResourceWatchUnavailableError(Exception):
    """Resource Watch could not be reached or answered unexpectedly."""


def _fold(value: str) -> str:
    """Fold a GFW label or stored slug into one lookup key.

    GFW saves option labels as ``label.replace(/( )+|(\\/)+/g, "_")``, and
    lower-cases some of them since 2025, so "Forest Management/Park
    Management", "Forest_Management_Park_Management" and
    "forest_management_park_management" must all meet.
    """
    return re.sub(r"[\s/_]+", "_", value.strip().lower()).strip("_")


_SECTOR_BY_KEY = {_fold(k): v for k, v in GFW_SECTORS.items()}
_ROLE_BY_KEY = {_fold(k): v for k, v in GFW_SUBSECTORS.items()}
_TOPIC_BY_KEY = {_fold(k): v for k, v in GFW_INTERESTS.items()}


def _text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _sector_code(value: Any) -> Optional[str]:
    text = _text(value)
    if text is None:
        return None
    key = _fold(text)
    code = _OTHER if key.startswith(_OTHER) else _SECTOR_BY_KEY.get(key)
    return code if code in SECTORS else None


def _role_code(value: Any, sector_code: Optional[str]) -> Optional[str]:
    # PATCH /api/auth/profile validates a role against the sector in the
    # same body, so a role is only worth suggesting alongside its sector.
    text = _text(value)
    if text is None or sector_code is None:
        return None
    key = _fold(text)
    code = _OTHER if key.startswith(_OTHER) else _ROLE_BY_KEY.get(key)
    return code if code in SECTOR_ROLES.get(sector_code, {}) else None


def _country_code(value: Any) -> Optional[str]:
    text = _text(value)
    if text is None:
        return None
    code = GADM_ISO3_TO_COUNTRY_CODE.get(text.upper())
    return code if code in COUNTRIES else None


def _language_code(value: Any) -> Optional[str]:
    text = _text(value)
    if text is None:
        return None
    code = re.split(r"[-_]", text.lower(), maxsplit=1)[0]
    return code if code in LANGUAGES else None


def _topics(*values: Any) -> list[str]:
    topics: list[str] = []
    for value in values:
        items = [value] if isinstance(value, str) else value
        if not isinstance(items, list):
            continue
        for item in items:
            text = _text(item)
            code = _TOPIC_BY_KEY.get(_fold(text)) if text else None
            if code is not None and code in TOPICS and code not in topics:
                topics.append(code)
    return topics


def map_gfw_profile(attributes: Any) -> dict[str, Any]:
    """Map RW user attributes to a partial ``PATCH /api/auth/profile`` body.

    ``attributes`` is ``data.attributes`` of ``GET /v2/user/{id}``. Keys
    appear only for fields that mapped to a valid GNW value. GFW's opt-in
    flags (receive_updates, signUpForNewsletter, signUpForTesting) are never
    carried over: a suggestion the person confirms in one click must not
    pre-tick consent.
    """
    attrs = attributes if isinstance(attributes, dict) else {}
    application_data = attrs.get("applicationData")
    gfw = (
        application_data.get("gfw")
        if isinstance(application_data, dict)
        else None
    )
    if not isinstance(gfw, dict):
        gfw = {}

    sector_code = _sector_code(gfw.get("sector"))
    candidates = {
        "first_name": _text(attrs.get("firstName")),
        "last_name": _text(attrs.get("lastName")),
        "job_title": _text(gfw.get("jobTitle")),
        "company_organization": _text(gfw.get("company")),
        "sector_code": sector_code,
        "role_code": _role_code(gfw.get("subsector"), sector_code),
        "country_code": _country_code(gfw.get("country")),
        "preferred_language_code": _language_code(
            gfw.get("preferred_language")
        ),
        "topics": _topics(gfw.get("interests"), gfw.get("topics")) or None,
    }
    suggestion = {k: v for k, v in candidates.items() if v is not None}

    # Name the enumerated GFW values that did not map, so the tables can be
    # extended. Free-text fields are never logged.
    unmapped = {
        field: gfw[source]
        for field, source in (
            ("sector_code", "sector"),
            ("role_code", "subsector"),
            ("country_code", "country"),
            ("preferred_language_code", "preferred_language"),
        )
        if field not in suggestion
        and isinstance(gfw.get(source), str)
        and gfw[source].strip()
        and not gfw[source].strip().lower().startswith(_OTHER)
    }
    logger.info(
        "Mapped MyGFW profile to a GNW suggestion",
        mapped_fields=sorted(suggestion),
        unmapped_values=unmapped,
    )
    return suggestion


async def fetch_gfw_attributes(
    user_id: str, token: str
) -> Optional[dict[str, Any]]:
    """Read the caller's RW user attributes, where MyGFW keeps its profile.

    Returns ``None`` when RW has no profile for the user (404: the MyGFW
    form was never saved). Raises ``ResourceWatchUnavailableError`` when RW
    cannot be reached or answers anything but 200/404.
    """
    url = f"{RW_API_URL}/v2/user/{quote(user_id, safe='')}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=RW_TIMEOUT_SECONDS,
            )
    except httpx.HTTPError as e:
        logger.warning(
            "Could not reach Resource Watch for the MyGFW profile",
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise ResourceWatchUnavailableError(
            f"Could not reach Resource Watch: {type(e).__name__}"
        ) from e

    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        # A 401/403 lands here too: the token passed require_auth, possibly
        # from the one-day identity cache, but RW refused it.
        logger.warning(
            "Resource Watch refused the MyGFW profile request",
            status_code=resp.status_code,
        )
        raise ResourceWatchUnavailableError(
            f"Resource Watch answered {resp.status_code}"
        )

    try:
        body = resp.json()
    except ValueError as e:
        logger.warning(
            "Resource Watch returned a non-JSON MyGFW profile",
            exc_info=True,
        )
        raise ResourceWatchUnavailableError(
            "Resource Watch returned a non-JSON body"
        ) from e

    # The JSON:API shape is inferred from the gfw frontend, not observed
    # live. If it differs, say so loudly in the logs but degrade to "no
    # profile", since prefill is best-effort.
    data = body.get("data") if isinstance(body, dict) else None
    attributes = data.get("attributes") if isinstance(data, dict) else None
    if not isinstance(attributes, dict):
        logger.warning(
            "Resource Watch user response has no data.attributes",
            top_level_keys=(
                sorted(body) if isinstance(body, dict) else type(body).__name__
            ),
        )
        return {}
    return attributes


async def get_profile_prefill(
    user: UserModel, token: str
) -> ProfilePrefillResponse:
    """Suggest profile fields for ``user`` from their MyGFW profile."""
    not_found = ProfilePrefillResponse(found=False)

    # A machine key is ours and must never be sent to a third party, and a
    # machine user has no MyGFW profile anyway.
    if (
        token.startswith(f"{MACHINE_USER_PREFIX}:")
        or user.user_type == UserType.MACHINE
    ):
        return not_found

    attributes = await fetch_gfw_attributes(user.id, token)
    if attributes is None:
        logger.info("No MyGFW profile for this user")
        return not_found

    suggestion = map_gfw_profile(attributes)
    if not suggestion:
        return not_found
    return ProfilePrefillResponse(
        found=True,
        source="gfw",
        suggestion=ProfilePrefillSuggestion(**suggestion),
    )
