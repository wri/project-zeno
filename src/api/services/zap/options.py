"""The option lists jev picks from in zap mode."""

import re
from datetime import date, timedelta
from typing import Optional

KEEP = "keep"
NONE = "none"

# Short, uniform dataset descriptions ("capability cards"), from the jev
# dataset-picker experiments (PR #841, variant `cards:neutral`). They scored
# 94-98% on the dataset step, against 78-96% for the long catalog text.
# Not offered: 9 (sLUC emission factors, table data with no map layer) and
# 12 (LGMS, not released in the default profile).
DATASET_CARDS: dict[int, str] = {
    1: "Global land cover (2015-2024). Land cover and land use classes at 30 m: bare ground and sparse vegetation, short vegetation, tree cover, wetlands, water, snow/ice, cropland, cultivated grasslands, built-up land. Gives the area (ha) of each class in 2015 or 2024, and the transitions between classes from 2015 to 2024. No year-by-year series between 2015 and 2024.",
    2: "Natural/semi-natural grassland extent (2000-2022). Annual 30 m maps of natural and semi-natural grassland, which includes native grasslands, shrublands, savannas, steppes and tundra (low vegetation under 3 m). Gives grassland area (ha) for each year from 2000 to 2022 and its gain or loss between years. Does not include cultivated grassland or cropland.",
    3: "SBTN Natural Lands Map (2020). Baseline map of natural and non-natural land in 2020 at 30 m. Natural classes: natural forest, mangrove, natural peat forest, wetland natural forest, natural short vegetation, natural water, bare, snow. Non-natural classes: crop, built-up, non-natural tree cover, non-natural short vegetation. Gives the area of each class in 2020. Used for no-conversion (SBTN) targets. One year only, no change over time.",
    4: "Tree cover loss (2001-2025). Annual area (ha) of tree cover loss at 30 m for all vegetation over 5 m tall, and the annual greenhouse gas emissions from that loss (MgCO2e). Can be limited to primary forest or intact forest to measure deforestation. Supports a canopy cover threshold. Time step is one year; no monthly or seasonal values. Does not give the cause of the loss.",
    5: "Tree cover gain (2000-2020). Area (ha) where new tree cover over 5 m tall grew, cumulative over 2000-2020, 2005-2020, 2010-2020 and 2015-2020, at 30 m. Includes natural regrowth, forest recovery and plantation cycles. No annual values.",
    6: "Forest greenhouse gas net flux (2001-2025). Forest carbon balance at 30 m: greenhouse gas emissions from forest disturbance, carbon removals by forest growth, and the net flux between them (MgCO2e). Negative net flux means a carbon sink, positive means a source. One value for the whole 2001-2025 period (total or annual average); no year-by-year values.",
    7: "Tree cover (2000). Tree canopy cover density (percent) in the year 2000 at 30 m for vegetation over 5 m tall. Gives tree cover area and density for 2000, with a selectable canopy cover threshold; can be limited to primary forest. One year only, no change over time.",
    8: "Tree cover loss by dominant driver (2001-2025). Splits tree cover loss into its direct causes: permanent agriculture, hard commodities (mining, energy), shifting cultivation, logging, wildfire, settlements and infrastructure, other natural disturbances. Gives the area and share of loss for each cause. One total for the whole period; no year-by-year values.",
    10: "Tree cover loss due to fires (2001-2025). Annual tree cover loss at 30 m split into loss caused by fire and loss from all other causes. Can be limited to primary or intact forest. Time step is one year. No emissions data.",
    11: "Integrated alerts (December 2023 to present). Near-real-time alerts of vegetation disturbance, clearing and deforestation at 10 m, updated daily, from the DIST-ALERT, GLAD-L, GLAD-S2 and RADD systems. Gives disturbed area (ha) by alert date and by confidence (low, high, highest = detected by several systems). Covers all vegetation; cannot be split by land cover, ecosystem or cause.",
}

DATASET_INSTRUCTIONS = (
    "Which dataset best matches what the user wants to know? "
    f"Pick '{KEEP}' only if the request is not about the data."
)

PLACE_INSTRUCTIONS = (
    "Which words of the request name the area to show? An area can be a "
    "country, a state, a district, a protected area, a key biodiversity area "
    "or indigenous land. The name of a dataset or of an event is not an "
    f"area. Pick '{KEEP}' when the request names no area."
)

SCOPE_INSTRUCTIONS = "How many areas does the request ask about?"
SCOPES = {
    "single": "One named area, or no area at all",
    "several": "Two or more named areas, e.g. a comparison of countries",
    "subregions": "The parts of one area, e.g. 'which district in Amazonas'",
    "global": "The whole world, or a ranking of all countries",
}

PERIOD_INSTRUCTIONS = (
    "Which time period does the request ask about? "
    f"Pick '{KEEP}' when the request names no time."
)

AREA_INSTRUCTIONS = (
    f"Which area does the request mean? Pick '{NONE}' when no option is the "
    "area of the request."
)

CONTEXT_INSTRUCTIONS = (
    "Should the data be limited to a type of forest? Pick a forest type only "
    f"when the request asks for it, e.g. 'deforestation' or 'primary forest'. "
    f"Pick '{NONE}' otherwise."
)

CANOPY_INSTRUCTIONS = (
    "Which minimum canopy cover does the request ask for? "
    f"Pick '{NONE}' when the request does not name a canopy cover or canopy "
    "density threshold."
)

MAX_SPAN = 4


def place_spans(prompt: str) -> list[str]:
    """All groups of 1 to MAX_SPAN words of the prompt, as stac-zap does."""
    words = [w.strip(".") for w in re.findall(r"[\w'’.-]+", prompt)]
    words = [w for w in words if w]
    return sorted(
        {
            " ".join(words[i : i + n])
            for n in range(1, MAX_SPAN + 1)
            for i in range(len(words) - n + 1)
        }
    )


FIRST_YEAR = 2001


def period_options(today: date) -> dict[str, str]:
    options = {
        "all": "The whole record of the dataset",
        "last-12-months": "Recent: the last 12 months",
        "last-5-years": "The last 5 years",
        "last-10-years": "The last 10 years",
    }
    for year in range(today.year, FIRST_YEAR - 1, -1):
        options[str(year)] = f"The year {year} only"
    for year in range(today.year - 1, FIRST_YEAR - 1, -1):
        options[f"since-{year}"] = (
            f"From {year} until today, e.g. 'since {year}'"
        )
    return options


def period_range(
    period: str, today: date
) -> tuple[Optional[str], Optional[str]]:
    """The (start, end) dates of a period; (None, None) for the whole record."""
    if period == "last-12-months":
        return str(today - timedelta(days=365)), str(today)
    if period in ("last-5-years", "last-10-years"):
        years = 5 if period == "last-5-years" else 10
        return f"{today.year - years}-01-01", str(today)
    if period.startswith("since-"):
        return f"{period[6:]}-01-01", str(today)
    if period.isdigit():
        return f"{period}-01-01", f"{period}-12-31"
    return None, None
