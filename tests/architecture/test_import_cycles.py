import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "src" / "agent" / "tools"

IMPORT_EACH_FROM_SCRATCH = """
import importlib, json, sys

failed = {}
for module in sys.argv[1:]:
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]
    try:
        importlib.import_module(module)
    except Exception as error:
        failed[module] = f"{type(error).__name__}: {error}"
print(json.dumps(failed))
"""


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(REPO).with_suffix("").parts)


def test_agent_tool_modules_import_in_a_fresh_interpreter():
    modules = [
        module_name(path)
        for path in sorted(TOOLS.glob("*.py"))
        if path.stem != "__init__"
    ]

    result = subprocess.run(
        [sys.executable, "-c", IMPORT_EACH_FROM_SCRATCH, *modules],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
