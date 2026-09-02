"""Deterministic chart generators — rule/config-driven builders that turn
pulled data into `InsightChart`s without calling an LLM.

`AnalyzeService` is injected with a sequence of these (`DETERMINISTIC_GENERATORS`)
and picks the first whose `can_handle(dataset_id)` matches; datasets with no
matching generator yield no charts. Each generator lives in its own module;
this package re-exports the public surface so existing
`from src.api.services.charts import ...` call sites are unaffected.
"""

from src.api.services.charts.base import ChartGenerator, column_to_rows
from src.api.services.charts.forest_flux import ForestFluxChartGenerator
from src.api.services.charts.grasslands import GrasslandsChartGenerator
from src.api.services.charts.integrated_alerts import (
    IntegratedAlertsChartGenerator,
)
from src.api.services.charts.land_cover import (
    LandCoverChangeChartGenerator,
)
from src.api.services.charts.lgms import (
    LGMS_CLASS_LABELS,
    LGMS_FULL_SERIES_CLASS_ORDER,
    LGMSChartGenerator,
)
from src.api.services.charts.natural_lands import NaturalLandsChartGenerator
from src.api.services.charts.registry import DETERMINISTIC_GENERATORS
from src.api.services.charts.sluc import SlucEmissionFactorsChartGenerator
from src.api.services.charts.tcl import TCLChartGenerator
from src.api.services.charts.tcl_by_driver import TCLByDriverChartGenerator
from src.api.services.charts.tcl_by_fires import TCLByFiresChartGenerator
from src.api.services.charts.tree_cover import TreeCoverChartGenerator
from src.api.services.charts.tree_cover_gain import TreeCoverGainChartGenerator

__all__ = [
    "ChartGenerator",
    "column_to_rows",
    "IntegratedAlertsChartGenerator",
    "LandCoverChangeChartGenerator",
    "LGMS_CLASS_LABELS",
    "LGMS_FULL_SERIES_CLASS_ORDER",
    "LGMSChartGenerator",
    "DETERMINISTIC_GENERATORS",
    "TCLChartGenerator",
    "ForestFluxChartGenerator",
    "GrasslandsChartGenerator",
    "NaturalLandsChartGenerator",
    "SlucEmissionFactorsChartGenerator",
    "TCLByDriverChartGenerator",
    "TCLByFiresChartGenerator",
    "TreeCoverChartGenerator",
    "TreeCoverGainChartGenerator",
]
