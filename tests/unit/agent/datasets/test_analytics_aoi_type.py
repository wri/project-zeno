"""The analytics API has no concession type: every concession subtype must
be sent as a feature collection, like a custom area."""

import pytest

from src.agent.datasets.handlers.analytics_handler import (
    ANALYTICS_AOI_SUBTYPES,
    AnalyticsHandler,
)
from src.shared.geocoding_helpers import (
    CONCESSION_SOURCES,
    SUBREGION_TO_SUBTYPE_MAPPING,
)


@pytest.mark.parametrize("source", CONCESSION_SOURCES)
def test_concessions_are_sent_as_a_feature_collection(source):
    aoi = {"subtype": SUBREGION_TO_SUBTYPE_MAPPING[source], "source": source}
    assert AnalyticsHandler()._get_aoi_type(aoi) == {
        "type": "feature_collection"
    }


def test_unknown_subtype_still_raises():
    with pytest.raises(ValueError, match="Unknown AOI subtype"):
        AnalyticsHandler()._get_aoi_type({"subtype": "palm-plantation"})


@pytest.mark.parametrize("subtype", ANALYTICS_AOI_SUBTYPES)
def test_every_analytics_subtype_has_an_aoi_type(subtype):
    assert AnalyticsHandler()._get_aoi_type({"subtype": subtype})["type"]


@pytest.mark.parametrize(
    "subtype, aoi_type",
    [
        ("key-biodiversity-area", "key_biodiversity_area"),
        ("indigenous-and-community-land", "indigenous_land"),
        ("protected-area", "protected_area"),
    ],
)
def test_named_area_types(subtype, aoi_type):
    assert AnalyticsHandler()._get_aoi_type({"subtype": subtype}) == {
        "type": aoi_type
    }


@pytest.mark.parametrize(
    "subtype", ["municipality", "locality", "neighbourhood"]
)
def test_admin_levels_below_2_are_not_analytics_subtypes(subtype):
    assert subtype not in ANALYTICS_AOI_SUBTYPES
