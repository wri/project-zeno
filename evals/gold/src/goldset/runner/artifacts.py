"""Per-case raw-artefact capture: keep more than we score.

The committed ledger stays small; these gzipped JSONs (gitignored, under
``results/artifacts/<run_id>/<uid>.json.gz``) hold the signals future
validators and triage need (decoded codeact, the tool-call sequence, the
last statistics payload, chart specs, dashboard widget bodies), so a run
can be re-analysed without being re-executed.
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from typing import Any

TOOL_OUTPUT_LIMIT = 3_000
CODEACT_PART_LIMIT = 8_000
STATISTICS_ROW_LIMIT = 200


def _decode_codeact(agent_state: dict[str, Any]) -> list[dict[str, str]]:
    parts = []
    for part in agent_state.get("codeact_parts") or []:
        try:
            content = base64.b64decode(part.get("content", "")).decode("utf-8")
        except Exception:
            content = str(part.get("content", ""))
        parts.append(
            {
                "type": part.get("type", "unknown"),
                "content": content[:CODEACT_PART_LIMIT],
            }
        )
    return parts


def _tool_calls(agent_state: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    messages = agent_state.get("messages") or []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if isinstance(call, dict):
                calls.append(
                    {
                        "name": call.get("name", "unknown"),
                        "args": call.get("args", {}),
                        "id": call.get("id", ""),
                    }
                )
    for message in messages:
        call_id = getattr(message, "tool_call_id", None)
        if call_id is None or not hasattr(message, "content"):
            continue
        for call in reversed(calls):
            if call["id"] == call_id and "output" not in call:
                call["output"] = str(message.content)[:TOOL_OUTPUT_LIMIT]
                break
    return calls


def _last_statistics(agent_state: dict[str, Any]) -> dict[str, Any] | None:
    """The last pull, with its inline rows capped. See ``utils.last_statistics``
    for the shared lookup; the slimming below is artifact-specific."""
    from goldset.evaluators.utils import last_statistics

    statistics = last_statistics(agent_state)
    if statistics is None:
        return None
    slim = {k: v for k, v in statistics.items() if k != "data"}
    data = statistics.get("data")
    if isinstance(data, list):
        slim["data"] = data[:STATISTICS_ROW_LIMIT]
        slim["data_rows_total"] = len(data)
    elif data is not None:
        slim["data"] = data
    return slim


def _cap_table(table: dict[str, Any]) -> dict[str, Any]:
    """One column-oriented table with each column's rows capped."""
    slim: dict[str, Any] = {
        key: values[:STATISTICS_ROW_LIMIT] if isinstance(values, list) else values
        for key, values in table.items()
    }
    first = next((v for v in table.values() if isinstance(v, list)), None)
    if first is not None:
        slim["_rows_total"] = len(first)
    return slim


def _pulled_data(agent_state: dict[str, Any]) -> dict[str, Any] | None:
    """The agent's raw pulled table (ground-truth runs only), rows capped.

    Two shapes, both seen live. Most datasets answer flat as
    ``{column: [values]}`` but LGMS (12) answers as ``{section: {column: [values]}}``
    """
    pulled = agent_state.get("pulled_data")
    if not isinstance(pulled, dict) or not pulled:
        return None
    if all(isinstance(value, dict) for value in pulled.values()):
        return {section: _cap_table(table) for section, table in pulled.items()}
    return _cap_table(pulled)


def build_artifact(
    agent_state: dict[str, Any],
    dashboard: dict[str, Any] | None,
    thread_id: str,
    trace_url: str | None,
) -> dict[str, Any]:
    """Everything worth keeping from one case's raw state, JSON-safe."""
    from goldset.evaluators.answer_evaluator import extract_final_answer_text

    return {
        "thread_id": thread_id,
        "trace_url": trace_url,
        "final_answer": extract_final_answer_text(agent_state.get("messages", [])),
        "codeact": _decode_codeact(agent_state),
        "tool_calls": _tool_calls(agent_state),
        "statistics_last": _last_statistics(agent_state),
        "pulled_data": _pulled_data(agent_state),
        "charts_data": agent_state.get("charts_data"),
        "aoi_selection": agent_state.get("aoi_selection"),
        "dataset": agent_state.get("dataset"),
        "suggested_datasets": agent_state.get("suggested_datasets"),
        "nudge": agent_state.get("nudge"),
        "dashboard_widgets": (dashboard or {}).get("widgets"),
    }


class ArtifactWriter:
    """Writes one gzipped JSON per case under a run's artefact directory."""

    def __init__(self, artifacts_dir: Path, run_id: str):
        self._dir = artifacts_dir / run_id
        self._dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, uid: str, trial: int, artifact: dict[str, Any]) -> Path:
        suffix = f"_t{trial}" if trial > 1 else ""
        path = self._dir / f"{uid}{suffix}.json.gz"
        payload = json.dumps(artifact, default=str, ensure_ascii=False)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(payload)
        return path
