"""Keep prompt growth visible in review.

``prompt_size_snapshot.json`` holds the character count of every part of the
static prompt: each profile's system prompt and tool schemas, each skill body
and each dataset's model-instruction fields. This test compares the current
sizes with the snapshot.

Why a tolerance snapshot and not an exact snapshot or a fixed budget:

- An exact snapshot fails on every wording fix, so people learn to regenerate
  it without looking.
- A fixed budget hides slow growth until the day it fails, and it does not
  show a shrink.
- A snapshot with a tolerance (2 percent, at least 100 characters) ignores
  small edits. A change that moves a part by more than that fails, in both
  directions. The fix is to regenerate the file, and the diff of the JSON in
  the PR shows which part grew or shrank, and by how much. A shrink must also
  be regenerated, so the new lower size becomes the reference.

A new or removed profile, tool, skill, dataset or field fails at once.

To regenerate after an intended change:

    uv run python scripts/prompt_size.py --write-snapshot

The system prompt embeds today's date as ``YYYY-MM-DD``. The length of that
string never changes, so the size is stable from day to day.
"""

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = Path(__file__).with_name("prompt_size_snapshot.json")
REGENERATE = "uv run python scripts/prompt_size.py --write-snapshot"
REL_TOLERANCE = 0.02
ABS_TOLERANCE = 100


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "prompt_size", REPO_ROOT / "scripts" / "prompt_size.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _leaves(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{prefix}/{key}")
    else:
        yield prefix, node


def _allowed(reference: int) -> float:
    return max(ABS_TOLERANCE, REL_TOLERANCE * reference)


def test_prompt_sizes_match_the_snapshot():
    expected = dict(_leaves(json.loads(SNAPSHOT.read_text(encoding="utf-8"))))
    actual = dict(_leaves(_load_script().collect()))

    added = sorted(set(actual) - set(expected))
    removed = sorted(set(expected) - set(actual))
    moved = [
        f"{path}: {expected[path]} -> {actual[path]} "
        f"({actual[path] - expected[path]:+d})"
        for path in sorted(set(expected) & set(actual))
        if abs(actual[path] - expected[path]) > _allowed(expected[path])
    ]
    problems = (
        [f"new: {p} = {actual[p]}" for p in added]
        + [f"gone: {p}" for p in removed]
        + moved
    )
    assert not problems, (
        "The static prompt size changed. If the change is intended, run\n"
        f"    {REGENERATE}\n"
        "and commit the snapshot so that the reviewer sees the new sizes.\n"
        + "\n".join(problems)
    )


def test_every_registered_profile_is_in_the_snapshot():
    from src.agent.agent_config import default_registry

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert set(snapshot["profiles"]) == {
        c.name for c in default_registry.configs()
    }


def test_token_estimate_is_deterministic_and_offline():
    script = _load_script()
    assert script.estimate_tokens(0) == 0
    assert script.estimate_tokens(1) == 1
    assert script.estimate_tokens(4) == 1
    assert script.estimate_tokens(5) == 2
