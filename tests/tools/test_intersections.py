"""Unit tests for dataset params (YAML config + pick_dataset validation).

Integration pulls per (dataset, params) live in tests/tools/test_pull_data.py
and use a hand-maintained matrix aligned with the analytics OpenAPI spec.
"""

import pytest

from src.agent.tools.datasets_config import DATASETS
from src.agent.tools.pick_dataset import DatasetOption

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _param_defs(dataset: dict) -> dict:
    config = dataset.get("analytics_config") or {}
    return config.get("params") or {}


def dataset_param_values_from_config() -> list[tuple[int, str, str]]:
    """Every (dataset_id, param_name, value) declared under ``params`` in dataset YAML."""
    cases: list[tuple[int, str, str]] = []
    for ds in DATASETS:
        for param_name, defn in _param_defs(ds).items():
            for val in defn.get("values", []):
                cases.append((ds["dataset_id"], param_name, val))
    return cases


def dataset_intersection_values_from_config() -> list[tuple[int, str]]:
    """Every (dataset_id, value) for intersections params — used by test_pull_data sync check."""
    cases: list[tuple[int, str]] = []
    for ds in DATASETS:
        params = _param_defs(ds)
        if "intersections" in params:
            for val in params["intersections"].get("values", []):
                cases.append((ds["dataset_id"], val))
    return cases


@pytest.mark.parametrize(
    "dataset_id,param_name,param_value",
    dataset_param_values_from_config(),
)
def test_yaml_param_accepted_by_dataset_option(
    dataset_id: int, param_name: str, param_value: str
):
    """Any value in params YAML must survive DatasetOption validation."""
    opt = DatasetOption(
        dataset_id=dataset_id,
        params={param_name: param_value},
        reason="test",
        language="en",
    )
    assert param_name in opt.params
    param_def = _param_defs(
        next(ds for ds in DATASETS if ds["dataset_id"] == dataset_id)
    )[param_name]
    is_list = param_def.get("type") == "list"
    if is_list:
        assert param_value in opt.params[param_name]
    else:
        assert opt.params[param_name] == param_value


def _datasets_with_default_intersections():
    """Dataset IDs where intersections param has a non-empty default."""
    result = []
    for ds in DATASETS:
        params = _param_defs(ds)
        inter = params.get("intersections")
        if inter and inter.get("default"):
            result.append(ds["dataset_id"])
    return result


@pytest.mark.parametrize(
    "dataset_id",
    _datasets_with_default_intersections(),
)
def test_default_intersections_applied_when_llm_omits(dataset_id: int):
    params_def = _param_defs(
        next(ds for ds in DATASETS if ds["dataset_id"] == dataset_id)
    )
    expected_default = params_def["intersections"]["default"]
    opt = DatasetOption(
        dataset_id=dataset_id,
        params={},
        reason="test",
        language="en",
    )
    assert opt.params.get("intersections") == expected_default


def test_params_config_has_valid_entries():
    """Datasets with ``analytics_config.params`` should have valid value lists."""
    for ds in DATASETS:
        for param_name, defn in _param_defs(ds).items():
            values = defn.get("values")
            assert values, (
                f"{ds.get('dataset_name')} (id={ds.get('dataset_id')}) has "
                f"param '{param_name}' with no values list"
            )


def test_pull_data_matrix_covers_all_config_intersections():
    """Keep tests/tools/test_pull_data.py ALL_DATASET_COMBINATIONS in sync with YAML.

    When you add intersections in dataset YAML, extend ALL_DATASET_COMBINATIONS
    (or switch that module to build cases from DATASETS) so live API pulls stay covered.
    """
    from tests.tools.test_pull_data import ALL_DATASET_COMBINATIONS

    config_pairs = set(dataset_intersection_values_from_config())
    pull_pairs = {
        (c["dataset_id"], c["intersection"])
        for c in ALL_DATASET_COMBINATIONS
        if c.get("intersection") is not None
    }
    missing = config_pairs - pull_pairs
    assert not missing, (
        "ALL_DATASET_COMBINATIONS is missing pull tests for YAML intersections: "
        f"{sorted(missing)}"
    )
