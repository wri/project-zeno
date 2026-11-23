"""One writer for the `statistics` row of a pull."""

from unittest.mock import MagicMock

from src.api.repositories.statistics_writer import (
    PulledStatistics,
    add_statistics_row,
)

AREAS = [
    {"name": "Brazil", "source": "gadm", "src_id": "BRA"},
    {"name": "Para", "source": "gadm", "src_id": "BRA.14_1"},
]


def test_the_row_keeps_the_areas_as_parallel_lists_and_the_canopy_cover():
    session = MagicMock()

    row = add_statistics_row(
        session,
        PulledStatistics(
            dataset_id=4,
            dataset_name="Tree cover loss",
            start_date="2001-01-01",
            end_date="2024-12-31",
            source_url="https://analytics.example.com/result/1",
            areas=AREAS,
            parameters=None,
            context_layer="natural_forest",
            canopy_cover=10,
        ),
        user_id="user-1",
        thread_id="thread-1",
    )

    session.add.assert_called_once_with(row)
    assert row.aoi_names == ["Brazil", "Para"]
    assert row.aoi_ids == ["BRA", "BRA.14_1"]
    assert row.aoi_sources == ["gadm", "gadm"]
    assert row.parameters is None
    assert row.canopy_cover == 10
    assert row.context_layer == "natural_forest"
