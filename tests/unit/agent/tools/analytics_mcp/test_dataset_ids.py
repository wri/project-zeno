import pytest

from src.agent.tools.analytics_mcp.dataset_ids import (
    DatasetIds,
    UnknownDatasetError,
)

CATALOG = [
    {
        "dataset_id": 1,
        "analytics_api_endpoint": "/v0/land_change/land_cover_change/analytics",
    },
    {
        "dataset_id": 4,
        "analytics_api_endpoint": "/v0/land_change/tree_cover_loss/analytics",
    },
    {
        "dataset_id": 8,
        "analytics_api_endpoint": "/v0/land_change/tree_cover_loss/analytics",
    },
    {
        "dataset_id": 10,
        "analytics_api_endpoint": "/v0/land_change/tree_cover_loss/analytics",
    },
]


@pytest.fixture
def dataset_ids() -> DatasetIds:
    return DatasetIds(
        catalog=CATALOG,
        intersection_ids={
            ("tree_cover_loss", "driver"): 8,
            ("tree_cover_loss", "fire"): 10,
        },
        alias_ids={"land_cover_composition": 1},
    )


def test_dataset_without_intersection_is_the_plain_dataset(dataset_ids):
    assert dataset_ids.dataset_id_for("tree_cover_loss", None) == 4


@pytest.mark.parametrize(
    ("intersection", "expected"), [("driver", 8), ("fire", 10)]
)
def test_intersection_selects_its_own_dataset(
    dataset_ids, intersection, expected
):
    assert (
        dataset_ids.dataset_id_for("tree_cover_loss", [intersection])
        == expected
    )


def test_alias_maps_to_the_catalog_dataset(dataset_ids):
    assert dataset_ids.dataset_id_for("land_cover_composition", None) == 1


def test_unknown_dataset_is_rejected(dataset_ids):
    with pytest.raises(UnknownDatasetError):
        dataset_ids.dataset_id_for("carbon_flux", None)
