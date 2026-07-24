import pytest

from src.agent.datasets.config import DATASETS
from src.api.services.charts import (
    DATASETS_WITHOUT_CURATED_INSIGHTS,
    GENERATORS,
    register,
)
from src.api.services.charts.integrated_alerts import (
    IntegratedAlertsChartGenerator,
)
from src.api.services.charts.tree_cover_loss import TCLChartGenerator

CATALOG_IDS = {ds["dataset_id"] for ds in DATASETS}


def test_every_catalog_dataset_is_registered_or_explicitly_excluded():
    """Coverage ratchet: a new catalog YAML must ship a curated generator or
    be added to the exclusion set deliberately."""
    covered = set(GENERATORS) | DATASETS_WITHOUT_CURATED_INSIGHTS
    assert covered == CATALOG_IDS, (
        f"Catalog datasets missing from registry and exclusion set: "
        f"{CATALOG_IDS - covered}; "
        f"stale entries not in the catalog: {covered - CATALOG_IDS}"
    )


def test_registered_and_excluded_sets_are_disjoint():
    overlap = set(GENERATORS) & DATASETS_WITHOUT_CURATED_INSIGHTS
    assert (
        not overlap
    ), f"Datasets with a generator must leave the exclusion set: {overlap}"


def test_register_rejects_duplicate_dataset_id():
    existing_id = next(iter(GENERATORS))
    with pytest.raises(ValueError, match="Duplicate chart generator"):
        register(existing_id, TCLChartGenerator())


def test_tcl_generator_registered():
    assert any(
        isinstance(gen, TCLChartGenerator) for gen in GENERATORS.values()
    )


def test_integrated_alerts_generator_registered():
    assert any(
        isinstance(gen, IntegratedAlertsChartGenerator)
        for gen in GENERATORS.values()
    )
