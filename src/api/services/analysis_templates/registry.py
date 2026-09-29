"""The registered analysis templates."""

from datetime import date, timedelta
from typing import Optional

from pydantic import Field

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.api.services.analysis_templates.models import (
    AnalysisTemplate,
    ChartWidgetSpec,
    ImageryWidgetSpec,
    LayerWidgetSpec,
    TemplateArgs,
)


class NrtMonitoringArgs(TemplateArgs):
    days: int = Field(
        default=14,
        ge=1,
        le=365,
        description="Length of the period in days, counted back from today.",
    )

    def period(self, today: date) -> tuple[date, date]:
        return today - timedelta(days=self.days), today


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
)

TEMPLATES_BY_NAME: dict[str, AnalysisTemplate] = {
    template.name: template for template in TEMPLATES
}


def get_template(name: str) -> Optional[AnalysisTemplate]:
    return TEMPLATES_BY_NAME.get(name)
