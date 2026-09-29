import pytest
from pydantic import ValidationError

from src.shared.imagery.sentinel2 import SceneSummary


def test_scene_summary_keeps_the_number_of_scenes_it_summarizes():
    assert SceneSummary(item_count=9).item_count == 9


def test_scene_summary_rejects_fields_it_does_not_define():
    with pytest.raises(
        ValidationError, match="Extra inputs are not permitted"
    ):
        SceneSummary(item_count=9, max_cloud_cover_observed=14.8)
