"""The shape of an analysis template.

A template is a Pydantic object, not a module with methods. A new template
is one registry entry, one args model and its i18n strings. A new widget
kind is one spec class here and one builder function in ``builder``.
"""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TemplateArgs(BaseModel):
    """The arguments of one template. Each template has a subclass.

    The API and the agent send the arguments as a dict. The template's
    subclass validates them, and its JSON schema tells clients which
    arguments the template takes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    def period(self, today: date) -> tuple[date, date]:
        """The start and end dates that the widgets cover."""
        raise NotImplementedError


class ChartWidgetSpec(BaseModel):
    """A curated chart of one dataset, from the analytics pull."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["chart"] = "chart"
    dataset_id: int
    # A failed required widget stops the build.
    required: bool = True


class LayerWidgetSpec(BaseModel):
    """A map widget with the tile layer of one dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["layer"] = "layer"
    dataset_id: int
    required: bool = True


class ImageryWidgetSpec(BaseModel):
    """A map widget with a Sentinel-2 mosaic of the area at the period end."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["imagery"] = "imagery"
    window_days: int = 7
    max_cloud_cover: int = 20
    # A failed optional widget adds a warning and is left out.
    required: bool = False


WidgetSpec = Annotated[
    ChartWidgetSpec | LayerWidgetSpec | ImageryWidgetSpec,
    Field(discriminator="kind"),
]


class AnalysisTemplate(BaseModel):
    """A named spec for one dashboard section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    # i18n key of the name shown in the template list.
    label_key: str
    # One sentence for the text model and the agent: what the section is for.
    purpose: str
    # i18n keys for the text used when the text model fails. Placeholders:
    # {aoi_name}, {start_date}, {end_date}.
    fallback_title_key: str
    fallback_description_key: str
    # Validates the arguments of a request.
    args_model: type[TemplateArgs]
    widgets: tuple[WidgetSpec, ...]

    def parse_args(self, raw: dict[str, Any] | None) -> TemplateArgs:
        """The validated arguments. Raises ``pydantic.ValidationError``."""
        return self.args_model.model_validate(raw or {})

    def dataset_ids(self) -> list[int]:
        """The datasets the template reads, in widget order, no repeats."""
        ids: list[int] = []
        for widget in self.widgets:
            dataset_id = getattr(widget, "dataset_id", None)
            if dataset_id is not None and dataset_id not in ids:
                ids.append(dataset_id)
        return ids
