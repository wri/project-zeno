"""`gold run --ids-file`: the ids of a file select the cases to run."""

import argparse
import sys
from pathlib import Path

import pytest

from goldset import cli

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases" / "v2"
SUBSET = ROOT / "cases" / "subsets" / "inner-loop.txt"


def _args(ids=None) -> argparse.Namespace:
    return argparse.Namespace(
        status_exclude="not doing", id=ids, group=None, cases_dir=CASES
    )


def test_read_ids_file_skips_comments_and_blank_lines(tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text(
        "# header\n\n1-002\n  1-004  # why\n   # indented comment\nmt-001\n"
    )
    assert cli.read_ids_file(path) == ["1-002", "1-004", "mt-001"]


def test_merge_ids_combines_without_duplicates(tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text("1-004\n1-002\n")
    assert cli.merge_ids(["1-002", "mt-001"], path) == ["1-002", "mt-001", "1-004"]
    assert cli.merge_ids(["1-002"], None) == ["1-002"]
    assert cli.merge_ids(None, path) == ["1-004", "1-002"]
    assert cli.merge_ids(None, None) is None


def test_select_cases_rejects_an_unknown_id():
    with pytest.raises(ValueError, match="1-999"):
        cli.select_cases(_args(["1-002", "1-999"]))


def test_subset_file_selects_exactly_its_cases():
    ids = cli.read_ids_file(SUBSET)
    assert len(ids) == 28
    assert len(set(ids)) == 28
    assert "1-033" not in ids
    assert "1-046" not in ids
    selected = cli.select_cases(_args(cli.merge_ids(None, SUBSET)))
    assert sorted(c.id for c in selected) == sorted(ids)


def _main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["gold", "run", "--cases-dir", str(CASES), *argv])
    return cli.main()


def test_dry_run_with_ids_file_and_id(monkeypatch, capsys, tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text("1-002\n")
    assert (
        _main(monkeypatch, "--dry-run", "--ids-file", str(path), "--id", "1-004") == 0
    )
    assert "2 cases selected (dry run)" in capsys.readouterr().out


def test_unknown_id_in_file_fails_before_any_api_call(monkeypatch, capsys, tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text("1-002\n1-999\n")
    # No --dry-run: if the check came late, the run would try the API.
    monkeypatch.setattr(
        cli, "load_dotenv", lambda *a, **k: pytest.fail("reached the API setup")
    )
    assert _main(monkeypatch, "--ids-file", str(path)) == 1
    assert "1-999" in capsys.readouterr().out


def test_missing_ids_file_fails(monkeypatch, capsys, tmp_path):
    assert _main(monkeypatch, "--dry-run", "--ids-file", str(tmp_path / "no.txt")) == 1
    assert "error" in capsys.readouterr().out
