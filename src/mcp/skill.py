"""The `gnw-charting` skill: how GNW charts and words each dataset.

The skill is made from what zeno already holds: the catalog's charting and
presentation guidance, cautions and colors, the curated chart generators and
their source, and the analyst's wording guide. It is checked in under
`src/mcp/skills/gnw-charting/` so it can be read and reviewed, copied into a
Claude or Gemini skills folder, and served by the MCP server. A unit test
fails when the checked-in files no longer match the sources; rebuild with

    uv run python -m src.mcp.skill
"""

import inspect
import re
import shutil
import sys
from pathlib import Path

from src.agent.subagents.analyst.code_executors.base import CHART_TYPES
from src.agent.subagents.analyst.prompts import WORDING_GUIDE
from src.api.services.charts import base as chart_base
from src.api.services.charts.base import ChartGenerator
from src.mcp.charts import find_generator, generator_info
from src.mcp.datasets import (
    _colors,
    _colors_text,
    _context_layers,
    _parameters,
    available_datasets,
)

SKILL_NAME = "gnw-charting"
SKILL_DIR = Path(__file__).parent / "skills" / SKILL_NAME

_DESCRIPTION = (
    "Chart and describe Global Nature Watch (GNW) data the way GNW does: "
    "which chart to draw for each dataset, its colors, the wording to use "
    "and avoid, its cautions and citation, and GNW's own curated chart "
    "code. Use when charting, summarising or presenting data from the GNW "
    "MCP server (pull_data, curated_charts)."
)

_SKILL_BODY = """\
# Charting GNW data

Data from the Global Nature Watch MCP server comes with rules: each dataset
has a way GNW charts it, colors it, and words it, and cautions a reader must
see. This skill holds those rules, one file per dataset, made from GNW's
catalog and chart code.

## Workflow

1. **Prefer the curated charts.** `curated_charts` returns the charts GNW
   itself shows for a dataset, drawn by code GNW maintains, with their data
   and colors. When the user wants the standard view of a dataset, render
   those specs as they are, keep their titles, and say they are GNW's
   charts.
2. **Draw your own** when the question needs another view (a comparison, a
   subset, a different breakdown). Read the dataset's file below first: its
   "How to chart it" rules are GNW's, and they override the general advice
   here. The dataset's curated generator (in `generators/`) shows how GNW
   filters, sorts and sums the same rows.
3. **Present it** as the dataset's "How to present it" says, with the
   wording guide below, the cautions that apply, and the citation.

## Rules for every chart

- Chart only numbers a tool returned. Never fill in a missing year or area.
- Use the dataset's colors (in its file, or from `get_dataset`). A chart with
  one series takes the series color; categories take their category colors.
  Do not invent colors for categories the palette lists.
- One metric per chart: area and emissions, or area and counts, go in
  separate charts. A title names only the metric(s) plotted, the area and
  the period, e.g. "Annual Tree Cover Loss in Pará (2018-2023)".
- Give units on the axis or in the title (ha, MgCO2e).
- State the options the pull ran with: the canopy cover threshold, the
  context layer, and any date range the server fitted to the dataset.
- Sort a time series by date and a ranking by value.
- Keep a pie to 6-8 slices; group the rest as "Other".

## Chart types

GNW renders these types: {chart_types}. Use the same names when you hand a
chart to GNW, in the `InsightChart` shape the curated charts come in
(`chart_type`, `x_axis`, `y_axis`, `color_field`, `series_fields`,
`chart_data`, `color_map`, `series_color`).

- **line**: a time series or trend; several series in wide format.
- **bar**: comparisons and rankings, and annual totals.
- **stacked-bar**: composition within each category or year.
- **grouped-bar**: several metrics side by side, in long format.
- **pie**: part of a whole.
- **area**: cumulative or stacked time series.
- **scatter**: two variables against each other.
- **table**: detail that a chart would not show well, such as transitions.

{wording}
## Datasets

| Id | Dataset | Curated charts | File |
|---|---|---|---|
{dataset_rows}

`generators/base.py` holds the helpers the generators share.
"""


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _section(title: str, text) -> str:
    text = str(text or "").strip()
    return f"## {title}\n\n{text}\n" if text else ""


def _generator_file(generator: ChartGenerator) -> str:
    return Path(generator_info(generator)["path"]).name


def _dataset_file(ds: dict) -> str:
    generator = find_generator(ds["dataset_id"])
    lines = [
        f"# {ds['dataset_name']} (dataset {ds['dataset_id']})\n",
        f"{str(ds.get('selection_card') or '').strip()}\n",
        f"Dates: {ds.get('start_date')} to {ds.get('end_date') or 'today'}.\n",
    ]
    if generator is not None:
        info = generator_info(generator)
        lines.append(
            _section(
                "Curated charts",
                f"`curated_charts` draws these with `{info['name']}` "
                f"([generators/{_generator_file(generator)}]"
                f"(../generators/{_generator_file(generator)})).\n\n"
                f"{info['description']}",
            )
        )
    lines += [
        _section("How to chart it", ds.get("code_instructions")),
        _section("How to present it", ds.get("presentation_instructions")),
        _section("Cautions", ds.get("cautions")),
    ]
    options = [
        f"- context layer `{layer['value']}`: {layer['description']}"
        for layer in _context_layers(ds)
    ] + [
        f"- `{param['name']}`, one of {param['values']}: "
        f"{param['description']}"
        for param in _parameters(ds)
    ]
    if options:
        lines.append(_section("Options (pull_data)", "\n".join(options)))
    colors = _colors(ds["dataset_id"])
    if colors:
        lines.append(_colors_text(colors) + "\n")
    lines.append(_section("Citation", ds.get("citation")))
    return "\n".join(line for line in lines if line).rstrip() + "\n"


def build_skill() -> dict[str, str]:
    """The skill's files, by path inside the skill folder."""
    files: dict[str, str] = {}
    rows = []
    for ds in available_datasets():
        name = (
            f"datasets/{ds['dataset_id']:02d}-{_slug(ds['dataset_name'])}.md"
        )
        files[name] = _dataset_file(ds)
        generator = find_generator(ds["dataset_id"])
        if generator is not None:
            module = sys.modules[type(generator).__module__]
            files[f"generators/{_generator_file(generator)}"] = (
                inspect.getsource(module)
            )
        rows.append(
            f"| {ds['dataset_id']} | {ds['dataset_name']} | "
            f"{'yes' if generator else 'no'} | [{name}]({name}) |"
        )
    files["generators/base.py"] = inspect.getsource(chart_base)

    frontmatter = (
        f"---\nname: {SKILL_NAME}\ndescription: {_DESCRIPTION}\n---\n\n"
    )
    files["SKILL.md"] = frontmatter + _SKILL_BODY.format(
        chart_types=", ".join(f"`{t}`" for t in CHART_TYPES),
        wording=WORDING_GUIDE.replace("# Wording", "## Wording", 1).strip()
        + "\n",
        dataset_rows="\n".join(rows),
    )
    return files


def write_skill(directory: Path = SKILL_DIR) -> None:
    if directory.exists():
        shutil.rmtree(directory)
    for path, text in build_skill().items():
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    write_skill()
    print(f"Wrote {SKILL_DIR}")
