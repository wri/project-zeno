"""The `gnw-charting` skill: how GNW charts and words each dataset.

The skill is made from what zeno already holds: the catalog's charting and
presentation guidance, cautions and colors, the curated chart generators and
their source, and the analyst's wording guide. It is checked in under
`src/mcp/skills/gnw-charting/` so it can be read and reviewed, copied into a
Claude or Gemini skills folder, and served by the MCP server. A unit test
fails when the checked-in files no longer match the sources; rebuild with

    uv run python -m src.mcp.skill
"""

import difflib
import inspect
import json
import re
import shutil
import sys
from pathlib import Path

from src.agent.datasets.handlers import analytics_handler
from src.agent.i18n import MESSAGES
from src.agent.subagents.analyst.code_executors.base import CHART_TYPES
from src.agent.subagents.analyst.prompts import WORDING_GUIDE
from src.api.services.charts import base as chart_base
from src.api.services.charts.base import ChartGenerator
from src.mcp.charts import find_generator, generator_info
from src.mcp.columns import COLUMN_NOTES, unit_of
from src.mcp.columns import load as load_columns
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
    "code, the columns of each dataset's rows, and how to keep an analysis "
    "repeatable. Use when analysing, charting, summarising or presenting "
    "data from the GNW MCP server (pull_data, curated_charts) or the gnw "
    "CLI."
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
   filters, sorts and sums the same rows, and
   `python generators/run.py <dataset_id> rows.csv` runs GNW's generator on
   a pull's rows outside GNW (it needs numpy): the curated charts, made in
   your own analysis.
3. **Present it** as the dataset's "How to present it" says, with the
   wording guide below, the cautions that apply, and the citation.

## Repeatable analysis

Every pull comes with what it takes to repeat it: `pull_data` and
`curated_charts` return the request sent to the analytics API, the pull's
provenance, and `script`, a standalone `pull.py` (Python 3.9+, no packages)
that fetches the same rows into `gnw/pulls/<result_id>/rows.csv`. The `gnw`
CLI writes these files itself.

- **When you can run code, analyse in code.** Run `pull.py` (or `gnw pull`)
  and compute every number you report from `rows.csv`: totals, changes,
  shares, rankings. Each dataset's file lists its columns, types and units,
  so you can write the code before you see the rows.
- **Keep it in one script** that starts from the pulls' `rows.csv` files and
  draws the charts too, so `python pull.py` then `python analysis.py`
  repeats the whole result.
- **Never copy numbers** from a tool result into code or into the answer as
  data; read them from the files.
- **End the answer with** what was pulled (dataset, areas, dates and
  options, including a date range the server fitted to the dataset), how to
  repeat it (the scripts or commands, in order), the cautions that apply,
  and the citation with the access date filled in.
- **Without code** (in a chat), quote only numbers a tool returned, and
  point the user to the result's Reproduce panel, which holds `pull.py`.

`pull.py` warns when the rows it fetches differ from the ones first pulled
(`rows_sha256`): the data was updated since.

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


def _lower_first(text: str) -> str:
    text = text.rstrip(".")
    return text[:1].lower() + text[1:]


def _variant_label(name: str) -> str:
    if name.startswith("context_layer="):
        return f"With context layer `{name.removeprefix('context_layer=')}`"
    return f"With `{name}`"


def _columns_section(ds: dict) -> str:
    """The columns of the dataset's rows, as the analytics API returned
    them, and how its context layers and options change them."""
    variants = load_columns().get(str(ds["dataset_id"])) or {}
    default = variants.get("default", {}).get("columns")
    if not default:
        return ""
    lines = [
        "The columns of `rows.csv` and of `pull_data`'s rows, as the GNW "
        "analytics API returns them.\n",
        "| Column | Type | Unit | Holds |",
        "|---|---|---|---|",
    ]
    for column, kind in default.items():
        lines.append(
            f"| `{column}` | {kind if kind != 'null' else ''} | "
            f"{unit_of(column)} | {COLUMN_NOTES.get(column, '')} |"
        )
    notes = []
    for name, variant in variants.items():
        columns = variant.get("columns")
        if name == "default" or columns is None:
            continue
        changes = []
        added = [c for c in columns if c not in default]
        missing = [c for c in default if c not in columns]
        empty = [
            c
            for c, kind in columns.items()
            if kind == "null" and default.get(c) not in (None, "null")
        ]
        if added:
            changes.append(
                "adds "
                + ", ".join(
                    f"`{c}` ({_lower_first(COLUMN_NOTES.get(c, columns[c]))})"
                    for c in added
                )
            )
        if missing:
            changes.append("drops " + ", ".join(f"`{c}`" for c in missing))
        if empty:
            changes.append(
                ", ".join(f"`{c}`" for c in empty) + " can be empty"
            )
        if changes:
            notes.append(f"- {_variant_label(name)}: {'; '.join(changes)}.")
    if notes:
        lines += ["", *notes]
    return _section("Columns", "\n".join(lines))


def _column_names(ds: dict) -> set[str]:
    variants = load_columns().get(str(ds["dataset_id"])) or {}
    return {
        column
        for variant in variants.values()
        for column in variant.get("columns") or {}
    }


def _misnamed_columns(ds: dict, text: str) -> list[tuple[str, str]]:
    """(name in the rules, name in the rows) for each snake_case name the
    rules use that the rows spell differently, e.g. emissions_tco2e for
    emissions_tCO2e. Names with no close column are left alone: they are
    options or words, not columns."""
    columns = _column_names(ds)
    by_lower = {column.lower(): column for column in columns}
    options = {layer["value"] for layer in _context_layers(ds)} | {
        param["name"] for param in _parameters(ds)
    }
    found = []
    for name in sorted(set(_SNAKE.findall(text)) - columns - options):
        match = difflib.get_close_matches(
            name.lower(), by_lower, n=1, cutoff=0.8
        )
        if match:
            found.append((name, by_lower[match[0]]))
    return found


_SNAKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")


def _chart_rules(ds: dict) -> str:
    """The catalog's charting rules, with a word on the terms of GNW's own
    chart code they use and on column names the rows spell differently."""
    rules = str(ds.get("code_instructions") or "").strip()
    if not rules:
        return ""
    reading = []
    if "REFUSE" in rules or "refuse" in rules:
        reading.append(
            "where they say REFUSE, decline that request and say why"
        )
    if "chart_data" in rules:
        reading.append("`chart_data.csv` is the data of your chart")
    if "insight" in rules:
        reading.append('"the insight" is your answer')
    lines = [
        "GNW's rules for this dataset, written for the code that draws GNW's "
        "own charts" + (f": {'; '.join(reading)}." if reading else ".")
    ]
    misnamed = _misnamed_columns(
        ds, rules + " " + str(ds.get("presentation_instructions") or "")
    )
    if misnamed:
        lines.append(
            "The rows name some columns differently from these rules: "
            + ", ".join(f"`{rule}` is `{row}`" for rule, row in misnamed)
            + "."
        )
    return "\n\n".join([*lines, rules])


def _generator_file(generator: ChartGenerator) -> str:
    return Path(generator_info(generator)["path"]).name


def _dataset_file(ds: dict) -> str:
    generator = find_generator(ds["dataset_id"])
    lines = [
        f"# {ds['dataset_name']} (dataset {ds['dataset_id']})\n",
        f"{str(ds.get('selection_card') or '').strip()}\n",
        f"Dates: {ds.get('start_date')} to {ds.get('end_date') or 'today'}.\n",
        _columns_section(ds),
    ]
    if generator is not None:
        info = generator_info(generator)
        lines.append(
            _section(
                "Curated charts",
                f"`curated_charts` draws these with `{info['name']}` "
                f"([generators/{_generator_file(generator)}]"
                f"(../generators/{_generator_file(generator)})).\n\n"
                f"{info['description']}\n\n"
                "Run it on a pull's rows: `python generators/run.py "
                f"{ds['dataset_id']} gnw/pulls/<result_id>/rows.csv charts.json`.",
            )
        )
    lines += [
        _section("How to chart it", _chart_rules(ds)),
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


# Imports of a generator, and what they become in the skill's copy.
_IMPORTS = {
    "from src.agent.datasets.handlers.analytics_handler import": "from _gnw import",
    "from src.agent.subagents.analyst.charts import": "from _gnw import",
    "from src.api.services.charts.base import": "from base import",
}
_ZENO_IMPORT = re.compile(r"^\s*(from|import) src\b", re.MULTILINE)
SKILL_FILES = Path(__file__).parent / "skill_files"

_GNW = '''"""Stand-ins for the zeno modules GNW's chart generators import, so the
generators in this folder run outside zeno: InsightChart (the chart spec),
the dataset ids, and the English chart titles and labels. Written by
src/mcp/skill.py from zeno's own definitions; do not edit.
"""

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

{ids}

# Message key -> English text, from zeno's src/agent/i18n.py.
MESSAGES = {messages}


def _json_safe(value):
    """NaN and Inf as None, as zeno's InsightChart stores them."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {{key: _json_safe(item) for key, item in value.items()}}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class InsightChart:
    """A chart spec and the rows it draws: zeno's InsightChart."""

    title: str
    chart_type: str
    position: int = 0
    x_axis: str = ""
    y_axis: str = ""
    color_field: str = ""
    stack_field: str = ""
    group_field: str = ""
    series_fields: List[str] = field(default_factory=list)
    chart_data: List[dict] = field(default_factory=list)
    insight: str = ""
    dataset_id: Optional[int] = None
    color_map: Dict[str, str] = field(default_factory=dict)
    series_color: Optional[str] = None
    divergent_colors: Optional[Dict[str, str]] = None

    def __post_init__(self):
        self.chart_data = [_json_safe(row) for row in self.chart_data]

    def model_dump(self, exclude=()):
        return {{
            key: value
            for key, value in asdict(self).items()
            if key not in exclude
        }}


def text(key):
    """A message key's English text; the key itself when it has none."""
    return MESSAGES.get(key) or key


def localise(charts, generator):
    """Message keys to English text, as zeno's curated.py does."""
    for chart in charts:
        chart.title = text(chart.title)
        for column in generator.label_fields:
            for row in chart.chart_data:
                if column in row:
                    row[column] = text(row[column])
        if generator.label_series:
            names = {{key: text(key) for key in chart.series_fields}}
            if len(set(names.values())) != len(names):
                raise ValueError(f"Series names are not unique: {{names}}")
            chart.series_fields = [names[key] for key in chart.series_fields]
            chart.chart_data = [
                {{names.get(key, key): value for key, value in row.items()}}
                for row in chart.chart_data
            ]
            chart.color_map = {{
                names.get(key, key): color
                for key, color in chart.color_map.items()
            }}
'''


def _runnable(source: str, name: str) -> str:
    """A generator's source with its zeno imports pointed at _gnw.py and
    base.py; fails the build when an import has no stand-in."""
    for zeno, local in _IMPORTS.items():
        source = source.replace(zeno, local)
    if _ZENO_IMPORT.search(source):
        raise ValueError(
            f"{name} imports a zeno module with no stand-in in _gnw.py."
        )
    return source


def _gnw_module() -> str:
    ids = "\n".join(
        f"{name} = {value}"
        for name, value in sorted(vars(analytics_handler).items())
        if name.endswith("_ID") and isinstance(value, int)
    )
    messages = {
        key: templates["en"].format()
        for key, templates in MESSAGES.items()
        if key.startswith("charts.")
    }
    return _GNW.format(
        ids=ids, messages=json.dumps(messages, indent=4, ensure_ascii=False)
    )


def _column_types() -> str:
    """Each dataset's columns and their types, for run.py to read rows.csv."""
    types = {
        dataset_id: {
            column: kind
            for variant in variants.values()
            for column, kind in (variant.get("columns") or {}).items()
            if kind != "null"
        }
        for dataset_id, variants in load_columns().items()
    }
    return json.dumps(types, indent=2, ensure_ascii=False) + "\n"


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
            files[f"generators/{_generator_file(generator)}"] = _runnable(
                inspect.getsource(module), _generator_file(generator)
            )
        rows.append(
            f"| {ds['dataset_id']} | {ds['dataset_name']} | "
            f"{'yes' if generator else 'no'} | [{name}]({name}) |"
        )
    files["generators/base.py"] = _runnable(
        inspect.getsource(chart_base), "base.py"
    )
    files["generators/_gnw.py"] = _gnw_module()
    files["generators/column_types.json"] = _column_types()
    files["generators/run.py"] = (SKILL_FILES / "run.py").read_text(
        encoding="utf-8"
    )

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
