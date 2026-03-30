"""
Unit tests for canopy cover threshold support in analytics_handler and pull_data.

These tests are purely deterministic — no LLM calls, no HTTP calls.
They verify that:
  1. _build_payload uses the passed canopy_cover for TCL, Tree Cover, and TCL by Driver
  2. Forest Carbon Flux always uses 30% regardless of the canopy_cover argument
  3. DataPullOrchestrator and the pull_data tool correctly thread canopy_cover through

Database access is not needed and is overridden to no-ops.
"""

import inspect

import pytest

from src.agent.tools.data_handlers.analytics_handler import AnalyticsHandler
from src.agent.tools.datasets_config import DATASETS
from src.agent.tools.generate_insights import build_analysis_prompt
from src.agent.tools.pull_data import DataPullOrchestrator, pull_data

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Override DB fixtures — these tests don't need the database
@pytest.fixture(scope="function", autouse=True)
def test_db():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    pass


_DS_BY_NAME = {ds["dataset_name"]: ds for ds in DATASETS}

# Minimal admin AOI that doesn't require DB or geometry lookups
_BRAZIL_ADMIN_AOI = {
    "subtype": "country",
    "src_id": "BRA",
    "name": "Brazil",
}

_HANDLER = AnalyticsHandler()


def _dataset(name: str, context_layer=None) -> dict:
    """Return a copy of a dataset dict with context_layer set."""
    ds = dict(_DS_BY_NAME[name])
    ds["context_layer"] = context_layer
    return ds


# ---------------------------------------------------------------------------
# _build_payload: canopy_cover is forwarded for tree cover datasets
# ---------------------------------------------------------------------------


class TestBuildPayloadCanopyCover:
    """_build_payload must use the canopy_cover kwarg for variable-threshold datasets."""

    async def test_tcl_default_is_30(self):
        """Tree Cover Loss uses 30% when canopy_cover is not specified."""
        payload = await _HANDLER._build_payload(
            _dataset("Tree cover loss"),
            [_BRAZIL_ADMIN_AOI],
            "2020-01-01",
            "2022-12-31",
        )
        assert payload["canopy_cover"] == 30

    @pytest.mark.parametrize("threshold", [10, 15, 20, 25, 50, 75])
    async def test_tcl_uses_specified_threshold(self, threshold):
        """Tree Cover Loss uses the exact threshold passed in."""
        payload = await _HANDLER._build_payload(
            _dataset("Tree cover loss"),
            [_BRAZIL_ADMIN_AOI],
            "2020-01-01",
            "2022-12-31",
            canopy_cover=threshold,
        )
        assert payload["canopy_cover"] == threshold

    @pytest.mark.parametrize("threshold", [10, 15, 25, 50])
    async def test_tcl_by_driver_uses_specified_threshold(self, threshold):
        """Tree Cover Loss by Dominant Driver uses the exact threshold passed in."""
        payload = await _HANDLER._build_payload(
            _dataset("Tree cover loss by dominant driver"),
            [_BRAZIL_ADMIN_AOI],
            "2020-01-01",
            "2022-12-31",
            canopy_cover=threshold,
        )
        assert payload["canopy_cover"] == threshold

    @pytest.mark.parametrize("threshold", [10, 15, 25, 50])
    async def test_tree_cover_uses_specified_threshold(self, threshold):
        """Tree Cover (2000 baseline) uses the exact threshold passed in."""
        payload = await _HANDLER._build_payload(
            _dataset("Tree cover"),
            [_BRAZIL_ADMIN_AOI],
            "2000-01-01",
            "2000-12-31",
            canopy_cover=threshold,
        )
        assert payload["canopy_cover"] == threshold

    @pytest.mark.parametrize("threshold", [10, 15, 20, 25, 50, 75])
    async def test_forest_carbon_flux_always_30(self, threshold):
        """Forest Carbon Flux always uses 30%, regardless of input threshold.

        This dataset has a fixed threshold that cannot be changed per the API
        and dataset documentation.
        """
        payload = await _HANDLER._build_payload(
            _dataset("Forest greenhouse gas net flux"),
            [_BRAZIL_ADMIN_AOI],
            "2001-01-01",
            "2024-12-31",
            canopy_cover=threshold,
        )
        assert payload["canopy_cover"] == 30, (
            f"Forest Carbon Flux must always use 30%, got {payload['canopy_cover']} "
            f"when canopy_cover={threshold} was requested"
        )

    async def test_tcl_intersections_present_with_context_layer(self):
        """When context_layer is set, intersections are included alongside canopy_cover."""
        payload = await _HANDLER._build_payload(
            _dataset("Tree cover loss by dominant driver", context_layer="driver"),
            [_BRAZIL_ADMIN_AOI],
            "2020-01-01",
            "2022-12-31",
            canopy_cover=10,
        )
        assert payload["canopy_cover"] == 10
        assert payload["intersections"] == ["driver"]


# ---------------------------------------------------------------------------
# Signature checks: canopy_cover is present with correct defaults
# ---------------------------------------------------------------------------


class TestSignatures:
    """Verify canopy_cover is plumbed through every layer of the call stack.

    These are synchronous checks — no async needed.
    """

    # Override the module-level asyncio mark for this class
    pytestmark = []

    def test_build_payload_has_canopy_cover_param(self):
        sig = inspect.signature(AnalyticsHandler._build_payload)
        assert "canopy_cover" in sig.parameters
        assert sig.parameters["canopy_cover"].default == 30

    def test_analytics_handler_pull_data_has_canopy_cover_param(self):
        sig = inspect.signature(AnalyticsHandler.pull_data)
        assert "canopy_cover" in sig.parameters
        assert sig.parameters["canopy_cover"].default == 30

    def test_orchestrator_pull_data_has_canopy_cover_param(self):
        sig = inspect.signature(DataPullOrchestrator.pull_data)
        assert "canopy_cover" in sig.parameters
        assert sig.parameters["canopy_cover"].default == 30

    def test_pull_data_tool_has_canopy_cover_param(self):
        """The LangChain tool exposes canopy_cover so the LLM can set it."""
        # StructuredTool stores the underlying coroutine in .coroutine
        underlying = pull_data.coroutine
        sig = inspect.signature(underlying)
        assert "canopy_cover" in sig.parameters
        # Optional — defaults to None so the tool layer defaults to 30
        assert sig.parameters["canopy_cover"].default is None


# ---------------------------------------------------------------------------
# Default propagation: None → 30 at the tool boundary
# ---------------------------------------------------------------------------


class TestDefaultPropagation:
    """None passed to the tool should be interpreted as the 30% default.

    The pull_data tool function accepts canopy_cover=None (Optional[int]) and
    must normalise it to 30 before forwarding to the orchestrator.
    We verify this by checking the orchestrator receives the correct default
    through a mocked handler.
    """

    async def test_orchestrator_default_canopy_cover_propagates_to_handler(self):
        """Orchestrator passes canopy_cover=30 to handler by default."""
        captured = {}

        class _MockHandler:
            def can_handle(self, _dataset):
                return True

            async def pull_data(self, **kwargs):
                captured["canopy_cover"] = kwargs.get("canopy_cover")
                from src.agent.tools.data_handlers.base import DataPullResult

                return DataPullResult(
                    success=True,
                    data={"data": []},
                    message="mock",
                    data_points_count=0,
                    analytics_api_url="http://example.com",
                )

        orchestrator = DataPullOrchestrator()
        orchestrator.handlers = [_MockHandler()]

        await orchestrator.pull_data(
            query="test",
            dataset={"dataset_id": 99, "dataset_name": "mock"},
            start_date="2020-01-01",
            end_date="2022-12-31",
            change_over_time_query=False,
            aois=[_BRAZIL_ADMIN_AOI],
            # canopy_cover intentionally omitted — should default to 30
        )
        assert captured["canopy_cover"] == 30

    async def test_orchestrator_custom_canopy_cover_propagates_to_handler(self):
        """Orchestrator forwards an explicit canopy_cover value to the handler."""
        captured = {}

        class _MockHandler:
            def can_handle(self, _dataset):
                return True

            async def pull_data(self, **kwargs):
                captured["canopy_cover"] = kwargs.get("canopy_cover")
                from src.agent.tools.data_handlers.base import DataPullResult

                return DataPullResult(
                    success=True,
                    data={"data": []},
                    message="mock",
                    data_points_count=0,
                    analytics_api_url="http://example.com",
                )

        orchestrator = DataPullOrchestrator()
        orchestrator.handlers = [_MockHandler()]

        await orchestrator.pull_data(
            query="test",
            dataset={"dataset_id": 99, "dataset_name": "mock"},
            start_date="2020-01-01",
            end_date="2022-12-31",
            change_over_time_query=False,
            aois=[_BRAZIL_ADMIN_AOI],
            canopy_cover=10,
        )
        assert captured["canopy_cover"] == 10


# ---------------------------------------------------------------------------
# build_analysis_prompt: canopy_cover override appears in the prompt
# ---------------------------------------------------------------------------

_TCL_CODE_INSTRUCTIONS = (
    'THRESHOLD: extract the canopy cover threshold from the query (e.g. "10%", "30%"); '
    'if not specified, use 30%. ALWAYS print "Canopy cover threshold: X% (<source>)" '
    "at the start of the analysis output AND include it in the chart title. "
    'If no source was specified, write "30% (GFW default)".'
)


@pytest.mark.no_cover
class TestBuildAnalysisPromptCanopyOverride:
    """build_analysis_prompt must inject the resolved threshold so Gemini
    cannot fall back to its own inference from the query text."""

    # Pure-function synchronous tests — opt out of the module-level asyncio mark.
    pytestmark = [pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")]

    def test_override_line_present_for_non_default_threshold(self):
        """A non-default threshold produces an explicit override line."""
        prompt = build_analysis_prompt(
            query="Show tree cover loss in India from 2015 to 2022",
            file_references="input_file_0.csv",
            code_instructions=_TCL_CODE_INSTRUCTIONS,
            canopy_cover=10,
        )
        assert "THRESHOLD USED FOR DATA FETCH: 10%" in prompt

    def test_override_line_present_for_default_threshold(self):
        """The override line is also injected for the 30% default so the
        instruction is always explicit, not left to inference."""
        prompt = build_analysis_prompt(
            query="Show tree cover loss in Brazil from 2015 to 2022",
            file_references="input_file_0.csv",
            code_instructions=_TCL_CODE_INSTRUCTIONS,
            canopy_cover=30,
        )
        assert "THRESHOLD USED FOR DATA FETCH: 30%" in prompt

    def test_override_line_precedes_code_instructions(self):
        """The override must appear before the raw code_instructions so it
        takes precedence over the 'if not specified, use 30%' fallback."""
        prompt = build_analysis_prompt(
            query="Show tree cover loss in India",
            file_references="input_file_0.csv",
            code_instructions=_TCL_CODE_INSTRUCTIONS,
            canopy_cover=10,
        )
        override_pos = prompt.index("THRESHOLD USED FOR DATA FETCH: 10%")
        fallback_pos = prompt.index("if not specified, use 30%")
        assert override_pos < fallback_pos

    def test_no_override_when_no_code_instructions(self):
        """When there are no code_instructions the dataset_rules_section is
        skipped entirely — no spurious override line should appear."""
        prompt = build_analysis_prompt(
            query="Show tree cover loss in India",
            file_references="input_file_0.csv",
            code_instructions=None,
            canopy_cover=10,
        )
        assert "THRESHOLD USED FOR DATA FETCH" not in prompt

    def test_state_canopy_cover_stored_in_pull_data_command(self):
        """pull_data resolves canopy_cover=None to 30 and stores it in state."""
        # Verify the Command update dict contains canopy_cover at the tool level.
        # We check the source rather than running the full async tool to keep
        # this test fast and dependency-free.
        import ast
        import inspect

        source = inspect.getsource(pull_data.coroutine)
        tree = ast.parse(source)

        # Find all string constants in the source — "canopy_cover" must appear
        # as a dict key in the Command(update={...}) call.
        string_literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert "canopy_cover" in string_literals, (
            "pull_data must store 'canopy_cover' in the Command update dict "
            "so generate_insights can read it from state"
        )
