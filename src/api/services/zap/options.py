"""The option lists jev picks from in zap mode."""

import re
from datetime import date, timedelta
from typing import Optional

from src.agent.datasets.config import DATASETS

KEEP = "keep"
NONE = "none"

# Short, uniform dataset descriptions ("capability cards"), from the jev
# dataset-picker experiments (PR #841, variant `cards:neutral`). They scored
# 94-98% on the dataset step, against 78-96% for the long catalog text.
# The cards live in the catalog YAML (`selection_card`), which the MCP
# server's dataset listing reads too. Zap offers the datasets that have a
# map layer and that the default profile shows: not 9 (sLUC emission
# factors, table data with no map layer) and not 12 (LGMS, hidden by
# default). This set is the rule; a card alone does not put a dataset in
# zap. A dataset with no card is left out as well, rather than failing the
# import (and so the app).
ZAP_EXCLUDED_DATASET_IDS = frozenset({9, 12})
DATASET_CARDS: dict[int, str] = {
    ds["dataset_id"]: ds["selection_card"]
    for ds in DATASETS
    if ds["dataset_id"] not in ZAP_EXCLUDED_DATASET_IDS
    and ds.get("selection_card")
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
