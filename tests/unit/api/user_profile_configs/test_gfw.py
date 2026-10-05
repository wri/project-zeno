"""Every MyGFW translation table must point at real GNW profile codes."""

import re

import pytest

from src.api.user_profile_configs.countries import COUNTRIES
from src.api.user_profile_configs.gfw import (
    GADM_ISO3_TO_COUNTRY_CODE,
    GFW_INTERESTS,
    GFW_SECTORS,
    GFW_SUBSECTORS,
)
from src.api.user_profile_configs.sectors import SECTOR_ROLES, SECTORS
from src.api.user_profile_configs.topics import TOPICS


def test_gfw_sectors_cover_every_named_gnw_sector():
    # "other" is matched by prefix in the mapper, not by the table.
    assert set(GFW_SECTORS.values()) == set(SECTORS) - {"other"}


def test_gfw_subsectors_map_to_roles_gnw_offers():
    all_roles = {role for roles in SECTOR_ROLES.values() for role in roles}
    assert set(GFW_SUBSECTORS.values()) <= all_roles


def test_gfw_interests_map_to_gnw_topics():
    assert set(GFW_INTERESTS.values()) <= set(TOPICS)


def test_country_table_targets_gnw_country_codes():
    assert set(GADM_ISO3_TO_COUNTRY_CODE.values()) <= set(COUNTRIES)


def test_country_table_reaches_every_gnw_country():
    assert set(GADM_ISO3_TO_COUNTRY_CODE.values()) == set(COUNTRIES) - {
        "OTHER"
    }


def test_country_table_keys_are_iso3_shaped_and_values_unique():
    assert all(re.fullmatch(r"[A-Z]{3}", k) for k in GADM_ISO3_TO_COUNTRY_CODE)
    values = list(GADM_ISO3_TO_COUNTRY_CODE.values())
    assert len(values) == len(set(values))


@pytest.mark.parametrize(
    "iso3, alpha2",
    [("BRA", "BR"), ("IDN", "ID"), ("COD", "CD"), ("XKO", "XK")],
)
def test_known_countries_translate(iso3, alpha2):
    assert GADM_ISO3_TO_COUNTRY_CODE[iso3] == alpha2


@pytest.mark.parametrize("gadm_only", ["XCA", "XAD", "ZNC", "Z01", "Z09"])
def test_gadm_only_codes_are_not_translated(gadm_only):
    assert gadm_only not in GADM_ISO3_TO_COUNTRY_CODE
