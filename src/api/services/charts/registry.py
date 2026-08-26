"""The ordered list of chart generators `AnalyzeService` picks from."""

from typing import List

from src.api.services.charts.base import ChartGenerator
from src.api.services.charts.integrated_alerts import (
    IntegratedAlertsChartGenerator,
)
from src.api.services.charts.lgms import LGMSChartGenerator
from src.api.services.charts.tcl import TCLChartGenerator

DETERMINISTIC_GENERATORS: List[ChartGenerator] = [
    TCLChartGenerator(),
    IntegratedAlertsChartGenerator(),
    LGMSChartGenerator(),
]
