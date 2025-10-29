import asyncio
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Annotated, Dict, List

import pandas as pd
import yaml
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState, create_react_agent
from langgraph.types import Command
from llm_sandbox import SandboxSession
from pydantic import BaseModel, Field

from src.utils.llms import GEMINI_FLASH
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class PersistentPythonSandbox:
    """Manages a persistent sandbox session with automatic lifecycle management."""

    def __init__(self):
        self.session = None
        self.session_dir = None  # Isolated temp dir for sandbox session
        self.sandbox_files = []  # Files to be copied to sandbox session
        # Suppress tar extraction deprecation warning from llm_sandbox library
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            module="llm_sandbox.core.mixins",
        )

    async def __aenter__(self):
        """Start the sandbox session asynchronously and create isolated temp dir."""
        self.session_dir = Path(
            tempfile.mkdtemp(prefix="zeno_sandbox_", dir="/tmp")
        )
        logger.info(f"Created sandbox session directory: {self.session_dir}")

        def _open_session():
            self.session = SandboxSession(
                lang="python",
                verbose=True,
                keep_template=True,
                commit_container=False,
                workdir="/sandbox",
                skip_environment_setup=False,
                default_timeout=360.0,
                execution_timeout=360.0,
                session_timeout=300.0,
                image="quay.io/jupyter/scipy-notebook",
            )
            self.session.open()

        await asyncio.to_thread(_open_session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up the sandbox session and delete temp dir."""
        if self.session:
            await asyncio.to_thread(self.session.close)

        # Clean up session dir
        if self.session_dir and self.session_dir.exists():
            shutil.rmtree(self.session_dir)
            logger.info(
                f"Deleted sandbox session directory: {self.session_dir}"
            )

        return False

    def prepare_file(self, raw_data: Dict, filename: str) -> Path:
        """
        Save raw_data to a CSV file in the sandbox session directory.
        Returns the local path (not yet copied to sandbox).
        """
        local_path = self.session_dir / filename
        df = pd.DataFrame(raw_data)

        # Drop constant columns if more then 1 row
        if len(df) > 1:
            constants = df.nunique() == 1
            logger.debug(
                f"Dropping constant columns: {list(df.columns[constants])}"
            )
            df = df.drop(columns=df.columns[constants])

        df.to_csv(local_path, index=False)
        logger.debug(f"Prepared file : {local_path}")
        return local_path

    async def copy_files_to_sandbox(
        self, local_files: List[Path]
    ) -> List[str]:
        """
        Copy files from session dir to sandbox container.
        Returns list of filenames (not full path) for tool use.
        """

        def _copy_sync():
            filenames = []
            for local_path in local_files:
                sandbox_path = f"/sandbox/{local_path.name}"
                self.session.copy_to_runtime(str(local_path), sandbox_path)
                filenames.append(local_path.name)
                self.sandbox_files.append(local_path.name)
            return filenames

        return await asyncio.to_thread(_copy_sync)

    async def execute(self, code: str, files: List[str]) -> str:
        """Execute code in the persistent session (async)."""
        if not self.session:
            raise RuntimeError(
                "Sandbox not initialized. Use within async context manager."
            )

        def _execute_sync():
            """All blocking operations in one function."""
            logger.info("CODE")
            logger.info(code)
            logger.info("FILES")
            logger.info(files)

            # Execute code (blocking)
            result = self.session.run(code)

            return result.stdout if result.exit_code == 0 else result.stderr

        # Run all blocking operations in a thread
        return await asyncio.to_thread(_execute_sync)

    async def retrieve_output(
        self, output_filename: str = "chart_data.csv"
    ) -> Path:
        """
        Retrieve output file from sandbox to session directory.
        Returns local path to the file, or None if not found.
        """

        def _retrieve_sync():
            # Check if file exists in sandbox
            check_code = f"""
from pathlib import Path
print(Path('/sandbox/{output_filename}').exists())
"""
            check_result = self.session.run(check_code)

            if check_result.stdout.strip() == "True":
                local_path = self.session_dir / output_filename
                print(f"Retrieving /sandbox/{output_filename} -> {local_path}")
                self.session.copy_from_runtime(
                    f"/sandbox/{output_filename}", str(local_path)
                )
                return local_path
            else:
                logger.warning(
                    f"Output file {output_filename} not found in sandbox"
                )
                return None

        return await asyncio.to_thread(_retrieve_sync)

    def get_tool(self):
        """Create a LangChain tool bound to this sandbox instance."""

        @tool("python_sandbox")
        async def python_sandbox(code: str, files: List[str]) -> str:
            """Execute Python code in a secure sandbox.

            code: python code to be executed inside a sandbox container
            files: list of file names accessible inside the sandbox container
            """
            return await self.execute(code, files)

        return python_sandbox


def _get_available_datasets() -> str:
    """Get a concise list of available datasets from the analytics_datasets.yml file."""
    try:
        # Get the path to the YAML file relative to this script
        current_dir = Path(__file__).parent
        yaml_path = current_dir / "analytics_datasets.yml"

        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        dataset_names = []
        for dataset in data.get("datasets", []):
            name = dataset.get("dataset_name", "Unknown")
            dataset_names.append(name)

        return ", ".join(dataset_names)

    except Exception:
        # Fallback to hardcoded list if YAML loading fails
        return "DIST-ALERT, Global Land Cover, Tree Cover Loss, and Grasslands"


class ChartInsight(BaseModel):
    """
    Represents a chart-based insight with Recharts-compatible data.
    """

    title: str = Field(description="Clear, descriptive title for the chart")
    chart_type: str = Field(
        description="Chart type: 'line', 'bar', 'stacked-bar', 'grouped-bar', 'pie', 'area', 'scatter', or 'table'"
    )
    insight: str = Field(
        description="Key insight or finding that this chart reveals (2-3 sentences)"
    )
    x_axis: str = Field(
        description="Name of the field to use for X-axis (for applicable chart types)"
    )
    y_axis: str = Field(
        description="Name of the field to use for Y-axis (for applicable chart types)"
    )
    color_field: str = Field(
        default="",
        description="Optional field name for color grouping/categorization",
    )
    stack_field: str = Field(
        default="",
        description="Field name for stacking data (for stacked-bar charts)",
    )
    group_field: str = Field(
        default="",
        description="Field name for grouping bars (for grouped-bar charts)",
    )
    series_fields: List[str] = Field(
        default=[],
        description="List of field names for multiple data series (for multi-bar charts)",
    )
    follow_up_suggestions: List[str] = Field(
        description="List of 2-3 follow-up prompt suggestions for additional analysis"
    )


@tool("generate_insights")
async def generate_insights(
    query: str,
    is_comparison: bool,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Analyzes raw data and generates a single chart insight with Recharts-compatible data.

    This tool analyzes the raw data and generates the most compelling visualization that
    answers the user's query, along with follow-up suggestions for further exploration.

    Args:
        query: Improved query from the user including relevant context that will help in
               better insight generation. Should include specific chart type requests,
               temporal focus, comparison aspects, and any domain-specific context.
        is_comparison: Whether the user is comparing two or more different AOIs (e.g.,
                      comparing Brazil vs Indonesia). Set to False for comparisons within
                      a specific AOI (e.g., provinces in a country, KBAs in a region, counties in a state).
    """
    logger.info("GENERATE-INSIGHTS-TOOL")
    logger.debug(f"Generating insights for query: {query}")

    if not state or "raw_data" not in state:
        error_msg = "No raw data available in state. Please pull data first."
        logger.error(error_msg)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                ]
            }
        )

    raw_data = state["raw_data"]

    # Create persistent sandbox with isolated session directory
    async with PersistentPythonSandbox() as sandbox:
        # 1. PREPARE FILES: Save raw_data to CSVs inside session directory

        raw_data_prompt = f"""User Query: {query}

You have access to the following datasets - pick the ones you need for analysis:

"""

        local_files = []

        for data_by_aoi in raw_data.values():
            for data in data_by_aoi.values():
                data_copy = data.copy()
                aoi_name = data_copy.pop("aoi_name")
                dataset_name = data_copy.pop("dataset_name")
                start_date = data_copy.pop("start_date")
                end_date = data_copy.pop("end_date")

                filename = (
                    f"{aoi_name}_{dataset_name}_{start_date}_{end_date}.csv"
                )
                local_path = sandbox.prepare_file(data_copy, filename)
                local_files.append(local_path)
                raw_data_prompt += f"- {filename}: {aoi_name} - {dataset_name} for date range {start_date} - {end_date}\n"

        # 2. COPY FILES TO SANDBOX: one-time bulk copy of all files
        _ = await sandbox.copy_files_to_sandbox(local_files)
        raw_data_prompt += "\nPass ONLY the files necessary to answer user query to the 'python_sandbox' tool's files argument, they are present inside /sandbox directory."

        logger.info(raw_data_prompt)

        # 3. RUN AGENT: Multiple calls to the python_sandbox tool, files already present in sandbox
        python_sandbox = sandbox.get_tool()

        codeact_agent = create_react_agent(
            model=GEMINI_FLASH,
            tools=[python_sandbox],
            prompt="""You are an expert Analyst helping users analyze datasets via code execution using the 'python_sandbox' tool.

Workflow:
1. **Explore datasets first**: Identify datasets relevant to user query, load them, use head(), info(), describe() to understand structure, columns, dtypes, and units. Never assume column names or formats.
2. **Analyze**: Write code to extract insights using pandas operations and print statements. DO NOT create plots or visualizations.
3. **Output**: Recommend an appropriate chart type and save the prepared chart data to `/sandbox/chart_data.csv`.""",
        )

        try:
            codeact_response = await codeact_agent.ainvoke(
                {"messages": [{"role": "user", "content": raw_data_prompt}]}
            )
        except Exception as e:
            logger.error(f"Error in codeact agent: {e}")
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content="I've reached my processing limit - you may have requested a large set of areas or too many data points. I'm clearing the current dataset to prevent errors. To continue your analysis, please start a new chat conversation and re-select your areas and datasets.",
                            tool_call_id=tool_call_id,
                            status="success",
                            response_metadata={"msg_type": "human_feedback"},
                        )
                    ],
                }
            )

        # 4. GET CHART DATA: Read chart data from sandbox
        chart_data_path = await sandbox.retrieve_output("chart_data.csv")

        if not chart_data_path or not chart_data_path.exists():
            logger.error("chart_data.csv not found after sandbox execution")
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content="Failed to generate chart data. Please try again.",
                            tool_call_id=tool_call_id,
                            status="error",
                        )
                    ]
                }
            )

        # 5. GENERATE CHART SCHEMA
        chart_data = pd.read_csv(chart_data_path)

        chart_insight_prompt = f"""Based on analysis done by an expert & data saved for visualization, generate structured response.

### Analysis
{codeact_response["messages"][-1].content}

### Saved chart data - head 5 rows
{chart_data.head().to_csv(index=False)}
"""

        chart_insight_response = await GEMINI_FLASH.with_structured_output(
            ChartInsight
        ).ainvoke(chart_insight_prompt)

        tool_message = f"Title: {chart_insight_response.title}"
        tool_message += f"\nKey Finding: {chart_insight_response.insight}"
        tool_message += "\nFollow-up suggestions:"
        for i, suggestion in enumerate(
            chart_insight_response.follow_up_suggestions, 1
        ):
            tool_message += f"\n{i}. {suggestion}"

        # Store chart data for frontend
        charts_data = [
            {
                "id": "main_chart",
                "title": chart_insight_response.title,
                "type": chart_insight_response.chart_type,
                "insight": chart_insight_response.insight,
                "data": chart_data.to_dict("records"),
                "xAxis": chart_insight_response.x_axis,
                "yAxis": chart_insight_response.y_axis,
                "colorField": chart_insight_response.color_field,
                "stackField": chart_insight_response.stack_field,
                "groupField": chart_insight_response.group_field,
                "seriesFields": chart_insight_response.series_fields,
            }
        ]

        # Update state with generated insight and follow-ups
        updated_state = {
            "insight": chart_insight_response.model_dump()["insight"],
            "follow_up_suggestions": chart_insight_response.model_dump()[
                "follow_up_suggestions"
            ],
            "charts_data": charts_data,
            "messages": [
                ToolMessage(
                    content=tool_message,
                    tool_call_id=tool_call_id,
                    status="success",
                    response_metadata={"msg_type": "human_feedback"},
                )
            ],
        }

        return Command(update=updated_state)
    # Sandbox automatically cleaned up here
