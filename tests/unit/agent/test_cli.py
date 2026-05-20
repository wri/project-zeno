from click.testing import CliRunner
from langchain_core.messages import AIMessage

from src.agent.cli import (
    format_message_content,
    format_state_line,
    format_tool_action,
    format_tool_outcome,
    main,
)
from src.agent.graph import get_prompt


def test_show_prompt():
    runner = CliRunner()
    result = runner.invoke(main, ["--show-prompt"])
    assert result.exit_code == 0
    assert "Geospatial Agent" in result.output
    assert get_prompt().strip() in result.output


def test_prompt_and_prompt_file_mutually_exclusive(tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("custom from file", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["-p", "custom", "-f", str(prompt_file), "-q", "hi"],
    )
    assert result.exit_code != 0
    assert "only one" in result.output.lower()


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "--prompt-file" in result.output
    assert "--verbose" in result.output


def test_format_tool_action_read_skill():
    assert format_tool_action("read_skill", {"name": "analyze"}) == (
        "Reading skill: analyze"
    )


def test_format_tool_action_pick_aoi():
    assert "Para, Brazil" in format_tool_action(
        "pick_aoi", {"question": "tree cover loss in Para, Brazil"}
    )


def test_format_tool_outcome_pick_aoi():
    content = "Selected AOIs:\n- Pará, Brazil\n"
    assert format_tool_outcome("pick_aoi", content) == "Pará, Brazil"


def test_format_tool_outcome_read_skill():
    content = "# Workflow\n\n1. pick_aoi"
    assert format_tool_outcome("read_skill", content) == "Skill loaded"


def test_format_message_content_gemini_blocks():
    msg = AIMessage(
        content=[
            {
                "type": "text",
                "text": "Hello **world**",
                "extras": {"signature": "should-not-appear"},
            }
        ]
    )
    assert format_message_content(msg) == "Hello **world**"


def test_format_message_content_plain_string():
    msg = AIMessage(content="Plain answer")
    assert format_message_content(msg) == "Plain answer"


def test_format_message_content_empty():
    assert format_message_content(AIMessage(content=[])) == ""
    assert format_message_content(AIMessage(content="")) == ""
    assert format_message_content(AIMessage(content="   ")) == ""


def test_format_tool_outcome_read_skill_capabilities():
    content = "## About me\n\nI am an agent.\n\n## Available datasets\n- Foo"
    assert format_tool_outcome("read_skill", content) == "Capabilities loaded"


def test_format_tool_action_read_skill_capabilities():
    assert format_tool_action("read_skill", {"name": "capabilities"}) == (
        "Loading capabilities"
    )


def test_format_tool_outcome_pick_dataset():
    content = """
    Selected dataset name: Tree cover loss
    Selected context layer: None
    Reasoning for selection: Best match for annual loss.
    """
    out = format_tool_outcome("pick_dataset", content)
    assert "Tree cover loss" in out
    assert "Best match" in out


def test_format_state_line_dataset():
    line = format_state_line(
        "dataset",
        {
            "dataset_name": "Tree cover loss",
            "start_date": "2001-01-01",
            "end_date": "2025-12-31",
        },
    )
    assert line == "Dataset: Tree cover loss (2001-01-01 – 2025-12-31)"
