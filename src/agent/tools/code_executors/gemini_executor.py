"""Gemini code executor using inline data and native code execution."""

import asyncio
import io
from functools import partial
from typing import Dict, List

import pandas as pd
from google import genai
from google.genai import types

from src.agent.config import AgentSettings
from src.agent.tools.code_executors.base import (
    CodeActPart,
    ExecutionResult,
    PartType,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class GeminiCodeExecutor:
    """Simple Gemini code executor with inline data support."""

    MAX_RETRIES = 2
    INITIAL_DELAY = 1.0
    BACKOFF_FACTOR = 2.0

    def __init__(self):
        """
        Initialize Gemini code executor.

        Args:
            model: Gemini model to use (must support code execution)
        """
        self.model = AgentSettings.coding_model
        raw = AgentSettings.coding_fallback_models.strip()
        self.fallback_models = (
            [m.strip() for m in raw.split(",") if m.strip()] if raw else []
        )
        self.client = genai.Client()

    def build_file_references(
        self, dataframes: List[tuple[pd.DataFrame, str]]
    ) -> str:
        """
        Build Gemini-specific file reference section for prompt.

        Args:
            dataframes: List of (DataFrame, display_name) tuples

        Returns:
            Formatted string describing available files
        """
        lines = []
        for i, (_, display_name) in enumerate(dataframes):
            lines.append(f"- input_file_{i}.csv → {display_name}")
        return "\n".join(lines)

    async def prepare_dataframes(
        self, dataframes: List[tuple[pd.DataFrame, str]]
    ) -> List[CodeActPart]:
        """
        Convert DataFrames to inline_data format for Gemini.

        Args:
            dataframes: List of (DataFrame, display_name) tuples

        Returns:
            List of inline_data dicts
        """
        inline_data_parts = []

        for df, display_name in dataframes:
            logger.info(f"Preparing inline data for {display_name}")

            # Convert DataFrame to CSV bytes
            csv_bytes = df.to_csv(index=False).encode("utf-8")

            inline_data_parts.append(
                {
                    "inline_data": {
                        "mime_type": "text/csv",
                        "data": csv_bytes,
                    }
                }
            )

        return inline_data_parts

    async def _call_model(self, model: str, content_parts: List[Dict]):
        """Call a model with retry logic. Returns the raw response."""
        last_error = None
        loop = asyncio.get_running_loop()
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await loop.run_in_executor(
                    None,
                    partial(
                        self.client.models.generate_content,
                        model=model,
                        contents=[{"role": "user", "parts": content_parts}],
                        config=types.GenerateContentConfig(
                            tools=[
                                types.Tool(
                                    code_execution=types.ToolCodeExecution()
                                )
                            ],
                        ),
                    ),
                )
                return response
            except Exception as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    delay = self.INITIAL_DELAY * (self.BACKOFF_FACTOR**attempt)
                    logger.warning(
                        f"Model {model} attempt {attempt + 1} failed: {e}, "
                        f"retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
        raise last_error

    def _parse_response(self, response) -> ExecutionResult:
        """Parse a generate_content response into ExecutionResult."""
        parts = []
        chart_data = None

        for part in response.candidates[0].content.parts:
            if part.text:
                parts.append(
                    CodeActPart(type=PartType.TEXT_OUTPUT, content=part.text)
                )
            if part.executable_code:
                code = part.executable_code.code
                if code is None:
                    logger.warning(
                        "Model returned executable_code with None code, defaulting to empty string"
                    )
                    code = ""
                parts.append(
                    CodeActPart(
                        type=PartType.CODE_BLOCK,
                        content=code,
                    )
                )
            if part.code_execution_result:
                output = part.code_execution_result.output
                if output is None:
                    logger.warning(
                        "Model returned code_execution_result with None output, defaulting to empty string"
                    )
                    output = ""
                parts.append(
                    CodeActPart(
                        type=PartType.EXECUTION_OUTPUT,
                        content=output,
                    )
                )
            if part.inline_data and part.inline_data.mime_type == "text/csv":
                try:
                    df = pd.read_csv(io.BytesIO(part.inline_data.data))
                    chart_data = df.to_dict("records")
                    logger.info(f"Parsed chart_data: {len(chart_data)} rows")
                except Exception as e:
                    logger.error(f"Failed to parse chart_data: {e}")

        return ExecutionResult(
            parts=parts,
            chart_data=chart_data,
            error=None,
        )

    async def execute(
        self, prompt: str, inline_data_parts: List[Dict]
    ) -> ExecutionResult:
        """
        Execute code with Gemini, with retry and fallback.

        Args:
            prompt: Analysis prompt
            inline_data_parts: List of inline_data dicts from prepare_dataframes()

        Returns:
            ExecutionResult with outputs and chart data
        """
        content_parts = [{"text": prompt}] + inline_data_parts
        models = [self.model] + self.fallback_models

        last_error = None
        for model in models:
            try:
                logger.info(f"Executing code with model: {model}")
                response = await self._call_model(model, content_parts)
                return self._parse_response(response)
            except Exception as e:
                last_error = e
                logger.exception(f"Model {model} failed after retries: {e}")

        return ExecutionResult(
            parts=[],
            chart_data=None,
            error=str(last_error),
        )
