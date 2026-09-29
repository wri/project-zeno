from datetime import date

import pytest
from pydantic import ValidationError

from tests.unit.agent.imagery.factories import scene_summary


def test_scene_summary_keeps_the_number_of_scenes_it_summarizes():
    assert scene_summary(item_count=12).item_count == 12


def test_scene_summary_rejects_fields_it_does_not_define():
    with pytest.raises(
        ValidationError, match="Extra inputs are not permitted"
    ):
        scene_summary(max_cloud_cover_observed=14.8)


def test_scene_summary_keeps_the_dates_its_scenes_were_captured():
    summary = scene_summary(start_date="2026-08-09", end_date="2026-08-20")

    assert (summary.start_date, summary.end_date) == (
        date(2026, 8, 9),
        date(2026, 8, 20),
    )


def test_scene_summary_keeps_the_cloud_cover_across_its_scenes():
    summary = scene_summary(
        mean_cloud_cover=7.35, min_cloud_cover=2.1, max_cloud_cover=14.8
    )

    assert (
        summary.mean_cloud_cover,
        summary.min_cloud_cover,
        summary.max_cloud_cover,
    ) == (7.35, 2.1, 14.8)
