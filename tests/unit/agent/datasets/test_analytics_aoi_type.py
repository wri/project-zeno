"""The analytics API has no concession type: every concession subtype must
be sent as a feature collection, like a custom area."""

import pytest

from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler
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
