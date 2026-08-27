"""The ordered list of chart generators `AnalyzeService` picks from."""

from typing import List

from src.api.services.charts.base import ChartGenerator
from src.api.services.charts.forest_flux import ForestFluxChartGenerator
from src.api.services.charts.grasslands import GrasslandsChartGenerator
from src.api.services.charts.integrated_alerts import (
    IntegratedAlertsChartGenerator,
)
from src.api.services.charts.land_cover import (
    LandCoverChangeChartGenerator,
)
from src.api.services.charts.lgms import LGMSChartGenerator
from src.api.services.charts.natural_lands import NaturalLandsChartGenerator
from src.api.services.charts.sluc import SlucEmissionFactorsChartGenerator
from src.api.services.charts.tcl import TCLChartGenerator
from src.api.services.charts.tcl_by_driver import TCLByDriverChartGenerator
from src.api.services.charts.tcl_by_fires import TCLByFiresChartGenerator
from src.api.services.charts.tree_cover import TreeCoverChartGenerator
from src.api.services.charts.tree_cover_gain import TreeCoverGainChartGenerator

DETERMINISTIC_GENERATORS: List[ChartGenerator] = [
    TCLChartGenerator(),
    IntegratedAlertsChartGenerator(),
    LGMSChartGenerator(),
    LandCoverChangeChartGenerator(),
    ForestFluxChartGenerator(),
    GrasslandsChartGenerator(),
    NaturalLandsChartGenerator(),
    SlucEmissionFactorsChartGenerator(),
    TCLByDriverChartGenerator(),
    TCLByFiresChartGenerator(),
    TreeCoverChartGenerator(),
    TreeCoverGainChartGenerator(),
]
