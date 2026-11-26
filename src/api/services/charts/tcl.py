"""Tree Cover Loss chart generator."""

from typing import List, Optional, Sequence

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_LOSS_ID
from src.agent.datasets.palette import PALETTES
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator
from src.api.services.charts.ranking import RankedArea, build_ranking

# The annual loss bars take the colour of the tree cover loss map layer.
LOSS_COLOR = PALETTES[TREE_COVER_LOSS_ID]["series_color"]
if LOSS_COLOR is None:
    raise RuntimeError("The tree cover loss palette has no series_color")


class TCLChartGenerator(ChartGenerator):
    """Tree Cover Loss: annual loss area + annual GHG emissions, as two bars."""

    dataset_id = TREE_COVER_LOSS_ID

    def __init__(self, areas: Optional[Sequence[RankedArea]] = None):
        self._areas = list(areas) if areas is not None else None

    def for_areas(self, areas: Sequence[RankedArea]) -> "TCLChartGenerator":
        return TCLChartGenerator(areas)

    def _rankings(self, rows: List[dict]) -> List[InsightChart]:
        """The areas of the pull as bars, ranked by loss and by emissions.
        Built from every pulled row, also the rows of 0 that the annual
        charts drop, and in this order, as the annual pair. A measure that
        no row has gives no chart."""
        charts = [
            self._ranking(
                rows,
                title="charts.tcl.loss_ranking",
                column="area_ha",
                color=LOSS_COLOR,
            ),
            self._ranking(
                rows,
                title="charts.tcl.emissions_ranking",
                column="carbon_emissions_MgCO2e",
                color=None,
            ),
        ]
        kept = [chart for chart in charts if chart is not None]
        for position, chart in enumerate(kept):
            chart.position = position
        return kept

    def _ranking(
        self,
        rows: List[dict],
        title: str,
        column: str,
        color: Optional[str],
    ) -> Optional[InsightChart]:
        assert self._areas is not None
        ranking = build_ranking(rows, self._areas, column)
        if not ranking:
            return None
        return InsightChart(
            position=0,
            title=title,
            chart_type="ranked-bar",
            x_axis="name",
            y_axis=column,
            series_color=color,
            chart_data=ranking,
        )

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        # Two or more areas are ranked; one area has its years as bars.
        if self._areas is not None and len(self._areas) >= 2:
            return self._rankings(rows)
        # The analytics API returns rows in arbitrary order; sort by year so
        # the chart's category x-axis reads 2001 → 2025 rather than a shuffle.
        rows = sorted(
            (r for r in rows if r.get("area_ha") != 0),
            key=lambda r: r.get("tree_cover_loss_year") or 0,
        )
        return [
            InsightChart(
                position=0,
                title="charts.tcl.annual_loss",
                chart_type="bar",
                x_axis="tree_cover_loss_year",
                y_axis="area_ha",
                series_color=LOSS_COLOR,
                chart_data=rows,
            ),
            InsightChart(
                position=1,
                title="charts.tcl.annual_emissions",
                chart_type="bar",
                x_axis="tree_cover_loss_year",
                y_axis="carbon_emissions_MgCO2e",
                chart_data=rows,
            ),
        ]
