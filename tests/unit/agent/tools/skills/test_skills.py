from src.agent.tools.skills import all_skills, get_skill_body, load_skills


def test_load_skills():
    skills = load_skills()
    names = {s.name for s in skills}
    assert "analyze" in names
    assert "pick-aoi" in names
    assert "capabilities" in names
    assert "explore" not in names
    assert len(skills) >= 7


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


def test_pick_dataset_skill_dataset_only():
    body = get_skill_body("pick-dataset")
    assert body is not None
    assert "Dataset-only" in body
    assert "pick_dataset" in body
    assert "Do not ask for a country" in body


def test_pull_data_skill_pull_only():
    body = get_skill_body("pull-data")
    assert body is not None
    assert "pull_data" in body
    assert "generate_insights" in body
    assert "Stop" in body
    assert "analyze" in body


def test_get_prompt_pull_only_scope():
    from src.agent.graph import get_prompt

    prompt = get_prompt()
    assert "pull-data" in prompt
    assert "Pull-only" in prompt
    assert "Capabilities-only" in prompt
    assert "capabilities" in prompt
    assert "get_capabilities" not in prompt
    assert "Do not read `analyze`" in prompt


def test_executor_skill_hidden_from_all_skills_list():
    names = {s.name for s in all_skills()}
    assert "generate-insights-executor" in names
