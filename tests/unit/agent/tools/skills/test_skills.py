import pytest

from src.agent.skills import (
    all_skills,
    get_skill,
    get_skill_body,
    load_skills,
)
from src.agent.skills.tool import read_skill
from src.agent.tool_spec import Availability, set_bound_availability

_EMPTY = Availability(skills=frozenset(), tools=frozenset())


def _availability(*skills: str) -> Availability:
    return Availability(skills=frozenset(skills), tools=frozenset())


@pytest.fixture(autouse=True)
def _reset_bound_availability():
    """``bound_availability`` is a ContextVar; tests must not leak state."""
    yield
    set_bound_availability(_EMPTY)


def test_load_skills():
    skills = load_skills()
    names = {s.name for s in skills}
    assert "analyze" in names
    assert "capabilities" in names
    assert "pull-data" in names
    # Tool-owned guidance was moved into tool docstrings.
    assert "pick-aoi" not in names
    assert "pick-dataset" not in names
    # Always-on policy was folded into the system prompt.
    assert "general-rules" not in names
    assert "ui-selections" not in names


def test_skills_registry_is_the_seven_recipes():
    assert {s.name for s in all_skills()} == {
        "analyze",
        "capabilities",
        "dashboard",
        "explore",
        "pull-data",
        "wri-insights",
        "show-imagery",
    }


def test_wri_insights_skill_citation_guidance():
    body = get_skill_body("wri-insights")
    assert body is not None
    assert "wri_insights" in body
    assert "intermediate" in body.lower()
    assert "affirmative" in body.lower()
    assert "generate_insights" in body


def test_generate_insights_is_a_thin_subagent_tool():
    from src.agent.subagents import Analyst, generate_insights
    from src.agent.subagents.analyst.prompts import (
        EXECUTOR_WORKFLOW,
        WORDING_GUIDE,
    )

    assert hasattr(Analyst, "analyze")
    assert "chart insight" in generate_insights.description.lower()

    # The executor workflow + wording guide live in the subagent's prompts.
    assert "STEP-BY-STEP WORKFLOW" in EXECUTOR_WORKFLOW
    assert "**Avoid:**" in WORDING_GUIDE


def test_capabilities_skill_includes_datasets():
    body = get_skill_body("capabilities")
    assert body is not None
    assert "{{AVAILABLE_DATASETS}}" not in body
    assert "## Available datasets" in body
    assert body.strip().startswith("# Workflow")


def test_get_skill_body():
    body = get_skill_body("analyze")
    assert body is not None
    assert "pick_aoi" in body


def test_get_skill_returns_meta_with_requires():
    skill = get_skill("analyze")
    assert skill is not None
    assert set(skill.requires) == {
        "pick_aoi",
        "pick_dataset",
        "pull_data",
        "generate_insights",
    }


def test_get_skill_returns_none_for_unknown_name():
    assert get_skill("does-not-exist") is None


def test_get_skill_capabilities_has_no_requires():
    """Informational skills contribute no tools to the profiles that
    declare them."""
    skill = get_skill("capabilities")
    assert skill is not None
    assert skill.requires == ()


def test_read_skill_refuses_a_skill_the_profile_does_not_declare():
    """The profile's declared skills are the capability surface; anything
    else must read exactly like an unknown skill name to the model — it's
    already excluded from what this profile advertises
    (AgentConfig.skill_metas())."""
    set_bound_availability(_availability("pull-data", "capabilities"))
    result = read_skill.invoke({"name": "analyze"})
    assert result == "skill not found: analyze"


def test_read_skill_refuses_everything_when_nothing_is_bound():
    """Outside fetch_zeno no profile is bound, so no skill is served — even
    ones with no tool requirements."""
    for name in ("analyze", "capabilities"):
        result = read_skill.invoke({"name": name})
        assert result == f"skill not found: {name}"


def test_read_skill_logs_the_refusal_without_exposing_profile_details(
    monkeypatch,
):
    """The model-facing message stays a generic "not found"; the reason is
    only for our own logs."""
    warnings = []

    class _FakeLogger:
        def warning(self, event, **kwargs):
            warnings.append((event, kwargs))

        def info(self, *args, **kwargs):
            pass

    monkeypatch.setattr("src.agent.skills.tool.logger", _FakeLogger())
    set_bound_availability(_availability("capabilities"))
    result = read_skill.invoke({"name": "analyze"})

    assert result == "skill not found: analyze"
    [(event, kwargs)] = warnings
    assert event == "read_skill: skill not declared by this profile"
    assert kwargs["skill_name"] == "analyze"


def test_read_skill_serves_a_declared_skill():
    set_bound_availability(_availability("analyze"))
    result = read_skill.invoke({"name": "analyze"})
    assert result == get_skill_body("analyze")


def test_read_skill_serves_each_skill_a_profile_declares():
    """Declaring more skills must not interfere with serving any of them."""
    set_bound_availability(_availability("analyze", "capabilities"))
    assert read_skill.invoke({"name": "capabilities"}) == get_skill_body(
        "capabilities"
    )
    assert read_skill.invoke({"name": "analyze"}) == get_skill_body("analyze")


def test_read_skill_unknown_name_still_reports_not_found():
    set_bound_availability(_availability("analyze"))
    result = read_skill.invoke({"name": "does-not-exist"})
    assert "skill not found" in result


def test_pick_dataset_is_a_thin_subagent_tool():
    from src.agent.subagents import DatasetSelector, pick_dataset
    from src.agent.subagents.pick_dataset.prompts import (
        DATASET_SELECTOR_PROMPT,
    )

    # Orchestrator-facing contract stays in the tool description.
    doc = pick_dataset.description
    assert "Dataset-only" in doc
    assert "AOI is NOT required" in doc
    assert "subagent" in doc

    # The subagent owns the selection reasoning in its own system prompt.
    assert hasattr(DatasetSelector, "resolve")
    assert "dataset selector" in DATASET_SELECTOR_PROMPT.lower()


def test_pick_aoi_is_a_thin_subagent_tool():
    from src.agent.subagents import pick_aoi
    from src.agent.subagents.pick_aoi.prompts import GEOCODER_PROMPT

    # The tool call is trivial: just the user's request, no parsed places.
    assert "question" in pick_aoi.args
    assert "places" not in pick_aoi.args
    assert "subregion" not in pick_aoi.args

    # The orchestrator-facing description tells it to forward the request,
    # not to translate or classify the place itself.
    doc = pick_aoi.description
    assert "verbatim" in doc
    assert "geocoding subagent" in doc

    # The extraction rules live inside the subagent's own system prompt.
    assert "ENGLISH" in GEOCODER_PROMPT
    assert "subregion" in GEOCODER_PROMPT.lower()


def test_pull_data_skill_pull_only():
    body = get_skill_body("pull-data")
    assert body is not None
    assert "pull_data" in body
    assert "generate_insights" in body
    assert "Stop" in body
    assert "analyze" in body


def test_get_prompt_scope_and_policy():
    from src.agent.graph import get_prompt

    prompt = get_prompt()
    # per-skill routing lives in the skills block, not the Routing table
    assert "- pull-data:" in prompt
    assert "- capabilities:" in prompt
    assert "- analyze:" in prompt
    assert "get_capabilities" not in prompt
    # the no-skill request shapes stay in Routing
    assert "Dataset-only" in prompt
    assert "AOI-only" in prompt
    # always-on policy folded in
    assert "# Policy" in prompt
    assert "Reply in the language given in the session block" in prompt
    assert "UI / map selections" in prompt
    # only the three recipe skills are advertised
    assert "pick-aoi" not in prompt
    assert "pick-dataset" not in prompt


def test_get_prompt_has_no_per_skill_routing_rows():
    """Per-skill routing restated each skill's when_to_use; it must stay
    dropped for every profile so the skills block is the single source."""
    from src.agent.agent_config import EXPERIMENTAL_PROFILE, default_registry
    from src.agent.graph import get_prompt

    for config in (None, default_registry.resolve(EXPERIMENTAL_PROFILE)):
        prompt = get_prompt(config=config)
        assert "Pull-only" not in prompt
        assert "Full analysis (place + topic" not in prompt
        assert "Dashboard (" not in prompt
        assert "Imagery (" not in prompt
        assert "Capabilities (what you can do" not in prompt


def test_get_prompt_routing_gates_recall_row_on_search_insights():
    """The recall row routes to the search_insights tool; a profile that
    doesn't bind it must not see the row."""
    from src.agent.agent_config import EXPERIMENTAL_PROFILE, default_registry
    from src.agent.graph import get_prompt

    default_prompt = get_prompt()
    assert "Recall a past insight" not in default_prompt
    assert "search_insights" not in default_prompt

    experimental = default_registry.resolve(EXPERIMENTAL_PROFILE)
    assert "Recall a past insight" in get_prompt(config=experimental)
