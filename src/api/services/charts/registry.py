"""Dataset-id → curated chart generator mapping.

`DATASETS_WITHOUT_CURATED_INSIGHTS` is a coverage ratchet: every dataset in
the catalog must either have a registered generator or appear in that set,
and a unit test enforces the partition — so adding a catalog YAML without a
curated generator fails loudly. The set shrinks as generators land; the end
state is empty.
"""

from src.agent.datasets.handlers.analytics_handler import (
    DIST_ALERT_ID,
    FOREST_CARBON_FLUX_ID,
    GRASSLANDS_ID,
    INTEGRATED_ALERTS_ID,
    LAND_COVER_CHANGE_ID,
    NATURAL_LANDS_ID,
    SLUC_EMISSION_FACTORS_ID,
    TREE_COVER_GAIN_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
    TREE_COVER_LOSS_ID,
)
from src.api.services.charts.base import ChartGenerator
from src.api.services.charts.grasslands import GrasslandsChartGenerator
from src.api.services.charts.integrated_alerts import (
    IntegratedAlertsChartGenerator,
)
from src.api.services.charts.tcl_fires import TCLFiresChartGenerator
from src.api.services.charts.tree_cover_gain import (
    TreeCoverGainChartGenerator,
)
from src.api.services.charts.tree_cover_loss import TCLChartGenerator

GENERATORS: dict[int, ChartGenerator] = {}

DATASETS_WITHOUT_CURATED_INSIGHTS: set[int] = {
    DIST_ALERT_ID,
    LAND_COVER_CHANGE_ID,
    NATURAL_LANDS_ID,
    FOREST_CARBON_FLUX_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    SLUC_EMISSION_FACTORS_ID,
}


def register(dataset_id: int, generator: ChartGenerator) -> None:
    if dataset_id in GENERATORS:
        raise ValueError(f"Duplicate chart generator for dataset {dataset_id}")
    GENERATORS[dataset_id] = generator


register(TREE_COVER_LOSS_ID, TCLChartGenerator())
register(INTEGRATED_ALERTS_ID, IntegratedAlertsChartGenerator())
register(GRASSLANDS_ID, GrasslandsChartGenerator())
register(TREE_COVER_GAIN_ID, TreeCoverGainChartGenerator())
register(TREE_COVER_LOSS_BY_FIRES_ID, TCLFiresChartGenerator())
