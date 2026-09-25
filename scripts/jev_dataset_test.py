#!/usr/bin/env python3
"""Dataset-picker accuracy and latency test for the jev decision model.

Compares the open jev model on api.codiv.ai with Typesafe's jev on
OpenRouter's decisions API. Both get the same payload. Asks jev to pick a
dataset, context layer and canopy cover threshold for each query in
tests/tools/test_pick_dataset.py and a selection of GOLD offline-eval sheet
rows (GOLD_CASES), in one call per query.

Each catalog dataset becomes one choice. The choice text holds the same
fields the real picker shows its LLM (CANDIDATE_DATASET_LLM_COLUMNS):
description, selection_hints, content_date, context_layers, parameters and
layers. The instructions carry the real picker's SELECTION_RULES.

Differences from the real pick_dataset subagent:
- No RAG pre-filter: jev sees the full catalog, not the top 3 candidates.
- jev answers the three questions independently, so the context layer and
  canopy answers are not tied to the dataset it picked.
- Dates are not scored.
- Datasets in DEFAULT_EXCLUDED_DATASETS (LGMS) are left out, as in the
  default agent profile. Set INCLUDE_LGMS=1 to offer them.

Usage (reads TYPESAFE_API_KEY and OPENROUTER_API_KEY from .env; a backend
without a key is skipped):
    uv run python scripts/jev_dataset_test.py
"""

import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from src.agent.agent_config import DEFAULT_EXCLUDED_DATASETS
from src.agent.datasets.config import DATASETS
from src.agent.subagents.pick_dataset.tool import SELECTION_RULES

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")

# The same jev decision API, served two ways. Both take the same payload and
# return the same answers shape. A backend without an API key is skipped.
BACKENDS = [
    {
        "name": "codiv-open",
        "base_url": os.environ.get(
            "TYPESAFE_BASE_URL", "https://api.codiv.ai"
        ),
        "path": "/v1/systemone",
        "api_key": os.environ.get("TYPESAFE_API_KEY"),
        "model": os.environ.get("JEV_MODEL", "openjev-latest"),
    },
    {
        "name": "openrouter",
        "base_url": "https://openrouter.ai",
        "path": "/api/alpha/decisions",
        "api_key": os.environ.get("OPENROUTER_API_KEY"),
        "model": os.environ.get("OPENROUTER_JEV_MODEL", "typesafe/jev-1.13"),
    },
]
INCLUDE_LGMS = os.environ.get("INCLUDE_LGMS") == "1"

# Short keys for the dataset ids used in test_pick_dataset.py.
KEYS = {
    1: "land_cover",
    2: "grasslands",
    3: "natural_lands",
    4: "tcl",
    5: "tc_gain",
    6: "carbon_flux",
    7: "tree_cover",
    8: "tcl_driver",
    9: "sluc_ef",
    10: "tcl_fires",
    11: "integrated_alerts",
    12: "lgms",
}
NONE = "none"
# Marks an expectation the catalog cannot satisfy, so it is not scored.
SKIP = object()

DATASET_INSTRUCTIONS = f"""You are the dataset selector for Global Nature \
Watch. Pick the single best dataset for the user's request. An area of \
interest is NOT required to pick a dataset. If the user gives no dates, \
assume the dataset's own available range. Pick '{NONE}' when no dataset can \
usefully answer ALL parts of the question (that is what "dataset_id as \
null" means below).

Rules:
{SELECTION_RULES}"""

LAYER_INSTRUCTIONS = f"""Which context layer should be applied to the \
dataset that best answers the user's query? Use the context layer \
descriptions of the datasets. Pick a layer only when its description matches \
the query and the area of interest is inside the layer's extent. Pick \
'{NONE}' when no context layer applies."""

CANOPY_INSTRUCTIONS = f"""Which canopy_cover parameter value should be \
applied? Select parameters only when relevant, and use only values listed in \
the dataset. Pick '{NONE}' when the user did not ask for a canopy cover or \
canopy density threshold."""


def _squash(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _describe(ds: dict) -> str:
    parts = [
        f"{ds['dataset_name']}.",
        f"Content date: {ds.get('content_date')}.",
        f"Description: {_squash(ds.get('description'))}",
        f"When to prefer: {_squash(ds.get('selection_hints'))}",
    ]
    for layer in ds.get("context_layers") or []:
        extent = layer.get("extent")
        extent_s = f" (extent {extent})" if extent else ""
        parts.append(
            f"Context layer '{layer['value']}'{extent_s}: "
            f"{_squash(layer.get('description'))}"
        )
    for param in ds.get("parameters") or []:
        parts.append(
            f"Parameter '{param['name']}', values {param.get('values')}: "
            f"{_squash(param.get('description'))}"
        )
    for layer in ds.get("layers") or []:
        parts.append(
            f"Layer '{layer.get('name')}': {_squash(layer.get('description'))}"
        )
    return " ".join(parts)


def build_questions() -> dict:
    excluded = set() if INCLUDE_LGMS else DEFAULT_EXCLUDED_DATASETS
    datasets = [ds for ds in DATASETS if ds["dataset_name"] not in excluded]

    dataset_criteria = {
        KEYS.get(ds["dataset_id"], f"ds_{ds['dataset_id']}"): _describe(ds)
        for ds in datasets
    }
    dataset_criteria[NONE] = "No dataset in the catalog can answer this query"

    # Union of context layers; keep the most detailed description per value.
    layer_criteria: dict[str, str] = {}
    for ds in datasets:
        for layer in ds.get("context_layers") or []:
            desc = _squash(layer.get("description"))
            if extent := layer.get("extent"):
                desc += f" Extent: {extent}."
            if len(desc) > len(layer_criteria.get(layer["value"], "")):
                layer_criteria[layer["value"]] = desc
    layer_criteria[NONE] = "No context layer: analyse the whole dataset"

    canopy_values = sorted(
        {
            value
            for ds in datasets
            for param in ds.get("parameters") or []
            if param["name"] == "canopy_cover"
            for value in param.get("values") or []
        }
    )
    canopy_criteria = {
        str(value): f"canopy_cover = {value}% minimum canopy cover"
        for value in canopy_values
    }
    canopy_criteria[NONE] = "No canopy cover threshold requested"

    return {
        "dataset": {
            "type": "choice",
            "instructions": DATASET_INSTRUCTIONS,
            "criteria": dataset_criteria,
        },
        "layer": {
            "type": "choice",
            "instructions": LAYER_INSTRUCTIONS,
            "criteria": layer_criteria,
        },
        "canopy": {
            "type": "choice",
            "instructions": CANOPY_INSTRUCTIONS,
            "criteria": canopy_criteria,
        },
    }


# Copied from tests/tools/test_pick_dataset.py. Each case is a dict with the
# query, expected dataset and date range; "layer" and "canopy" are only
# scored when the source test checks them. "aoi" matches the `state` fixture
# the context-layer tests use.
D22 = ("2022-01-01", "2022-12-31")
D24 = ("2024-01-01", "2024-12-31")
INDONESIA = "Indonesia (GADM IDN, bbox [94.97, -11.01, 141.02, 6.08])"


def case(query, dataset, dates=D24, **extra) -> dict:
    return {
        "source": "unit",
        "query": query,
        "dataset": dataset,
        "dates": dates,
        **extra,
    }


CASES = [
    # test_queries_return_expected_dataset
    case(
        "Which year had more forest disturbance alerts in Ucayali, Peru, 2024 or 2025?",
        "integrated_alerts",
        ("2024-01-01", "2025-12-31"),
    ),
    case(
        "Show me recent vegetation disturbances in the Amazon basin over the past month",
        "integrated_alerts",
    ),
    case(
        "Have there been any new forest disturbance alerts in Indonesia this week?",
        "integrated_alerts",
    ),
    case(
        "I need to monitor recent forest disturbance alerts across East Africa",
        "integrated_alerts",
    ),
    case(
        "Which areas had the most forest disturbance alerts in the past 6 months?",
        "integrated_alerts",
    ),
    case("Which had more cropland in 2015, Nigeria or Ghana?", "land_cover"),
    case(
        "How has in agricultural expanded across Southeast Asia since 2015?",
        "land_cover",
    ),
    case(
        "I'm studying urbanization patterns in sub-Saharan Africa between 2015 and 2024",
        "land_cover",
    ),
    case(
        "Show me areas where wetlands have been converted to other uses",
        "land_cover",
    ),
    case(
        "Which regions show the fastest decline in native grassland habitats?",
        "grasslands",
    ),
    case(
        "I need data on natural and semi-natural pastoral landscapes",
        "grasslands",
    ),
    case("Where are the largest grassland ecosystems globally?", "grasslands"),
    case(
        "What percentage of land area in Brazil consists of natural ecosystems according to the 2020 baseline?",
        "natural_lands",
    ),
    case(
        "Show me areas where natural habitats remain undisturbed by human activities",
        "natural_lands",
    ),
    case(
        "What percent of 2000 forest did Kalimantan Barat lose from 2001 through 2024?",
        "tcl",
    ),
    case("Which country had the most deforestation in 2018?", "tcl"),
    case(
        "Where has forest regrowth occurred in the Amazon basin between 2000 and 2020?",
        "tc_gain",
    ),
    case(
        "Show me areas of tree cover gain in Southeast Asia over the past two decades",
        "tc_gain",
    ),
    case(
        "Which regions show the most significant forest recovery since 2000?",
        "tc_gain",
    ),
    case(
        "What areas of forest are acting as net carbon sinks versus sources?",
        "carbon_flux",
        ("2000-01-01", "2025-12-31"),
    ),
    case(
        "Show me forest carbon emissions and removals in the Congo Basin",
        "carbon_flux",
        ("2000-01-01", "2025-12-31"),
    ),
    case(
        "Which forests have been the largest net sources of greenhouse gas emissions since 2001?",
        "carbon_flux",
        ("2000-01-01", "2025-12-31"),
    ),
    case(
        "What percentage of land area in Brazil has tree cover above 30%?",
        "tree_cover",
    ),
    case(
        "Show me areas with high tree cover density in the Pacific Northwest",
        "tree_cover",
    ),
    case(
        "Which regions have the highest tree canopy cover globally?",
        "tree_cover",
    ),
    case(
        "What areas of forest are experiencing the most tree cover loss due to wildfire?",
        "tcl_fires",
    ),
    case(
        "Show me areas of tree cover loss by driver in the Congo Basin",
        "tcl_driver",
    ),
    case(
        "Which regions show the most significant tree cover loss by driver?",
        "tcl_driver",
    ),
    case(
        "What regions experienced the most fire-related tree cover loss?",
        "tcl_fires",
    ),
    case(
        "What vegetation disturbances happened this month in Borneo?",
        "integrated_alerts",
    ),
    case(
        "How much tree cover was lost in Brazil between 2010 and 2020?",
        "tcl",
        ("2010-01-01", "2020-12-31"),
    ),
    case("Why is tree cover being lost in Southeast Asia?", "tcl_driver"),
    case(
        "Show annual tree cover loss in Brazil from 2001 to 2024",
        "tcl",
        ("2001-01-01", "2024-12-31"),
    ),
    case(
        "How much tree cover does the DRC have?",
        "tree_cover",
        ("2000-01-01", "2000-12-31"),
    ),
    # Source has a typo ("foreLAND_COVER_CHANGEst"); fixed here.
    case(
        "Where has forest regrowth occurred in Indonesia since 2000?",
        "tc_gain",
        ("2000-01-01", "2020-12-31"),
    ),
    case(
        "What percentage of Colombia is natural land according to the 2020 SBTN baseline?",
        "natural_lands",
        ("2020-01-01", "2020-12-31"),
    ),
    case(
        "How did land cover change in Brazil between 2015 and 2024?",
        "land_cover",
        ("2015-01-01", "2024-12-31"),
    ),
    case(
        "How much natural grassland does Kenya have?",
        "grasslands",
        ("2000-01-01", "2022-12-31"),
    ),
    case(
        "How much cultivated grassland is there in Brazil?",
        "land_cover",
        ("2015-01-01", "2024-12-31"),
    ),
    case(
        "What is Brazil's cumulative net carbon flux (source or sink) since 2001?",
        "carbon_flux",
        ("2001-01-01", "2024-12-31"),
    ),
    case(
        "How much tree cover was lost each year in Brazil and what were the emissions?",
        "tcl",
        ("2001-01-01", "2024-12-31"),
    ),
    case(
        "What is the deforestation emission factor for soybean in Brazil?",
        "sluc_ef",
    ),
    case(
        "Show recent vegetation disturbances across all ecosystems in Brazil",
        "integrated_alerts",
    ),
    case(
        "What proportion of the total tree cover loss from 2001-2025 in Brazil is due to wildfire vs agriculture?",
        "tcl_driver",
        ("2001-01-01", "2025-12-31"),
    ),
    case(
        "Show annual forest emissions for Brazil from 2001 to 2024",
        "tcl",
        ("2001-01-01", "2024-12-31"),
    ),
    case(
        "How much tree cover did the DRC lose between 2000 and 2020?",
        "tcl",
        ("2000-01-01", "2020-12-31"),
    ),
    case(
        "Plot year-by-year carbon emissions from deforestation in Indonesia since 2001",
        "tcl",
        ("2001-01-01", "2024-12-31"),
    ),
    # test_query_with_context_layer
    case(
        "Vegetation disturbances by natural lands",
        NONE,
        D22,
        layer=NONE,
        aoi=INDONESIA,
    ),
    case(
        "Vegetation disturbances over grasslands",
        NONE,
        D22,
        layer=NONE,
        aoi=INDONESIA,
    ),
    # The source test expects context_layer "driver", but no catalog dataset
    # defines that layer, so it is not offered and not scored.
    case(
        "Tree cover loss by driver",
        "tcl_driver",
        D22,
        layer=SKIP,
        aoi=INDONESIA,
    ),
    case(
        "Tree cover loss in primary forest",
        "tcl",
        D22,
        layer="primary_forest",
        aoi=INDONESIA,
    ),
    case(
        "Tree cover loss in intact forest",
        "tcl",
        D22,
        layer="intact_forest",
        aoi=INDONESIA,
    ),
    case(
        "Tree  cover loss in the past decade in sparse forests",
        "tcl",
        D22,
        layer=NONE,
        aoi=INDONESIA,
    ),
    case(
        "Deforestation in the past decade",
        "tcl",
        D22,
        layer="primary_forest",
        aoi=INDONESIA,
    ),
    case(
        "Most recent global land cover",
        "land_cover",
        D22,
        layer=NONE,
        aoi=INDONESIA,
    ),
    # test_query_with_parameter
    case(
        "Tree cover loss in the past decade where canopy cover is at least 50%",
        "tcl",
        D22,
        canopy="50",
    ),
    case(
        "Tree cover loss in the past decade where canopy threshold is 30",
        "tcl",
        D22,
        canopy="30",
    ),
    case("Tree cover loss in the past decade", "tcl", D22, canopy=NONE),
    # test_tree_cover_tile_url_with_canopy_density
    case(
        "Tree cover where where canopy density is greater than 15%",
        "tree_cover",
        ("2000-01-01", "2000-12-31"),
        canopy="15",
        aoi=INDONESIA,
    ),
]

# A selection of dataset-picking rows from the GOLD offline-eval sheet
# ("GNW offline evals - GOLD"), keyed by test_id. Dates are the sheet's
# expected dates; rows without them send "not specified". Context layer and
# canopy_cover are scored only where the sheet sets them.
NO_DATES = (None, None)


def gold(test_id, query, dataset, dates=NO_DATES, **extra) -> dict:
    return {
        "source": "gold",
        "id": test_id,
        "query": query,
        "dataset": dataset,
        "dates": dates,
        **extra,
    }


GOLD_CASES = [
    gold(
        "1-001",
        "True or false: Mount Hakusan biodiversity area had more area with high confidence disturbance alerts in August 2024 than September 2024",
        "integrated_alerts",
        ("2024-08-01", "2024-09-30"),
    ),
    gold(
        "1-009",
        "What percentage of disturbances in Sara, Bolivia were caught by multiple systems during July 2025?",
        "integrated_alerts",
    ),
    gold(
        "1-010",
        "How much wetland was there in the Arawe KBA in Papua New Guinea in 2024?",
        "land_cover",
        ("2024-01-01", "2024-12-11"),
    ),
    gold(
        "1-014",
        "True or False, the largest land cover transition between 2015 and 2024 in California, USA was short vegetation",
        "land_cover",
    ),
    gold(
        "1-018",
        "Yes or no: did natural grasslands increase from 2017 to 2022 in Hwange national park, botswana?",
        "grasslands",
        ("2017-01-01", "2022-12-31"),
    ),
    gold(
        "1-024",
        "which county in the state of Salto, Uruguay had the least natural grassland in 2001?",
        "grasslands",
    ),
    gold(
        "1-026",
        "Whats the second largest natural land class in the Plaine du Villefagnan key biodiversity area in FRA?",
        "natural_lands",
    ),
    gold(
        "1-029",
        "Which state in Indonesia has the most natural peat forest?",
        "natural_lands",
    ),
    gold(
        "1-036",
        "In which year between 2001 and 2024 did Gabon have the most tree cover loss?",
        "tcl",
    ),
    gold(
        "1-040",
        "How much carbon was emitted in the North Baikal wetlands KBA in 2024?",
        "tcl",
    ),
    gold(
        "1-044",
        "In which year between 2001 and 2024 did Indonesia have the lowest emissions due to tree cover loss?",
        "tcl",
    ),
    gold(
        "1-048",
        "True or false: in Alto Rio Guama, more tree cover was gained in the period between 2000-2010 than 2010-2020",
        "tc_gain",
        ("2000-01-01", "2020-12-31"),
    ),
    gold(
        "1-054",
        "Determine whether the Canary islands a net source or sink for deforestation related emissions.",
        "carbon_flux",
    ),
    gold(
        "1-055",
        "What was the net greenhouse gas flux for Las Palmas, Canarias (ESP)?",
        "carbon_flux",
    ),
    gold(
        "1-058",
        "In 2000, how much tree cover did Dja et Lobo Cameroon have?",
        "tree_cover",
    ),
    gold(
        "1-060",
        "Which state of brazil has lost the most tree cover due to permanent agriculture.",
        "tcl_driver",
    ),
    gold(
        "1-063",
        "True or False: Logging causes more more tree cover loss than Wildfire in Aveiro, Portugal?",
        "tcl_driver",
    ),
    gold(
        "1-073",
        "How much primary forest was lost in the Democratic Republic of Congo since the turn of the century?",
        "tcl",
        ("2002-01-01", "2025-12-31"),
        layer="primary_forest",
    ),
    gold(
        "1-076",
        "How much deforestation in Russia?",
        "tcl",
        ("2001-01-01", "2025-12-31"),
        layer="intact_forest",
    ),
    gold(
        "1-080",
        "Show me deforestation in Brazil",
        "tcl",
        layer="primary_forest",
    ),
    gold(
        "1-086",
        "How much of Indonesia's 2025 tree cover loss was caused by fire?",
        "tcl_fires",
    ),
    gold(
        "1-090",
        "Cuánta superficie forestal se perdió en España en 2022?",
        "tcl",
        ("2022-01-01", "2022-12-31"),
    ),
    gold(
        "1-093",
        "Berapa luas hutan yang hilang di Indonesia pada tahun 2022?",
        "tcl",
        ("2022-01-01", "2022-12-31"),
        layer="primary_forest",
    ),
    gold(
        "1-095",
        "Using a 10% canopy threshold, how much tree cover did Finland lose in 2025?",
        "tcl",
        ("2025-01-01", "2025-12-31"),
        canopy="10",
    ),
    gold("1-102", "Add tree cover loss to the map", "tcl"),
    gold(
        "1-103",
        "What were Brazil's soy-linked deforestation emissions in 2023?",
        "sluc_ef",
    ),
    # The sheet expects suggested datasets, not one pick (the picker's
    # "no direct match" case), for 1-082..1-084. 1-089 asks for monthly
    # tree cover loss, which no dataset has.
    gold("1-082", "give me urbanization since 2010 in Brazil", NONE),
    gold(
        "1-083",
        "Brazil deforestation linked to agricultural commodities in 2017",
        NONE,
    ),
    gold("1-084", "Show me trends in natural land loss in Gabon", NONE),
    gold("1-089", "Show me monthly tree cover loss for Brazil in 2024", NONE),
]


def _state(c: dict) -> str:
    start, end = c["dates"]
    dates = f"{start} to {end}" if start and end else "not specified"
    state = f"User: {c['query']}\nRequested date range: {dates}"
    if aoi := c.get("aoi"):
        state += f"\nArea of interest: {aoi}"
    return state


def ask(
    client: httpx.Client, backend: dict, questions: dict, c: dict
) -> tuple[dict, float, float | None]:
    """Return (answers, seconds, cost in USD if the backend reports it)."""
    payload = {
        "model": backend["model"],
        "state": _state(c),
        "questions": questions,
    }
    t0 = time.perf_counter()
    resp = client.post(backend["path"], json=payload)
    elapsed = time.perf_counter() - t0
    resp.raise_for_status()
    body = resp.json()
    return body["answers"], elapsed, (body.get("usage") or {}).get("cost")


def _checks(c: dict) -> list[tuple[str, str]]:
    """(question, expected) for each scored question of a case."""
    return [
        (question, c[question])
        for question in ("dataset", "layer", "canopy")
        if c.get(question) is not None and c.get(question) is not SKIP
    ]


def _short(text, width: int) -> str:
    text = str(text)
    return text if len(text) <= width else text[: width - 3] + "..."


def main() -> None:
    backends = [b for b in BACKENDS if b["api_key"]]
    if not backends:
        sys.exit("Set TYPESAFE_API_KEY and/or OPENROUTER_API_KEY.")
    questions = build_questions()
    cases = CASES + GOLD_CASES
    n_datasets = len(questions["dataset"]["criteria"]) - 1
    prompt_chars = sum(
        len(q["instructions"]) + sum(map(len, q["criteria"].values()))
        for q in questions.values()
    )

    clients = {
        b["name"]: httpx.Client(
            base_url=b["base_url"],
            headers={"Authorization": f"Bearer {b['api_key']}"},
            timeout=120,
        )
        for b in backends
    }
    # results[backend][case index] = (answers or error string, seconds, cost)
    results: dict[str, list] = {b["name"]: [] for b in backends}
    try:
        for c in cases:
            # Call the backends back to back so both see similar network
            # conditions for each case.
            for b in backends:
                try:
                    results[b["name"]].append(
                        ask(clients[b["name"]], b, questions, c)
                    )
                except (httpx.HTTPError, KeyError) as exc:
                    results[b["name"]].append(
                        (f"ERROR: {exc}", float("nan"), None)
                    )
    finally:
        for client in clients.values():
            client.close()

    names = [b["name"] for b in backends]
    n_gold = sum(c["source"] == "gold" for c in cases)
    print(
        f"datasets={n_datasets}  prompt_chars={prompt_chars}  "
        f"cases={len(cases)} (unit {len(cases) - n_gold}, gold {n_gold})"
    )
    for b in backends:
        print(
            f"  {b['name']:<12} model={b['model']}  url={b['base_url']}{b['path']}"
        )
    print()

    col = 22
    header = f"{'query':<50} {'check':<8} {'expected':<18}" + "".join(
        f" {name:<{col}}" for name in names
    )
    print(header)
    print("-" * len(header))
    for i, c in enumerate(cases):
        label = f"[{c['id']}] {c['query']}" if "id" in c else c["query"]
        for question, expected in _checks(c):
            cells = []
            for name in names:
                answers, _, _ = results[name][i]
                if isinstance(answers, str):
                    cells.append(_short(answers, col))
                    continue
                answer = answers.get(question) or {}
                got, conf = answer.get("choice"), answer.get("confidence")
                mark = "ok" if got == expected else "XX"
                conf_s = f"{conf:.2f}" if conf is not None else "-"
                cells.append(f"{mark} {_short(got, 13)} {conf_s}")
            print(
                f"{_short(label, 50):<50} {question:<8} {expected:<18}"
                + "".join(f" {cell:<{col}}" for cell in cells)
            )
    print("-" * len(header))

    print(f"\n{'summary':<24}" + "".join(f" {name:>14}" for name in names))
    for source in ("unit", "gold", None):
        for question in ("dataset", "layer", "canopy"):
            cells = []
            for name in names:
                oks = [
                    not isinstance(results[name][i][0], str)
                    and (results[name][i][0].get(question) or {}).get("choice")
                    == expected
                    for i, c in enumerate(cases)
                    if source in (None, c["source"])
                    for q, expected in _checks(c)
                    if q == question
                ]
                cells.append(f"{sum(oks)}/{len(oks)}")
            if cells and cells[0] != "0/0":
                label = f"{source or 'all'} {question}"
                print(f"{label:<24}" + "".join(f" {x:>14}" for x in cells))

    def stat(fn, name):
        times = sorted(t for _, t, _ in results[name] if t == t)
        return fn(times) if times else float("nan")

    rows = [
        ("mean time (s)", lambda t: sum(t) / len(t)),
        ("median time (s)", lambda t: t[len(t) // 2]),
        ("p90 time (s)", lambda t: t[int(len(t) * 0.9)]),
        ("min time (s)", lambda t: t[0]),
        ("max time (s)", lambda t: t[-1]),
        ("total time (s)", sum),
    ]
    for label, fn in rows:
        print(
            f"{label:<24}" + "".join(f" {stat(fn, n):>14.2f}" for n in names)
        )
    costs = []
    for name in names:
        reported = [cost for _, _, cost in results[name] if cost is not None]
        costs.append(f"${sum(reported):.5f}" if reported else "-")
    print(f"{'total cost':<24}" + "".join(f" {x:>14}" for x in costs))

    if len(names) == 2:
        a, b = names
        disagree = sum(
            1
            for i, c in enumerate(cases)
            for q, _ in _checks(c)
            if not isinstance(results[a][i][0], str)
            and not isinstance(results[b][i][0], str)
            and (results[a][i][0].get(q) or {}).get("choice")
            != (results[b][i][0].get(q) or {}).get("choice")
        )
        print(f"{'answers that differ':<24} {disagree:>14}")


if __name__ == "__main__":
    main()
