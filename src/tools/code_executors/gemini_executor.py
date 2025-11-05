"""Gemini code executor using inline data and native code execution."""

import io
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
from google import genai
from google.genai import types

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ExecutionResult:
    """Result from code execution."""

    text_output: str
    code_blocks: List[str]
    execution_outputs: List[str]
    chart_data: Optional[List[Dict]]
    error: Optional[str] = None


class GeminiCodeExecutor:
    """Simple Gemini code executor with inline data support."""

    def __init__(self, model: str = "gemini-2.5-pro"):
        """
        Initialize Gemini code executor.

        Args:
            model: Gemini model to use (must support code execution)
        """
        self.model = model
        self.client = genai.Client()

    async def prepare_dataframes(
        self, dataframes: List[tuple[pd.DataFrame, str]]
    ) -> List[Dict]:
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

    async def execute(
        self, prompt: str, inline_data_parts: List[Dict]
    ) -> ExecutionResult:
        """
        Execute code with Gemini.

        Args:
            prompt: Analysis prompt
            inline_data_parts: List of inline_data dicts from prepare_dataframes()

        Returns:
            ExecutionResult with outputs and chart data
        """
        try:
            logger.info("Executing code with Gemini")

            # Build content: [{"text": prompt}, {"inline_data": ...}, ...]
            content_parts = [{"text": prompt}] + inline_data_parts

            # Call Gemini with code execution
            response = self.client.models.generate_content(
                model=self.model,
                contents=[{"role": "user", "parts": content_parts}],
                config=types.GenerateContentConfig(
                    tools=[
                        types.Tool(code_execution=types.ToolCodeExecution())
                    ],
                ),
            )

            # Parse response
            text_parts = []
            code_blocks = []
            execution_outputs = []
            chart_data = None

            for part in response.candidates[0].content.parts:
                if part.text:
                    text_parts.append(part.text)
                if part.executable_code:
                    code_blocks.append(part.executable_code.code)
                if part.code_execution_result:
                    execution_outputs.append(part.code_execution_result.output)
                if (
                    part.inline_data
                    and part.inline_data.mime_type == "text/csv"
                ):
                    # Parse chart_data.csv from response
                    try:
                        df = pd.read_csv(io.BytesIO(part.inline_data.data))
                        chart_data = df.to_dict("records")
                        logger.info(
                            f"Parsed chart_data: {len(chart_data)} rows"
                        )
                    except Exception as e:
                        logger.error(f"Failed to parse chart_data: {e}")

            return ExecutionResult(
                text_output="\n\n".join(text_parts),
                code_blocks=code_blocks,
                execution_outputs=execution_outputs,
                chart_data=chart_data,
                error=None,
            )

        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return ExecutionResult(
                text_output="",
                code_blocks=[],
                execution_outputs=[],
                chart_data=None,
                error=str(e),
            )
