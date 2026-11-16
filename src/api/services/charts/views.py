"""The registry of curated chart views.

A view is one named curated chart. A generator makes the charts of a
dataset; each chart it can make is one view here. The registry is the
stable name of a chart for everything that refers to it: the provenance on
a stored chart (`view_id`, `view_revision`), and later a selector that
picks a view for a question.

Rules:

- A view `id` is permanent. Do not rename it, and do not use it again for
  a different chart. Stored charts and eval labels refer to it.
- Increase `revision` when the output of the view changes for the same
  rows: its chart type, its axes, its series, or how it sums the rows. A
  change of title text or colour does not need a new revision.

`build_curated_charts` stamps each chart with its view. A stored chart is
a snapshot, so a new revision does not change charts already stored.
"""

from dataclasses import dataclass
from typing import Literal, Optional

from src.agent.datasets.handlers.analytics_handler import (
    FOREST_CARBON_FLUX_ID,
    GRASSLANDS_ID,
    INTEGRATED_ALERTS_ID,
    LAND_COVER_CHANGE_ID,
    LAND_GHG_INVENTORY_ID,
    NATURAL_LANDS_ID,
    SLUC_EMISSION_FACTORS_ID,
    TREE_COVER_GAIN_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
    TREE_COVER_LOSS_ID,
)

TITLE_PREFIX = "charts."


@dataclass(frozen=True)
class ChartView:
    """One curated chart, by name."""

    # Permanent name, for example "tcl.annual_loss".
    id: str
    dataset_id: int
    # What the view shows and the question it answers, in one or two
    # sentences. Text for a selector, not for the user.
    card: str
    revision: int = 1
    # How many areas the rows can cover. A "one_area" view sums or mixes
    # the rows of several areas, so it is wrong for a comparison.
    shape: Literal["one_area", "many_areas"] = "one_area"
    # False for a view that only an analysis template can build, because
    # its rows do not come from a plain pull of the dataset.
    from_pull: bool = True
    # True when `generate_insights` can show the view in place of a chart
    # from the code executor (docs/curated-charts-first-plan.md). Release
    # each view by itself, after its generator agrees with the rules of
    # its dataset.
    agent_enabled: bool = False
    # Model-facing text that the curated tool message gives under the
    # chart: what the figures cover when the chart cannot show it, for
    # example a fixed period or a class that the chart leaves out.
    agent_note: Optional[str] = None

    @property
    def title_key(self) -> str:
        """The i18n key of the chart title that the generator emits."""
        return TITLE_PREFIX + self.id


VIEWS: tuple[ChartView, ...] = (
    ChartView(
        "tcl.annual_loss",
        TREE_COVER_LOSS_ID,
        "Tree cover loss area (ha) for each year, as bars. Answers how much "
        "tree cover was lost, in one year or in total, and which year had "
        "the most loss.",
        agent_enabled=True,
    ),
    ChartView(
        "tcl.annual_emissions",
        TREE_COVER_LOSS_ID,
        "Greenhouse gas emissions (MgCO2e) from tree cover loss for each "
        "year, as bars. Answers how much carbon the loss emitted.",
        agent_enabled=True,
    ),
    ChartView(
        "tcl_natural_forest.annual_split",
        TREE_COVER_LOSS_ID,
        "Tree cover loss area (ha) for each year, split into natural forest "
        "and other tree cover, as stacked bars.",
        from_pull=False,
    ),
    ChartView(
        "integrated_alerts.by_confidence",
        INTEGRATED_ALERTS_ID,
        "Disturbance alert area (ha) for each day, split by confidence "
        "(low, high, highest), as stacked bars. Answers how much area had "
        "alerts in a period and when the alerts occurred.",
    ),
    ChartView(
        "lgms.annual_average",
        LAND_GHG_INVENTORY_ID,
        "Annual average land emissions and removals by category, as a "
        "hierarchy of bars.",
    ),
    ChartView(
        "lgms.full_detail",
        LAND_GHG_INVENTORY_ID,
        "Land emissions and removals for each year in full class detail, "
        "as stacked bars with the net flux as a line.",
    ),
    ChartView(
        "lgms.by_category",
        LAND_GHG_INVENTORY_ID,
        "Land emissions and removals for each year by category (vegetation, "
        "soil, cropland management, livestock), as stacked bars with the "
        "net flux as a line.",
    ),
    ChartView(
        "lgms.summary",
        LAND_GHG_INVENTORY_ID,
        "Land use emissions, agriculture emissions and land use removals "
        "for each year, as stacked bars with the net flux as a line.",
    ),
    ChartView(
        "land_cover.transitions",
        LAND_COVER_CHANGE_ID,
        "Area (ha) of each change from one land cover class to another "
        "between 2015 and 2024, as a table, largest first. Answers what "
        "land was converted to.",
    ),
    ChartView(
        "land_cover.composition",
        LAND_COVER_CHANGE_ID,
        "Area (ha) of each land cover class in one year, as a pie. Answers "
        "what the land cover of an area is and which class is the largest.",
    ),
    ChartView(
        "forest_flux.net",
        FOREST_CARBON_FLUX_ID,
        "Forest greenhouse gas gross emissions, gross removals and net flux "
        "(MgCO2e) for the whole period, as bars. Answers if the forest is a "
        "carbon source or a carbon sink.",
    ),
    ChartView(
        "grasslands.by_year",
        GRASSLANDS_ID,
        "Natural and semi-natural grassland area (ha) for each year, as "
        "bars. Answers how much grassland an area has and how it changed.",
    ),
    ChartView(
        "natural_lands.by_class",
        NATURAL_LANDS_ID,
        "Area (ha) of each natural and non-natural land class in 2020, as a "
        "pie. Answers how much of an area is natural land and which class "
        "is the largest.",
    ),
    ChartView(
        "sluc.by_gas",
        SLUC_EMISSION_FACTORS_ID,
        "Deforestation (sLUC) emissions (tCO2e) by greenhouse gas, as a pie.",
    ),
    ChartView(
        "sluc.by_crop",
        SLUC_EMISSION_FACTORS_ID,
        "Deforestation (sLUC) emissions (tCO2e) by crop, as a table, "
        "largest first. Answers which crop has the most emissions.",
    ),
    ChartView(
        "tcl_by_driver.by_driver",
        TREE_COVER_LOSS_BY_DRIVER_ID,
        "Tree cover loss area (ha) for each dominant driver over the whole "
        "period, as a pie, without the unknown driver. Answers what caused "
        "the loss and which cause is the largest.",
        agent_enabled=True,
        agent_note=(
            "The drivers cover the whole period 2001 to 2025. The data has "
            "no years, so it cannot give the drivers of one year or of a "
            "shorter period. The chart leaves out the Unknown driver: the "
            "total and the shares in its facts are of the loss with a known "
            "driver."
        ),
    ),
    ChartView(
        "tcl_by_fires.split",
        TREE_COVER_LOSS_BY_FIRES_ID,
        "Tree cover loss area (ha) in one year, split into loss from fires "
        "and loss from other causes, as a pie.",
    ),
    ChartView(
        "tcl_by_fires.annual_split",
        TREE_COVER_LOSS_BY_FIRES_ID,
        "Tree cover loss area (ha) for each year, split into loss from "
        "fires and loss from other causes, as stacked bars. Answers how "
        "much loss fires caused and in which year fires caused the most.",
    ),
    ChartView(
        "tree_cover.extent",
        TREE_COVER_ID,
        "Tree cover area (ha) in 2000 for each area of the pull, as bars, "
        "largest first. Answers how much tree cover an area had.",
        shape="many_areas",
    ),
    ChartView(
        "tree_cover_gain.by_period",
        TREE_COVER_GAIN_ID,
        "Tree cover gain area (ha) for each period that ends in 2020, as "
        "bars. Answers how much tree cover an area gained.",
    ),
)

_BY_ID = {view.id: view for view in VIEWS}
if len(_BY_ID) != len(VIEWS):
    raise RuntimeError("Two chart views have the same id")


def get_view(view_id: str) -> Optional[ChartView]:
    return _BY_ID.get(view_id)


def view_for_title(title_key: str) -> Optional[ChartView]:
    """The view of a chart whose title is still the generator's i18n key;
    None for any other title."""
    if not title_key.startswith(TITLE_PREFIX):
        return None
    return _BY_ID.get(title_key[len(TITLE_PREFIX) :])


def views_for_dataset(
    dataset_id: int, *, from_pull: bool = True
) -> list[ChartView]:
    """The views of a dataset, in registry order. By default only the views
    that a plain pull of the dataset can build."""
    return [
        view
        for view in VIEWS
        if view.dataset_id == dataset_id and (view.from_pull or not from_pull)
    ]


def agent_views(dataset_id: int) -> list[ChartView]:
    """The views of a dataset that the agent can show in place of a
    generated chart, in registry order."""
    return [
        view for view in views_for_dataset(dataset_id) if view.agent_enabled
    ]
