"""The gnw CLI (cli/), run against the in-process MCP server.

The area lookup and the analytics handler are stubbed (conftest);
the pull.py each pull returns runs for real against the stub analytics API.
"""

import json
import sys
from pathlib import Path

import pytest

from src.mcp.server import mcp_server
from src.mcp.skill import SKILL_DIR
from tests.unit.mcp.analytics_stub import RESULT

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "cli" / "src"))

from gnw_cli.main import main  # noqa: E402

PULL = ["--aoi", "gadm:BRA.14_1", "--dataset", "4", "--start", "2020-01-01"]


def _gnw(capsys, *argv) -> tuple[str, str]:
    main(list(argv), server=mcp_server)
    captured = capsys.readouterr()
    return captured.out, captured.err


def _failing(capsys, *argv) -> str:
    with pytest.raises(SystemExit) as exit:
        main(list(argv), server=mcp_server)
    assert exit.value.code == 1
    return capsys.readouterr().err


def test_pull_writes_the_folder_and_prints_no_rows(
    replayable_pull, tmp_path, capsys
):
    out = tmp_path / "gnw"
    printed, errors = _gnw(capsys, "pull", *PULL, "--out", str(out))

    folder = out / "pulls" / "df747c81"
    assert errors == ""
    assert f"Rows: {folder / 'rows.csv'} (2 rows)" in printed
    assert (
        "Columns: aoi_id, aoi_type, tree_cover_loss_year, area_ha, name"
        in (printed)
    )
    assert f"Repeat: python {folder / 'pull.py'}" in printed
    assert "Citation: Hansen et al., 2013" in printed
    # The numbers are in the files, not on the terminal.
    assert "805620.12" not in printed
    assert "805620.12" in (folder / "rows.csv").read_text()
    for name in ("request.json", "provenance.json", "pull.py"):
        assert (folder / name).exists()

    [entry] = json.loads((out / "manifest.json").read_text())["entries"]
    assert entry["command"] == "pull"
    assert entry["arguments"]["aoi_ids"] == ["gadm:BRA.14_1"]
    assert entry["result_id"] == "df747c81"


def test_pull_json_gives_the_provenance(replayable_pull, tmp_path, capsys):
    printed, _ = _gnw(capsys, "pull", *PULL, "--out", str(tmp_path), "--json")
    provenance = json.loads(printed)
    assert provenance["result_id"] == "df747c81"
    assert provenance["folder"] == str(tmp_path / "pulls" / "df747c81")
    assert "rows" not in provenance and "script" not in provenance


def test_charts_writes_the_curated_specs(replayable_pull, tmp_path, capsys):
    printed, _ = _gnw(capsys, "charts", *PULL, "--out", str(tmp_path))

    folder = tmp_path / "pulls" / "df747c81"
    specs = json.loads((folder / "charts.json").read_text())
    assert specs["generator"]["name"] == "TCLChartGenerator"
    assert [chart["chart_type"] for chart in specs["charts"]] == ["bar", "bar"]
    assert "GNW's curated charts (TCLChartGenerator)" in printed
    assert (folder / "rows.csv").exists()


def test_replay_reports_pulls_whose_rows_changed(
    replayable_pull, api, tmp_path, capsys
):
    _gnw(capsys, "pull", *PULL, "--out", str(tmp_path))
    printed, _ = _gnw(capsys, "replay", "--out", str(tmp_path))
    assert printed.startswith("same")

    api.result = {**RESULT, "area_ha": [1.0, 2.0]}
    errors = _failing(capsys, "replay", "--out", str(tmp_path))
    assert "1 of 1 pulls did not repeat" in errors


def test_a_refused_pull_exits_with_the_servers_message(
    replayable_pull, capsys
):
    errors = _failing(
        capsys, "pull", "--aoi", "gadm:BRA.14_1", "--dataset", "999"
    )
    assert "gnw: No dataset 999." in errors


def test_skill_install_writes_both_skills(tmp_path, capsys):
    _gnw(capsys, "skill", "install", "--dir", str(tmp_path))

    assert (tmp_path / "gnw-charting" / "SKILL.md").read_text() == (
        SKILL_DIR / "SKILL.md"
    ).read_text()
    for name in ("tcl.py", "run.py", "_gnw.py", "column_types.json"):
        installed = tmp_path / "gnw-charting" / "generators" / name
        assert (
            installed.read_bytes()
            == (SKILL_DIR / "generators" / name).read_bytes()
        )
    assert not (tmp_path / "gnw-charting" / "_manifest").exists()
    assert (
        (tmp_path / "gnw-cli" / "SKILL.md")
        .read_text()
        .startswith("---\nname: gnw-cli\n")
    )
