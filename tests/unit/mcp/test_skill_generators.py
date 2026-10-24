"""The skill's generators run outside zeno and draw what zeno draws.

generators/run.py runs in its own Python on a rows.csv for each dataset,
and its charts must equal zeno's build_curated_charts in English. The rows
are real: the analytics API's answer for Brazil in each dataset's last
year, cut to 40 rows (fixtures/sample_rows.json).
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.api.services.charts.curated import build_curated_charts
from src.mcp.data import rows_csv
from src.mcp.skill import SKILL_DIR

SAMPLES = json.loads(
    (Path(__file__).parent / "fixtures" / "sample_rows.json").read_text(
        encoding="utf-8"
    )
)
RUN = SKILL_DIR / "generators" / "run.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, "-I", str(RUN), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("dataset_id", sorted(SAMPLES, key=int))
async def test_run_draws_the_charts_zeno_draws(dataset_id, tmp_path):
    rows = SAMPLES[dataset_id]
    path = tmp_path / "rows.csv"
    path.write_text(rows_csv(rows) + "\n", encoding="utf-8")

    run = _run(dataset_id, str(path))

    assert run.returncode == 0, run.stderr
    expected = await build_curated_charts(
        int(dataset_id), copy.deepcopy(rows), "en"
    )
    assert expected, "the sample draws no chart"
    assert json.loads(run.stdout) == [
        chart.model_dump(exclude={"insight"}) for chart in expected
    ]


def test_run_refuses_a_dataset_without_curated_charts(tmp_path):
    path = tmp_path / "rows.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    run = _run("12", str(path))
    assert run.returncode != 0
    assert "no curated charts for dataset 12" in run.stderr
