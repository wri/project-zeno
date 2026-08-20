"""Tests for the ``build-aois`` argument guards.

``--prune`` deletes rows, so the command rejects a combination that cannot
prune. Both guards raise before ``asyncio.run``, so these tests need no
database and no ``DatabaseManager``. The transform itself needs the
``geometries_*`` tables, which the test database does not have, so it stays
uncovered here.
"""

from click.testing import CliRunner

from src.api.cli import cli


def test_prune_needs_the_custom_source():
    result = CliRunner().invoke(
        cli, ["build-aois", "--source", "gadm", "--prune"]
    )

    assert result.exit_code == 2
    assert "--prune needs the custom source" in result.output


def test_prune_rejects_inspect():
    result = CliRunner().invoke(cli, ["build-aois", "--prune", "--inspect"])

    assert result.exit_code == 2
    assert "--prune cannot run with --inspect" in result.output
