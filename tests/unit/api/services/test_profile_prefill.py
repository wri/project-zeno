"""Unit tests for mapping a MyGFW profile to a GNW profile suggestion.

The fixtures follow what the gfw repo's profile form saves on the Resource
Watch user (``data.attributes`` of ``GET /v2/user/{id}``): see gfw
components/forms/profile/actions.js and config.js, and the pre-2025 config
at gfw commit 722e3ae6e8^. The real response has not been observed live yet.
"""

import pytest

from src.api.schemas import UserProfileUpdateRequest
from src.api.services.profile_prefill import map_gfw_profile

# Saved by the current GFW form: no subsector (the role radio is dead),
# lower-cased interest slugs, a real boolean receive_updates, the 'true'
# string quirk for signUpForTesting.
CURRENT_PROFILE = {
    "firstName": "Ana",
    "lastName": "Silva",
    "email": "ana@example.org",
    "applicationData": {
        "gfw": {
            "country": "BRA",
            "city": "Belém",
            "state": "Pará",
            "sector": "Local NGO (national or subnational)",
            "company": "Instituto Floresta",
            "jobTitle": "GIS analyst",
            "interests": ["deforestation", "fires", "biodiversity"],
            "aoiCountry": "BRA",
            "areaOrRegionOfInterest": "",
            "receive_updates": True,
            "preferred_language": "pt",
            "howDoYouUse": ["Monitor or manage an area", "Other: teaching"],
            "signUpForNewsletter": False,
            "signUpForTesting": "true",
        }
    },
}

# Saved before 2025: a subsector slug, capitalised interest slugs with the
# old wording, legacy newsletter topics, fullName instead of first/last.
LEGACY_PROFILE = {
    "fullName": "Jean Dupont",
    "email": "jean@example.org",
    "applicationData": {
        "gfw": {
            "sector": "Government",
            "subsector": "Forest_Management_Park_Management",
            "company": "Ministère de l'Environnement",
            "country": "COD",
            "interests": [
                "Deforestation_Forest_Degradation",
                "Reforestation_Landscape_restoration",
                "Watersheds_",
            ],
            "topics": [
                "Agricultural Supply Chains",
                "Climate and Biodiversity",
            ],
            "signUpForNewsletter": "true",
            "signUpForTesting": False,
        }
    },
}

# GFW only requires email, last name and sector.
THIN_PROFILE = {
    "lastName": "Okafor",
    "applicationData": {"gfw": {"sector": "Individual / No Affiliation"}},
}


def _gfw(**fields):
    return {"applicationData": {"gfw": fields}}


def test_current_profile_maps_every_portable_field():
    assert map_gfw_profile(CURRENT_PROFILE) == {
        "first_name": "Ana",
        "last_name": "Silva",
        "job_title": "GIS analyst",
        "company_organization": "Instituto Floresta",
        "sector_code": "local_ngo",
        "country_code": "BR",
        "preferred_language_code": "pt",
        "topics": ["combating_deforestation", "protecting_ecosystems"],
    }


def test_legacy_profile_maps_role_and_old_interest_wording():
    assert map_gfw_profile(LEGACY_PROFILE) == {
        "company_organization": "Ministère de l'Environnement",
        "sector_code": "government",
        "role_code": "forest_management",
        "country_code": "CD",
        "topics": [
            "combating_deforestation",
            "restoring_degraded_landscapes",
            "responsible_supply_chains",
        ],
    }


def test_thin_profile_maps_what_it_has():
    assert map_gfw_profile(THIN_PROFILE) == {
        "last_name": "Okafor",
        "sector_code": "individual",
    }


@pytest.mark.parametrize(
    "attributes",
    [
        None,
        {},
        [],
        "not-a-profile",
        {"applicationData": None},
        {"applicationData": "x"},
        {"applicationData": {"gfw": None}},
        {"applicationData": {"gfw": ["x"]}},
        {"applicationData": {"gfw": {}}},
        {"applicationData": {"rw": {"sector": "Government"}}},
    ],
)
def test_missing_or_malformed_profile_maps_to_nothing(attributes):
    assert map_gfw_profile(attributes) == {}


def test_values_of_the_wrong_type_are_skipped():
    attributes = {
        "firstName": 42,
        "lastName": ["Silva"],
        "applicationData": {
            "gfw": {
                "sector": ["Government"],
                "subsector": 3,
                "country": 76,
                "preferred_language": None,
                "company": {"name": "x"},
                "interests": [None, 7, "deforestation"],
            }
        },
    }

    assert map_gfw_profile(attributes) == {
        "topics": ["combating_deforestation"]
    }


def test_a_single_interest_string_is_accepted():
    assert map_gfw_profile(_gfw(interests="Biodiversity")) == {
        "topics": ["protecting_ecosystems"]
    }


def test_opt_in_flags_are_never_suggested():
    # A one-click "looks right" must not carry pre-ticked consent (GDPR), so
    # GFW's opt-ins are dropped whatever their value or quirk.
    attributes = _gfw(
        receive_updates=True,
        signUpForNewsletter="true",
        signUpForTesting="true",
    )

    assert map_gfw_profile(attributes) == {}


def test_text_fields_are_trimmed_and_blank_ones_dropped():
    attributes = {
        "firstName": "  Ana ",
        "lastName": "   ",
        "applicationData": {"gfw": {"jobTitle": "", "company": " WRI "}},
    }

    assert map_gfw_profile(attributes) == {
        "first_name": "Ana",
        "company_organization": "WRI",
    }


@pytest.mark.parametrize(
    "sector, expected",
    [
        ("Government", "government"),
        ("  international ngo ", "international_ngo"),
        ("Donor_Institution___Agency", "donor"),
        ("Other", "other"),
        ("Other: consultancy", "other"),
    ],
)
def test_sector_values_fold_case_spacing_and_other(sector, expected):
    assert map_gfw_profile(_gfw(sector=sector)) == {"sector_code": expected}


def test_unknown_sector_is_dropped_along_with_its_role():
    attributes = _gfw(sector="Space agency", subsector="Researcher")

    assert map_gfw_profile(attributes) == {}


def test_role_needs_a_mapped_sector():
    assert map_gfw_profile(_gfw(subsector="Director_Executive")) == {}


def test_role_not_offered_for_the_sector_is_dropped_but_sector_kept():
    # GNW academic roles do not include plain "researcher".
    attributes = _gfw(
        sector="Academic / Research Organization", subsector="Researcher"
    )

    assert map_gfw_profile(attributes) == {"sector_code": "academic"}


@pytest.mark.parametrize(
    "sector, subsector, role",
    [
        ("International NGO", "Director_Executive", "director_executive"),
        ("Donor Institution / Agency", "Field_Country_Staff", "field_staff"),
        (
            "Local NGO (national or subnational)",
            "Monitoring_Evaluation_Specialist",
            "monitoring_evaluation",
        ),
        (
            "Academic / Research Organization",
            "Researcher_(Post-Doc,_Fellow,_etc.)",
            "researcher_postdoc",
        ),
        ("Government", "Other: park ranger", "other"),
        ("Individual / No Affiliation", "Other:", "other"),
    ],
)
def test_legacy_role_slugs_map_within_their_sector(sector, subsector, role):
    suggestion = map_gfw_profile(_gfw(sector=sector, subsector=subsector))

    assert suggestion["role_code"] == role


def test_legacy_role_without_gnw_equivalent_is_dropped():
    attributes = _gfw(
        sector="Local NGO (national or subnational)",
        subsector="Park_Forest_Ranger",
    )

    assert map_gfw_profile(attributes) == {"sector_code": "local_ngo"}


@pytest.mark.parametrize(
    "country, expected",
    [("BRA", "BR"), (" idn ", "ID"), ("bra", "BR"), ("XKO", "XK")],
)
def test_gadm_iso3_country_converts_to_gnw_code(country, expected):
    assert map_gfw_profile(_gfw(country=country)) == {"country_code": expected}


@pytest.mark.parametrize("country", ["XCA", "Z01", "BR", "", "ZZZ"])
def test_country_without_gnw_code_is_dropped(country):
    assert map_gfw_profile(_gfw(country=country)) == {}


@pytest.mark.parametrize(
    "language, expected",
    [("en", "en"), ("EN", "en"), ("pt-BR", "pt"), ("id", "id")],
)
def test_preferred_language_maps_to_gnw_language(language, expected):
    assert map_gfw_profile(_gfw(preferred_language=language)) == {
        "preferred_language_code": expected
    }


def test_unsupported_language_is_dropped():
    assert map_gfw_profile(_gfw(preferred_language="de")) == {}


def test_topics_are_deduplicated_across_interests_and_legacy_topics():
    attributes = _gfw(
        interests=["deforestation", "Deforestation_Forest_Degradation"],
        topics=["Deforestation", "Agricultural Supply Chains"],
    )

    assert map_gfw_profile(attributes) == {
        "topics": ["combating_deforestation", "responsible_supply_chains"]
    }


def test_interests_without_gnw_topic_leave_topics_out():
    attributes = _gfw(
        interests=["fires", "climate_and_carbon"],
        topics=["Climate and Biodiversity"],
    )

    assert map_gfw_profile(attributes) == {}


@pytest.mark.parametrize(
    "attributes",
    [
        CURRENT_PROFILE,
        LEGACY_PROFILE,
        THIN_PROFILE,
        _gfw(sector="Government", subsector="Other: ranger"),
        _gfw(sector="Other", subsector="Other"),
    ],
    ids=["current", "legacy", "thin", "gov-other-role", "other-other"],
)
def test_suggestion_is_a_valid_profile_update_body(attributes):
    suggestion = map_gfw_profile(attributes)

    body = UserProfileUpdateRequest.model_validate(suggestion)

    assert body.model_dump(exclude_unset=True) == suggestion
