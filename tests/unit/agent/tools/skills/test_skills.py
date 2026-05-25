from src.agent.skills import (
    all_skills,
    get_skill_body,
    load_skills,
)


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
    assert "explore" not in names


def test_skills_registry_is_the_expected_recipes():
    # The registry holds the orchestrator recipes loaded from
    # skills_md/*.md. Tool-owned guidance and the analyst's
    # executor/wording prompts live elsewhere.
    assert {s.name for s in all_skills()} == {
        "analyze",
        "capabilities",
        "fao-fra",
        "pull-data",
    }


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
    assert "pull-data" in prompt
    assert "Pull-only" in prompt
    assert "Capabilities (what you can do" in prompt
    assert "read `capabilities`" in prompt
    assert "capabilities" in prompt
    assert "get_capabilities" not in prompt
    assert "read `analyze`" in prompt
    # always-on policy folded in
    assert "# Policy" in prompt
    assert "same language" in prompt
    assert "UI / map selections" in prompt
    # only the three recipe skills are advertised
    assert "pick-aoi" not in prompt
    assert "pick-dataset" not in prompt
