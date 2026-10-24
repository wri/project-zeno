"""Draw GNW's curated charts from a pull's rows, with GNW's own chart code.

    python generators/run.py <dataset_id> gnw/pulls/<result_id>/rows.csv [charts.json]

The generators in this folder are the ones the GNW MCP server's
curated_charts runs, with their imports pointed at _gnw.py instead of
zeno. This prints the charts as JSON, or writes them to the file you name:
one object per chart, with its title, type, axes and rows, as
curated_charts returns them before it adds the catalog colors (the
dataset's file in the skill lists those). Needs Python 3.10+ and numpy.
"""

import csv
import importlib
import inspect
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# Leave no __pycache__ in the skill folder.
sys.dont_write_bytecode = True

try:
    import numpy  # noqa: F401 (base.py and some generators use it)
except ImportError:
    sys.exit("run.py needs numpy: pip install numpy")

from _gnw import localise  # noqa: E402
from base import ChartGenerator  # noqa: E402

_NUMBER = re.compile(r"-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def generators() -> list:
    """An instance of every generator in this folder."""
    found = []
    for path in sorted(HERE.glob("*.py")):
        if path.stem in ("run", "_gnw", "base"):
            continue
        module = importlib.import_module(path.stem)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(cls, ChartGenerator)
                and cls.__module__ == module.__name__
                and not inspect.isabstract(cls)
            ):
                found.append(cls())
    return found


def _value(text, kind):
    """A CSV cell as the type the analytics API gave the column."""
    if text == "":
        return None
    if kind == "integer":
        return int(text)
    if kind == "number":
        return float(text)
    if kind is None and _NUMBER.fullmatch(text):
        return float(text) if any(c in text for c in ".eE") else int(text)
    return text


def read_rows(path, dataset_id: int) -> list:
    types = json.loads(
        (HERE / "column_types.json").read_text(encoding="utf-8")
    )
    kinds = types.get(str(dataset_id), {})
    with open(path, newline="", encoding="utf-8") as file:
        return [
            {
                column: _value(text, kinds.get(column))
                for column, text in row.items()
            }
            for row in csv.DictReader(file)
        ]


def curated_charts(dataset_id: int, rows: list) -> list:
    for generator in generators():
        if generator.can_handle(dataset_id):
            charts = generator.generate(rows)
            localise(charts, generator)
            for chart in charts:
                chart.dataset_id = dataset_id
            return [chart.model_dump(exclude={"insight"}) for chart in charts]
    sys.exit(f"GNW has no curated charts for dataset {dataset_id}.")


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    dataset_id = int(sys.argv[1])
    charts = curated_charts(dataset_id, read_rows(sys.argv[2], dataset_id))
    text = json.dumps(charts, indent=2, ensure_ascii=False)
    if len(sys.argv) == 4:
        Path(sys.argv[3]).write_text(text + "\n", encoding="utf-8")
        print(f"{len(charts)} charts written to {sys.argv[3]}")
    else:
        print(text)


if __name__ == "__main__":
    main()
