"""The registered analysis templates."""

from datetime import date, timedelta
from typing import Optional

from pydantic import Field

from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_ID,
)
from src.api.schemas import ALERTS_MAX_DAYS
from src.api.services.analysis_templates.models import (
    AlertsWidgetSpec,
    AnalysisTemplate,
    ChartFact,
    ChartWidgetSpec,
    ImageryWidgetSpec,
    LayerWidgetSpec,
    NaturalForestLossWidgetSpec,
    TemplateArgs,
    TextWidgetSpec,
)
from src.api.services.charts.tcl_natural_forest import FIRST_YEAR


class NrtMonitoringArgs(TemplateArgs):
    days: int = Field(
        default=30,
        ge=1,
        # The template's days become the alerts widget's, which this bounds.
        le=ALERTS_MAX_DAYS,
        description="Length of the period in days, counted back from today.",
    )

    def period(self, today: date) -> tuple[date, date]:
        return today - timedelta(days=self.days), today


class Post2020ForestLossArgs(TemplateArgs):
    def period(self, today: date) -> tuple[date, date]:
        # The chart and the map are clamped to the end of the loss data, and
        # so is the section. The imagery is of today.
        return date(FIRST_YEAR, 1, 1), today


class ForestLossDriversArgs(TemplateArgs):
    def period(self, today: date) -> tuple[date, date]:
        # From the first year of tree cover loss data. The widgets clamp the
        # end to the last year (2025).
        return date(2001, 1, 1), today


NRT_MONITORING_RULES = (
    "two or three sentences of plain prose, no markup. First give the fact "
    "on the latest alerts: the alert days, the area with its unit and the "
    "dates, or that no alerts were recorded. Take every figure and every "
    "date from the facts. Do not compute new figures. Then say that the "
    "alerts show possible disturbance, not confirmed deforestation. End "
    "with: Pick a period to see the list and the map for the same dates."
)


POST_2020_FOREST_LOSS_RULES = (
    "three to five sentences of plain prose, no markup. First give the fact "
    "on natural forest loss: the share with the natural forest area, the "
    "total area and their unit, or that no loss was recorded. Take every "
    "figure and every year from the facts. Do not compute new figures. Then "
    "explain, combining points where it reads well: the SBTN Natural Lands "
    "Map is a 2020 baseline, so the split covers loss from 2021 on; no "
    "canopy density threshold applies, so the totals are higher than the "
    "default 30% figures of Global Forest Watch (do not state a 30% "
    "threshold); other tree cover is non-natural forest, such as plantations "
    "and tree crops, plus loss outside the 2020 forest classes; natural "
    "forest is broader than primary forest, as it includes regenerated and "
    "secondary natural forest and excludes plantations; tree cover loss is "
    "not the same as deforestation."
)


FOREST_LOSS_DRIVERS_RULES = (
    "three or four sentences of plain prose, no markup. First give the "
    "facts, in their order. Take every figure and every year from the "
    "facts. Do not compute new figures. Say tree cover loss, never "
    "deforestation. The section has a fixed note on how to read the data: "
    "do not repeat its explanations."
)


TEMPLATES: tuple[AnalysisTemplate, ...] = (
    AnalysisTemplate(
        name="nrt-monitoring",
        label_key="analysis_template.nrt_monitoring.label",
        purpose="Show recent forest disturbance in the area, day by day.",
        description_rules=NRT_MONITORING_RULES,
        fallback_title_key="analysis_template.nrt_monitoring.title",
        fallback_description_key=(
            "analysis_template.nrt_monitoring.description"
        ),
        args_model=NrtMonitoringArgs,
        # The alerts widget's map is the alerts layer, so there is no
        # separate layer widget. The chart and the list share one period.
        widgets=(
            ChartWidgetSpec(dataset_id=INTEGRATED_ALERTS_ID),
            AlertsWidgetSpec(),
            ImageryWidgetSpec(),
        ),
    ),
    AnalysisTemplate(
        name="post-2020-forest-loss",
        label_key="analysis_template.post_2020_forest_loss.label",
        purpose=(
            "Show how much tree cover loss since 2021 was in natural "
            "forest, year by year, with a loss map and recent imagery."
        ),
        description_rules=POST_2020_FOREST_LOSS_RULES,
        fallback_title_key="analysis_template.post_2020_forest_loss.title",
        fallback_description_key=(
            "analysis_template.post_2020_forest_loss.description"
        ),
        args_model=Post2020ForestLossArgs,
        widgets=(
            NaturalForestLossWidgetSpec(),
            LayerWidgetSpec(
                dataset_id=TREE_COVER_LOSS_ID,
                context_layer="natural_forest",
                size="single",
            ),
            # A month, not a week: a cloud-free week is rare in the tropics.
            ImageryWidgetSpec(window_days=30, size="single"),
        ),
    ),
    AnalysisTemplate(
        name="forest-loss-drivers",
        label_key="analysis_template.forest_loss_drivers.label",
        purpose=(
            "Show how much tree cover the area lost each year since 2001, "
            "what drove the loss, and where it happened."
        ),
        description_rules=FOREST_LOSS_DRIVERS_RULES,
        fallback_title_key="analysis_template.forest_loss_drivers.title",
        fallback_description_key=(
            "analysis_template.forest_loss_drivers.description"
        ),
        args_model=ForestLossDriversArgs,
        widgets=(
            ChartWidgetSpec(
                dataset_id=TREE_COVER_LOSS_ID,
                charts=("charts.tcl.annual_loss",),
                facts=(
                    ChartFact(
                        kind="total",
                        text_key="analysis_template.forest_loss_drivers.total",
                        # The same sentence as the post-2020 template's.
                        empty_key=(
                            "analysis_template.natural_forest_loss.no_loss"
                        ),
                    ),
                    ChartFact(
                        kind="peak",
                        text_key="analysis_template.forest_loss_drivers.peak",
                    ),
                ),
            ),
            # Optional: an area with no loss has no driver to show, and the
            # section still has the loss chart and the map.
            ChartWidgetSpec(
                dataset_id=TREE_COVER_LOSS_BY_DRIVER_ID,
                facts=(
                    ChartFact(
                        kind="top_share",
                        text_key=(
                            "analysis_template.forest_loss_drivers.top_driver"
                        ),
                    ),
                ),
                required=False,
                size="single",
            ),
            # Half width each, the pie and the note share the row under the
            # loss chart.
            TextWidgetSpec(
                text_key="analysis_template.forest_loss_drivers.note",
                size="single",
            ),
            # Last, at the full width a map takes by default.
            LayerWidgetSpec(dataset_id=TREE_COVER_LOSS_BY_DRIVER_ID),
        ),
    ),
)

TEMPLATES_BY_NAME: dict[str, AnalysisTemplate] = {
    template.name: template for template in TEMPLATES
}


def get_template(name: str) -> Optional[AnalysisTemplate]:
    return TEMPLATES_BY_NAME.get(name)
