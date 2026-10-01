"""Suggest GNW profile fields from the person's MyGFW profile.

GFW and GNW share the Resource Watch user. MyGFW keeps its profile on that
user under ``applicationData.gfw``. The suggestion is best-effort: MyGFW
profiles are often thin, and a value with no GNW equivalent is left out, not
treated as an error. Nothing here writes to the GNW user.
"""

import re
from collections.abc import Container, Mapping
from typing import Any, Optional, cast
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
_COUNTRY_BY_KEY = {_fold(k): v for k, v in GADM_ISO3_TO_COUNTRY_CODE.items()}
_LANGUAGE_BY_KEY = {code: code for code in LANGUAGES}

# GFW values that are enumerations, by suggestion key. Only these are ever
# logged when they fail to map; free text never is.
_ENUMERATED_SOURCES = (
    ("sector_code", "sector"),
    ("role_code", "subsector"),
    ("country_code", "country"),
    ("preferred_language_code", "preferred_language"),
)


def _text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _is_other(text: str) -> bool:
    return _fold(text).startswith(_OTHER)


def _coded(
    value: Any, table: Mapping[str, str], valid: Container[str]
) -> Optional[str]:
    """The GNW code for a GFW value, or None when it has no valid one.

    A write-in "Other..." becomes "other", which only survives where "other"
    is a valid code (sectors and roles).
    """
    text = _text(value)
    if text is None:
        return None
    code = _OTHER if _is_other(text) else table.get(_fold(text))
    return code if code in valid else None


def _language_code(value: Any) -> Optional[str]:
    # GNW stores the primary subtag only, so "pt-BR" suggests "pt".
    primary = (
        re.split(r"[-_]", value, maxsplit=1)[0]
        if isinstance(value, str)
        else None
    )
    return _coded(primary, _LANGUAGE_BY_KEY, LANGUAGES)


def _topics(*values: Any) -> list[str]:
    topics: list[str] = []
    for value in values:
        items = [value] if isinstance(value, str) else value
        if not isinstance(items, list):
            continue
        for item in items:
            code = _coded(item, _TOPIC_BY_KEY, TOPICS)
            if code is not None and code not in topics:
                topics.append(code)
    return topics


def map_gfw_profile(attributes: dict[str, Any]) -> ProfilePrefillSuggestion:
    """Map RW user attributes to a partial ``PATCH /api/auth/profile`` body.

    ``attributes`` is ``data.attributes`` of ``GET /v2/user/{id}``. Keys
    appear only for fields that mapped to a valid GNW value. GFW's opt-in
    flags (receive_updates, signUpForNewsletter, signUpForTesting) are never
    carried over: a suggestion the person confirms in one click must not
    pre-tick consent.
    """
    application_data = attributes.get("applicationData")
    gfw = (
        application_data.get("gfw")
        if isinstance(application_data, dict)
        else None
    )
    if not isinstance(gfw, dict):
        gfw = {}

    sector_code = _coded(gfw.get("sector"), _SECTOR_BY_KEY, SECTORS)
    # PATCH /api/auth/profile validates a role against the sector in the
    # same body, so a role is only worth suggesting alongside its sector.
    role_code = (
        _coded(gfw.get("subsector"), _ROLE_BY_KEY, SECTOR_ROLES[sector_code])
        if sector_code
        else None
    )
    candidates = {
        "first_name": _text(attributes.get("firstName")),
        "last_name": _text(attributes.get("lastName")),
        "job_title": _text(gfw.get("jobTitle")),
        "company_organization": _text(gfw.get("company")),
        "sector_code": sector_code,
        "role_code": role_code,
        "country_code": _coded(gfw.get("country"), _COUNTRY_BY_KEY, COUNTRIES),
        "preferred_language_code": _language_code(
            gfw.get("preferred_language")
        ),
        "topics": _topics(gfw.get("interests"), gfw.get("topics")) or None,
    }
    suggestion = cast(
        ProfilePrefillSuggestion,
        {k: v for k, v in candidates.items() if v is not None},
    )

    # Name the enumerated GFW values that did not map, so the tables can be
    # extended. "Other: <text>" is a write-in, so it is never logged.
    unmapped: dict[str, str] = {}
    for field, source in _ENUMERATED_SOURCES:
        text = _text(gfw.get(source))
        if field not in suggestion and text and not _is_other(text):
            unmapped[field] = text
    logger.info(
        "Mapped MyGFW profile to a GNW suggestion",
        mapped_fields=sorted(suggestion),
        unmapped_values=unmapped,
    )
    return suggestion


async def fetch_gfw_attributes(user_id: str, token: str) -> dict[str, Any]:
    """Read the caller's RW user attributes, where MyGFW keeps its profile.

    Returns ``{}`` when there is no profile to read: RW answers 404 (the
    MyGFW form was never saved) or the body has no ``data.attributes``.
    Raises ``ResourceWatchUnavailableError`` when RW cannot be reached or
    answers anything but 200/404.
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
        logger.info("No MyGFW profile for this user")
        return {}
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

    suggestion = map_gfw_profile(await fetch_gfw_attributes(user.id, token))
    if not suggestion:
        return not_found
    return ProfilePrefillResponse(
        found=True,
        source="gfw",
        suggestion=suggestion,
    )
