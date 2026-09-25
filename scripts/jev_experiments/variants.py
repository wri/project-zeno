"""Description and instruction variants for the jev dataset question.

Every variant is a catalog-wide transformation or a fixed template filled
from catalog facts. No variant text was written from a test query.
"""

import re

from sets import KEYS, NONE, M

from src.agent.agent_config import DEFAULT_EXCLUDED_DATASETS
from src.agent.datasets.config import DATASETS as ALL_DATASETS

DATASETS = [
    ds
    for ds in ALL_DATASETS
    if ds["dataset_name"] not in DEFAULT_EXCLUDED_DATASETS
]
KEY = {ds["dataset_id"]: KEYS[ds["dataset_id"]] for ds in DATASETS}
NONE_DESC = "No dataset in the catalog can answer this query"


def _sentences(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"(])", text) if s]


def _filter(text, drop):
    """Drop the clauses (split on ';' and ' — ') that trip `drop`, so a
    sentence keeps its own facts when only its redirect names another
    dataset. A sentence left with no clauses is dropped."""
    out = []
    for sentence in _sentences(text):
        clauses = re.split(r"\s*;\s*|\s+—\s+", sentence)
        kept = [c for c in clauses if not drop(c)]
        if kept:
            joined = "; ".join(kept).rstrip(".;, ")
            out.append(joined + ".")
    return " ".join(out)


# Case-sensitive names used when one dataset's text refers to another one.
ALIASES = {
    1: ["Global Land Cover", "Global land cover"],
    2: ["Grasslands dataset", "Grassland dataset"],
    3: ["SBTN Natural Lands", "Natural Lands Map"],
    4: ["Tree Cover Loss", 'Tree cover loss"'],
    5: ["Tree Cover Gain", "Tree cover gain"],
    6: ["Forest greenhouse gas net flux"],
    7: ["Tree Cover dataset"],
    8: [
        "Tree Cover Loss by Dominant Driver",
        "Tree cover loss by dominant driver",
    ],
    9: ["sLUC emission factor dataset"],
    10: ["Tree cover loss due to fires"],
    11: ["Integrated alerts", "Integrated Alerts"],
    12: ["LGMS", "Land GHG Monitoring System"],
}


def _mentions_other(ds_id):
    names = [a for i, al in ALIASES.items() if i != ds_id for a in al]
    own = ALIASES.get(ds_id, [])

    def drop(sentence):
        s = sentence
        for a in own:  # "Tree cover loss by dominant driver" must not trip "Tree Cover Loss"
            s = s.replace(a, "")
        return any(a in s for a in names)

    return drop


def describe_base(ds, drop=None):
    """Same fields as the script's _describe, optionally filtering sentences."""
    f = (
        (lambda t: _filter(t, drop))
        if drop
        else (lambda t: re.sub(r"\s+", " ", str(t or "")).strip())
    )
    parts = [
        f"{ds['dataset_name']}.",
        f"Content date: {ds.get('content_date')}.",
        f"Description: {f(ds.get('description'))}",
        f"When to prefer: {f(ds.get('selection_hints'))}",
    ]
    for layer in ds.get("context_layers") or []:
        ext = f" (extent {layer['extent']})" if layer.get("extent") else ""
        parts.append(
            f"Context layer '{layer['value']}'{ext}: {f(layer.get('description'))}"
        )
    for p in ds.get("parameters") or []:
        parts.append(
            f"Parameter '{p['name']}', values {p.get('values')}: {f(p.get('description'))}"
        )
    return " ".join(parts)


# Capability cards: one fixed template (measures / units / time / breakdowns /
# own limits), filled from each dataset's YAML. No card names another dataset.
CARDS = {
    1: "Global land cover (2015-2024). Land cover and land use classes at 30 m: bare ground and sparse vegetation, short vegetation, tree cover, wetlands, water, snow/ice, cropland, cultivated grasslands, built-up land. Gives the area (ha) of each class in 2015 or 2024, and the transitions between classes from 2015 to 2024. No year-by-year series between 2015 and 2024.",
    2: "Natural/semi-natural grassland extent (2000-2022). Annual 30 m maps of natural and semi-natural grassland, which includes native grasslands, shrublands, savannas, steppes and tundra (low vegetation under 3 m). Gives grassland area (ha) for each year from 2000 to 2022 and its gain or loss between years. Does not include cultivated grassland or cropland.",
    3: "SBTN Natural Lands Map (2020). Baseline map of natural and non-natural land in 2020 at 30 m. Natural classes: natural forest, mangrove, natural peat forest, wetland natural forest, natural short vegetation, natural water, bare, snow. Non-natural classes: crop, built-up, non-natural tree cover, non-natural short vegetation. Gives the area of each class in 2020. Used for no-conversion (SBTN) targets. One year only, no change over time.",
    4: "Tree cover loss (2001-2025). Annual area (ha) of tree cover loss at 30 m for all vegetation over 5 m tall, and the annual greenhouse gas emissions from that loss (MgCO2e). Can be limited to primary forest or intact forest to measure deforestation. Supports a canopy cover threshold. Time step is one year; no monthly or seasonal values. Does not give the cause of the loss.",
    5: "Tree cover gain (2000-2020). Area (ha) where new tree cover over 5 m tall grew, cumulative over 2000-2020, 2005-2020, 2010-2020 and 2015-2020, at 30 m. Includes natural regrowth, forest recovery and plantation cycles. No annual values.",
    6: "Forest greenhouse gas net flux (2001-2025). Forest carbon balance at 30 m: greenhouse gas emissions from forest disturbance, carbon removals by forest growth, and the net flux between them (MgCO2e). Negative net flux means a carbon sink, positive means a source. One value for the whole 2001-2025 period (total or annual average); no year-by-year values.",
    7: "Tree cover (2000). Tree canopy cover density (percent) in the year 2000 at 30 m for vegetation over 5 m tall. Gives tree cover area and density for 2000, with a selectable canopy cover threshold; can be limited to primary forest. One year only, no change over time.",
    8: "Tree cover loss by dominant driver (2001-2025). Splits tree cover loss into its direct causes: permanent agriculture, hard commodities (mining, energy), shifting cultivation, logging, wildfire, settlements and infrastructure, other natural disturbances. Gives the area and share of loss for each cause. One total for the whole period; no year-by-year values.",
    9: "Deforestation (sLUC) emission factors by agricultural crop (2020-2024). Greenhouse gas emissions from deforestation linked to agricultural expansion, per tonne of crop product (tCO2e/t), for 42 crops, by country, state and district. Table data only, no map.",
    10: "Tree cover loss due to fires (2001-2025). Annual tree cover loss at 30 m split into loss caused by fire and loss from all other causes. Can be limited to primary or intact forest. Time step is one year. No emissions data.",
    11: "Integrated alerts (December 2023 to present). Near-real-time alerts of vegetation disturbance, clearing and deforestation at 10 m, updated daily, from the DIST-ALERT, GLAD-L, GLAD-S2 and RADD systems. Gives disturbed area (ha) by alert date and by confidence (low, high, highest = detected by several systems). Covers all vegetation; cannot be split by land cover, ecosystem or cause.",
}

RULES = M["DATASET_INSTRUCTIONS"]
SHORT = (
    "Which dataset has the data needed to answer the user's question? "
    f"Pick '{NONE}' only if no dataset measures what the user asks about."
)


def criteria(desc, none_mode="std"):
    c = {KEY[ds["dataset_id"]]: desc(ds) for ds in DATASETS}
    if NONE_MODES[none_mode]:
        c[NONE] = NONE_MODES[none_mode]
    return c


DESCRIPTIONS = {
    "base": describe_base,
    "no_lgms": lambda ds: describe_base(
        ds, drop=lambda s: "LGMS" in s or "Land GHG" in s
    ),
    "no_xref": lambda ds: describe_base(
        ds, drop=_mentions_other(ds["dataset_id"])
    ),
    "cards": lambda ds: CARDS[ds["dataset_id"]],
}
NEUTRAL = "Which dataset best matches what the user wants to know?"
INSTRUCTIONS = {"rules": RULES, "short": SHORT, "neutral": NEUTRAL}
# How the "none" option is offered: std = current text, topic = says what a
# decline means, drop = no none option (declines come from probabilities).
NONE_MODES = {
    "std": NONE_DESC,
    "topic": "The user asks about a variable, place type or time step that none of these datasets measure",
    "drop": None,
}


def question(desc_name, instr_name, none_mode="std"):
    """variant name = <description>:<instruction>[:<none mode>]"""
    return {
        "type": "choice",
        "instructions": INSTRUCTIONS[instr_name],
        "criteria": criteria(DESCRIPTIONS[desc_name], none_mode),
    }


if __name__ == "__main__":
    for name, fn in DESCRIPTIONS.items():
        c = criteria(fn)
        print(f"== {name}: {sum(map(len, c.values()))} chars")
    # Show what the sentence filters removed, to check they are not too greedy.
    for ds in DATASETS:
        drop = _mentions_other(ds["dataset_id"])
        print(f"\n[{KEY[ds['dataset_id']]}] no_xref hints:")
        print("   ", _filter(ds.get("selection_hints"), drop))
