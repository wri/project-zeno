"""Tests for the subprocess sandbox code executor.

Functional tests run everywhere. The security tests assert that the seccomp
syscall filter actually blocks network / exec / file access, so they are skipped
where seccomp is unavailable (non-Linux or pyseccomp missing).
"""

import importlib.util
import os
import sys

import pandas as pd
import pytest

from src.agent.subagents.analyst.code_executors.subprocess_executor import (
    _SubprocessRunner,
)

pytestmark = pytest.mark.asyncio

_SECCOMP_AVAILABLE = sys.platform.startswith("linux") and (
    importlib.util.find_spec("pyseccomp") is not None
)
requires_seccomp = pytest.mark.skipif(
    not _SECCOMP_AVAILABLE, reason="seccomp (pyseccomp on Linux) not available"
)

_INSIGHT = (
    'insight = {"charts": [{"title": "t", "chart_type": "bar", '
    '"x_axis": "a", "y_axis": "a"}], "primary_insight": "p", '
    '"follow_up_suggestions": ["f"]}'
)


async def _run(code: str, *, strict: bool = False, seccomp: bool = True):
    runner = _SubprocessRunner(
        timeout_seconds=20, seccomp=seccomp, strict=strict
    )
    await runner.start({"input_file_0": pd.DataFrame({"a": [1, 2, 3]})})
    try:
        return await runner.run_block(code), runner
    finally:
        await runner.close()


async def test_functional_compute_and_results():
    (output, chart, insight), runner = await _run(
        'print("sum =", int(input_file_0["a"].sum()))\n'
        'chart_data = [{"a": 1}]\n' + _INSIGHT
    )
    assert "sum = 6" in output
    assert chart == [{"a": 1}]
    assert insight is not None and "charts" in insight


async def test_environment_is_scrubbed_of_secrets():
    """The parent's secrets must not exist in the sandbox process env."""
    os.environ["ZENO_SANDBOX_SECRET"] = "leak-me-please"
    try:
        (output, _, _), _ = await _run(
            'import os; print("LEAK:", '
            'repr(os.environ.get("ZENO_SANDBOX_SECRET")))'
        )
    finally:
        del os.environ["ZENO_SANDBOX_SECRET"]
    assert "leak-me-please" not in output
    assert "LEAK: None" in output


@requires_seccomp
async def test_network_egress_blocked():
    (output, _, _), _ = await _run(
        "import socket\n"
        "s = socket.socket(); s.settimeout(3)\n"
        's.connect(("1.1.1.1", 80))\n'
        'print("CONNECTED-SHOULD-NOT-HAPPEN")'
    )
    assert "CONNECTED-SHOULD-NOT-HAPPEN" not in output
    assert "Error" in output or "Traceback" in output


@requires_seccomp
async def test_exec_blocked():
    (output, _, _), _ = await _run(
        'import os; os.system("echo PWNED-SHOULD-NOT-RUN")'
    )
    assert "PWNED-SHOULD-NOT-RUN" not in output


@requires_seccomp
async def test_strict_mode_blocks_file_reads():
    (output, _, _), _ = await _run(
        'print(open("/etc/hostname").read())', strict=True
    )
    # strict mode blocks open()/openat() → reading raises
    assert "Traceback" in output or "Error" in output


async def test_session_survives_failed_block():
    """A failing block must not kill the session; later blocks still work."""
    runner = _SubprocessRunner(timeout_seconds=20, seccomp=True, strict=False)
    await runner.start({"input_file_0": pd.DataFrame({"a": [1]})})
    try:
        bad, _, _ = await runner.run_block('raise ValueError("boom")')
        assert "boom" in bad
        out, chart, _ = await runner.run_block(
            'chart_data = [{"a": 1}]\nprint("recovered")'
        )
        assert "recovered" in out
        assert chart == [{"a": 1}]
    finally:
        await runner.close()
