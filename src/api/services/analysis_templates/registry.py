"""The registered analysis templates."""

from datetime import date, timedelta
from typing import Optional

from pydantic import Field

from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    TREE_COVER_LOSS_ID,
)
from src.api.services.analysis_templates.models import (
    AnalysisTemplate,
    ChartWidgetSpec,
    ImageryWidgetSpec,
    LayerWidgetSpec,
    NaturalForestLossWidgetSpec,
    TemplateArgs,
)
from src.api.services.charts.tcl_natural_forest import FIRST_YEAR


class NrtMonitoringArgs(TemplateArgs):
    days: int = Field(
        default=14,
        ge=1,
        le=365,
        description="Length of the period in days, counted back from today.",
    )

    def period(self, today: date) -> tuple[date, date]:
        return today - timedelta(days=self.days), today


class Post2020ForestLossArgs(TemplateArgs):
    def period(self, today: date) -> tuple[date, date]:
        # The chart is clamped to the end of the loss data. The imagery is
        # of today.
        return date(FIRST_YEAR, 1, 1), today


POST_2020_FOREST_LOSS_RULES = (
    "three to five sentences of plain prose, no markup. First give the fact "
    "on natural forest loss: the share with the natural forest area, the "
    "total area and their unit, or that no loss was recorded. Take every "
    "figure and every year from the facts: the period in the input is only "
    "the date of the imagery. Do not compute new figures. Then explain, "
    "combining points where it reads well: the SBTN Natural Lands Map is a "
    "2020 baseline, so the split covers loss from 2021 on; no canopy "
    "density threshold applies, so the totals are higher than the default "
    "30% figures of Global Forest Watch (do not state a 30% threshold); "
    "other tree cover is non-natural forest, such as plantations and tree "
    "crops, plus loss outside the 2020 forest classes; natural forest is "
    "broader than primary forest, as it includes regenerated and secondary "
    "natural forest and excludes plantations; tree cover loss is not the "
    "same as deforestation."
)


TEMPLATES: tuple[AnalysisTemplate, ...] = (
    AnalysisTemplate(
        name="nrt-monitoring",
        label_key="analysis_template.nrt_monitoring.label",
        purpose="Show recent forest disturbance in the area, day by day.",
        fallback_title_key="analysis_template.nrt_monitoring.title",
        fallback_description_key=(
            "analysis_template.nrt_monitoring.description"
        ),
        args_model=NrtMonitoringArgs,
        widgets=(
            ChartWidgetSpec(dataset_id=INTEGRATED_ALERTS_ID),
            LayerWidgetSpec(dataset_id=INTEGRATED_ALERTS_ID),
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
)

TEMPLATES_BY_NAME: dict[str, AnalysisTemplate] = {
    template.name: template for template in TEMPLATES
}


def get_template(name: str) -> Optional[AnalysisTemplate]:
    return TEMPLATES_BY_NAME.get(name)
