"""Local code executor using smolagents' in-process Python interpreter.

A lightweight, Docker-free alternative to the Gemini native code-execution
sandbox. A code-specialized chat model (e.g. an Ollama Cloud model) writes
Python in a CodeAct loop; each block runs in a restricted, stateful
``LocalPythonExecutor`` (import allowlist + execution timeout). Dataframes are
injected as namespace variables (``input_file_0`` ...), and the final block
assigns ``chart_data`` and ``insight`` which we read back from the interpreter
state.

Security note: ``LocalPythonExecutor`` restricts imports and operations but is
NOT a hardened sandbox. It is acceptable here because the executed code only
analyses CSVs the system itself produced. For a stronger boundary, swap in
smolagents' Docker/E2B executor behind ``get_code_executor()``.
"""

import asyncio
import re
from functools import partial
from typing import Dict, List, Optional, Tuple

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from smolagents import LocalPythonExecutor

from src.agent.config import AgentSettings
from src.agent.subagents.analyst.code_executors.base import (
    CodeActPart,
    CodeExecutor,
    ExecutionResult,
    MultiChartInsight,
    PartType,
)
from src.agent.subagents.analyst.prompts import EXECUTOR_WORKFLOW_LOCAL
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Modules the generated analysis code is allowed to import.
AUTHORIZED_IMPORTS = [
    "pandas",
    "numpy",
    "json",
    "math",
    "statistics",
    "datetime",
    "collections",
    "itertools",
]

_CODE_BLOCK_RE = re.compile(r"```(?:python|py)?\s*\n?(.*?)```", re.DOTALL)

_SYSTEM_PROMPT = """You are a data analyst writing Python in a stateful interpreter.

Protocol:
- Reply with EXACTLY ONE Python code block (```python ... ```) per message, plus
  optional brief prose. Variables persist between messages.
- After each block runs you will receive its printed output; use it to decide the
  next step. Follow the step-by-step workflow given by the user.
- Only these libraries are importable: pandas (pd), numpy (np), json, math,
  statistics, datetime. There is NO filesystem — never read or write files.
- Finish by assigning `chart_data` (a list of row dicts) and `insight` (a dict
  matching the MultiChartInsight schema) as variables.
"""


class LocalCodeExecutor(CodeExecutor):
    """CodeAct executor backed by smolagents' LocalPythonExecutor."""

    MAX_ITERATIONS = 8
    EXECUTION_TIMEOUT = 60

    #: Variable-based workflow: data is preloaded, results read from namespace.
    workflow = EXECUTOR_WORKFLOW_LOCAL

    def __init__(self):
        self.model_keys = self._resolve_model_keys()

    @staticmethod
    def _resolve_model_keys() -> List[str]:
        """Build the ordered list of MODEL_REGISTRY keys to try."""
        primary = AgentSettings.coding_model.strip().lower()
        raw = AgentSettings.coding_fallback_models.strip()
        fallbacks = (
            [m.strip().lower() for m in raw.split(",") if m.strip()]
            if raw
            else []
        )
        keys = [primary] + [k for k in fallbacks if k and k != primary]
        return keys

    # How many sample rows of each dataframe to show the model.
    PREVIEW_ROWS = 5

    def build_file_references(
        self, dataframes: List[Tuple[pd.DataFrame, str]]
    ) -> str:
        """Describe each DataFrame variable with its real schema + a preview.

        Weaker coding models guess column names and write defensive code that
        raises when a guessed column is absent. Showing the actual columns,
        dtypes, and a few rows up front removes the guessing.
        """
        blocks = []
        for i, (df, display_name) in enumerate(dataframes):
            cols = "\n".join(
                f"    - {col}: {dtype}" for col, dtype in df.dtypes.items()
            )
            preview = df.head(self.PREVIEW_ROWS).to_csv(index=False).strip()
            blocks.append(
                f"- `input_file_{i}` (pandas DataFrame) → {display_name}\n"
                f"  shape: {df.shape[0]} rows × {df.shape[1]} columns\n"
                f"  columns (name: dtype):\n{cols}\n"
                f"  first {min(self.PREVIEW_ROWS, len(df))} rows (CSV):\n"
                f"```\n{preview}\n```"
            )
        return "\n".join(blocks)

    async def prepare_dataframes(
        self, dataframes: List[Tuple[pd.DataFrame, str]]
    ) -> Dict[str, pd.DataFrame]:
        """Map each DataFrame to its interpreter variable name."""
        return {f"input_file_{i}": df for i, (df, _) in enumerate(dataframes)}

    def _new_executor(self) -> LocalPythonExecutor:
        executor = LocalPythonExecutor(
            additional_authorized_imports=AUTHORIZED_IMPORTS,
            timeout_seconds=self.EXECUTION_TIMEOUT,
        )
        # send_tools is required to populate the base builtins (print, range,
        # math helpers, ...) before any code can run.
        executor.send_tools({})
        return executor

    @staticmethod
    def _extract_code(content: str) -> Optional[str]:
        match = _CODE_BLOCK_RE.search(content or "")
        return match.group(1).strip() if match else None

    @staticmethod
    def _coerce_chart_data(value) -> Optional[List[Dict]]:
        if value is None:
            return None
        if isinstance(value, pd.DataFrame):
            return value.to_dict("records")
        if isinstance(value, list):
            return value
        return None

    @staticmethod
    def _coerce_insight(
        value,
    ) -> Tuple[Optional[MultiChartInsight], Optional[str]]:
        """Return (insight, error). error is None on success."""
        if value is None:
            return None, None
        try:
            if isinstance(value, MultiChartInsight):
                return value, None
            if isinstance(value, str):
                return MultiChartInsight.model_validate_json(value), None
            if isinstance(value, dict):
                return MultiChartInsight.model_validate(value), None
            if isinstance(value, (bytes, bytearray)):
                return (
                    MultiChartInsight.model_validate_json(
                        value.decode("utf-8")
                    ),
                    None,
                )
            return None, f"`insight` has unsupported type {type(value)}"
        except Exception as e:
            logger.error(f"Failed to parse insight: {e}")
            return None, str(e)

    @staticmethod
    def _build_feedback(
        raw_chart,
        chart_data: Optional[List[Dict]],
        raw_insight,
        insight: Optional[MultiChartInsight],
        insight_err: Optional[str],
    ) -> str:
        """Tell the model what is still missing/invalid so it can self-correct."""
        notes: List[str] = []
        if chart_data is None:
            if raw_chart is None:
                notes.append(
                    "`chart_data` is not defined. Define it as a list of row dicts."
                )
            else:
                notes.append(
                    f"`chart_data` must be a list of row dicts (got {type(raw_chart).__name__})."
                )
        if insight is None:
            if raw_insight is None:
                notes.append(
                    "`insight` is not defined. Define it as a dict with a "
                    "top-level `charts` LIST plus `primary_insight` and "
                    "`follow_up_suggestions`."
                )
            else:
                notes.append(
                    f"`insight` is invalid: {insight_err}. It must be a dict "
                    "with a top-level `charts` LIST (each entry is one chart) "
                    "plus `primary_insight` and `follow_up_suggestions`. Do not "
                    "put chart fields (title/chart_type/x_axis/...) at the top level."
                )
        if not notes:
            return ""
        return "Not done yet — fix in your NEXT code block:\n" + "\n".join(
            f"- {n}" for n in notes
        )

    async def _run_with_model(
        self, model, prompt: str, prepared: Dict[str, pd.DataFrame]
    ) -> ExecutionResult:
        """Run the full CodeAct loop with a single model."""
        executor = self._new_executor()
        executor.send_variables(prepared)

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        parts: List[CodeActPart] = []
        chart_data: Optional[List[Dict]] = None
        insight: Optional[MultiChartInsight] = None
        loop = asyncio.get_running_loop()

        for iteration in range(self.MAX_ITERATIONS):
            response = await model.ainvoke(messages)
            content = str(response.text)
            messages.append(AIMessage(content=content))

            code = self._extract_code(content)
            # Keep any prose the model produced for user-facing feedback.
            prose = _CODE_BLOCK_RE.sub("", content).strip()
            if prose:
                parts.append(
                    CodeActPart(type=PartType.TEXT_OUTPUT, content=prose)
                )

            if not code:
                logger.warning(
                    f"Model produced no code block on iteration {iteration}"
                )
                feedback = self._build_feedback(
                    executor.state.get("chart_data"),
                    chart_data,
                    executor.state.get("insight"),
                    insight,
                    None,
                )
                messages.append(
                    HumanMessage(
                        content="Reply with a single Python code block. "
                        + feedback
                    )
                )
                continue

            parts.append(CodeActPart(type=PartType.CODE_BLOCK, content=code))

            try:
                result = await loop.run_in_executor(
                    None, partial(executor, code)
                )
                output = result.logs or ""
            except Exception as e:
                output = f"Error: {e}"
                logger.warning(f"Code execution error: {e}")

            parts.append(
                CodeActPart(type=PartType.EXECUTION_OUTPUT, content=output)
            )

            raw_chart = executor.state.get("chart_data")
            raw_insight = executor.state.get("insight")
            chart_data = self._coerce_chart_data(raw_chart)
            insight, insight_err = self._coerce_insight(raw_insight)
            if chart_data is not None and insight is not None:
                break

            feedback = self._build_feedback(
                raw_chart, chart_data, raw_insight, insight, insight_err
            )
            exec_msg = f"Execution output:\n{output}"
            if feedback:
                exec_msg += f"\n\n{feedback}"
            messages.append(HumanMessage(content=exec_msg))

        self._log_code_and_outputs(parts)
        return ExecutionResult(
            parts=parts,
            chart_data=chart_data,
            insight=insight,
            error=None,
        )

    def _log_code_and_outputs(self, parts: List[CodeActPart]) -> None:
        segments: List[str] = []
        n_code = n_out = 0
        for part in parts:
            if part.type == PartType.CODE_BLOCK:
                n_code += 1
                segments.append(f"--- code_block {n_code} ---\n{part.content}")
            elif part.type == PartType.EXECUTION_OUTPUT:
                n_out += 1
                segments.append(
                    f"--- execution_output {n_out} ---\n{part.content}"
                )
        if segments:
            logger.debug("Executor code and outputs:\n" + "\n".join(segments))

    async def execute(
        self, prompt: str, prepared: Dict[str, pd.DataFrame]
    ) -> ExecutionResult:
        """Run the analysis, trying each configured coding model in turn."""
        from src.agent.llms import MODEL_REGISTRY

        last_result: Optional[ExecutionResult] = None
        last_error: Optional[str] = None

        for key in self.model_keys:
            model = MODEL_REGISTRY.get(key)
            if model is None:
                logger.warning(
                    f"Unknown coding model '{key}', skipping. "
                    f"Available: {list(MODEL_REGISTRY)}"
                )
                continue
            try:
                logger.info(f"Executing code with model: {key}")
                result = await self._run_with_model(model, prompt, prepared)
                if (
                    result.chart_data is not None
                    and result.insight is not None
                ):
                    return result
                last_result = result
                logger.warning(
                    f"Model {key} produced incomplete result "
                    "(missing chart_data or insight)"
                )
            except Exception as e:
                last_error = str(e)
                logger.exception(f"Model {key} failed: {e}")

        if last_result is not None:
            return last_result
        return ExecutionResult(
            parts=[],
            chart_data=None,
            insight=None,
            error=last_error or "No usable coding model configured",
        )
