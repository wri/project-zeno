"""Dataset tools: the catalog, read straight from the YAML the agent uses.

The server offers what zeno's default agent profile offers: the datasets in
`DEFAULT_EXCLUDED_DATASETS` (LGMS) are hidden here as well. LGMS is also the
one analytics endpoint that refuses a call without a token.
"""

from typing import Annotated, Optional

from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from src.agent.agent_config import DEFAULT_EXCLUDED_DATASETS
from src.agent.datasets.config import DATASETS
from src.agent.datasets.palette import get_dataset_palette

MCP_EXCLUDED_DATASETS = DEFAULT_EXCLUDED_DATASETS

# Catalog fields a client gets from get_dataset, in the order the text shows
# them. The rest of the YAML is agent prompt text (selection hints, prompt
# and function notes) or map plumbing (tile URLs).
_DETAIL_FIELDS = (
    ("description", "Description"),
    ("content_date", "Content date"),
    ("geographic_coverage", "Geographic coverage"),
    ("resolution", "Resolution"),
    ("update_frequency", "Update frequency"),
    ("cautions", "Cautions"),
    ("methodology", "Methodology"),
    ("presentation_instructions", "How to present it"),
    ("code_instructions", "How to chart it"),
    ("citation", "Citation"),
    ("license", "License"),
)


def available_datasets() -> list[dict]:
    """The catalog entries this server offers, by dataset id."""
    return [
        ds
        for ds in DATASETS
        if ds["dataset_name"] not in MCP_EXCLUDED_DATASETS
    ]


def get_catalog_dataset(dataset_id: int) -> dict:
    """The catalog entry for `dataset_id`; raises ToolError for an unknown
    or hidden one, listing the ids that exist."""
    for ds in available_datasets():
        if ds["dataset_id"] == dataset_id:
            return ds
    ids = ", ".join(str(ds["dataset_id"]) for ds in available_datasets())
    raise ToolError(
        f"No dataset {dataset_id}. Available dataset ids: {ids}. "
        "See list_datasets."
    )


def _card(ds: dict) -> str:
    """The short description: the selection card when the dataset has one,
    else its selection hints."""
    return str(ds.get("selection_card") or ds.get("selection_hints") or "")


def _text(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _context_layers(ds: dict) -> list[dict]:
    return [
        {
            "value": layer["value"],
            "description": _text(layer.get("description")),
            "start_date": layer.get("start_date"),
        }
        for layer in ds.get("context_layers") or []
    ]


def _parameters(ds: dict) -> list[dict]:
    return [
        {
            "name": param["name"],
            "description": _text(param.get("description")),
            "values": list(param.get("values") or []),
        }
        for param in ds.get("parameters") or []
    ]


def _summary(ds: dict) -> dict:
    return {
        "dataset_id": ds["dataset_id"],
        "dataset_name": ds["dataset_name"],
        "card": _card(ds),
        "start_date": ds.get("start_date"),
        "end_date": ds.get("end_date"),
        "context_layers": [
            layer["value"] for layer in ds.get("context_layers") or []
        ],
        "parameters": [param["name"] for param in ds.get("parameters") or []],
    }


async def list_datasets() -> ToolResult:
    """List the datasets you can pull, with a short description of each.

    Choose the dataset that measures what the user asks about, then read
    its details with get_dataset before pulling: the details say which
    context layers and parameters it takes, and its cautions.
    """
    summaries = [_summary(ds) for ds in available_datasets()]
    lines = []
    for summary in summaries:
        options = []
        if summary["context_layers"]:
            options.append(
                "context layers: " + ", ".join(summary["context_layers"])
            )
        if summary["parameters"]:
            options.append("parameters: " + ", ".join(summary["parameters"]))
        suffix = f" [{'; '.join(options)}]" if options else ""
        lines.append(
            f"- {summary['dataset_id']}: {summary['dataset_name']}. "
            f"{summary['card']}{suffix}"
        )
    return ToolResult(
        content="Datasets (id: name. description):\n" + "\n".join(lines),
        structured_content={"datasets": summaries},
    )


async def get_dataset(
    dataset_id: Annotated[
        int, Field(description="The dataset id from list_datasets.")
    ],
) -> ToolResult:
    """Read one dataset's details: what it measures, its date coverage,
    the context layers and parameters pull_data accepts for it, its
    cautions, how to present and chart it, its colors and its citation.
    """
    ds = get_catalog_dataset(dataset_id)
    details = {
        **_summary(ds),
        **{key: _text(ds.get(key)) for key, _ in _DETAIL_FIELDS},
        "context_layers": _context_layers(ds),
        "parameters": _parameters(ds),
        "colors": _colors(ds["dataset_id"]),
    }

    sections = [
        f"# {ds['dataset_name']} (dataset {ds['dataset_id']})",
        details["card"],
        f"Dates: {ds.get('start_date')} to {ds.get('end_date') or 'today'}",
    ]
    for key, label in _DETAIL_FIELDS:
        if details[key]:
            sections.append(f"## {label}\n{details[key]}")
    if details["context_layers"]:
        sections.append(
            "## Context layers (pull_data context_layer)\n"
            + "\n".join(
                f"- {layer['value']}: {layer['description']}"
                for layer in details["context_layers"]
            )
        )
    if details["parameters"]:
        sections.append(
            "## Parameters\n"
            + "\n".join(
                f"- {param['name']} (one of {param['values']}): "
                f"{param['description']}"
                for param in details["parameters"]
            )
        )
    if details["colors"]:
        sections.append(_colors_text(details["colors"]))
    return ToolResult(
        content="\n\n".join(sections), structured_content=details
    )


def _colors(dataset_id: int) -> Optional[dict]:
    """The dataset's chart colors from the catalog palette, the same ones
    zeno's charts and map legends use."""
    palette = get_dataset_palette(dataset_id)
    if not palette:
        return None
    return {
        "categories": [dict(category) for category in palette["categories"]],
        "series_color": palette["series_color"],
        "divergent_colors": (
            dict(palette["divergent_colors"])
            if palette["divergent_colors"]
            else None
        ),
    }


def _colors_text(colors: dict) -> str:
    lines = ["## Colors (use these, do not invent others)"]
    if colors["series_color"]:
        lines.append(f"- single series: {colors['series_color']}")
    if colors["divergent_colors"]:
        lines.append(
            "- positive / negative: "
            + ", ".join(
                f"{key} {value}"
                for key, value in colors["divergent_colors"].items()
            )
        )
    for category in colors["categories"]:
        lines.append(
            f"- {category['label_en']} ({category['slug']}): "
            f"{category['color']}"
        )
    return "\n".join(lines)
