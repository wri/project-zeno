"""Unit tests for the Langfuse trace parser (src/api/services/langfuse/parse.py).

Fixtures are synthetic but mirror the real ``AgentState`` snapshot shape (no real
user text committed). The contract tests at the bottom bind to the live
src/agent contract so a drift there fails CI loudly.
"""

from src.api.services.langfuse import parse as P


# --------------------------------------------------------------------------- #
# message builders (mirror real trace message shapes)
# --------------------------------------------------------------------------- #
def human(text):
    return {"type": "human", "content": text}


def ai(text, tool_calls=None, finish="stop", usage=None):
    m = {
        "type": "ai",
        "content": text,
        "response_metadata": {"finish_reason": finish},
    }
    if tool_calls is not None:
        m["tool_calls"] = tool_calls
    if usage is not None:
        m["usage_metadata"] = usage
    return m


def tool(name, content="", status="success", tcid="tc"):
    return {
        "type": "tool",
        "name": name,
        "content": content,
        "status": status,
        "tool_call_id": tcid,
    }


def usage(i, o, cache=0):
    return {
        "input_tokens": i,
        "output_tokens": o,
        "total_tokens": i + o,
        "input_token_details": {"cache_read": cache},
    }


def trace(output, inp=None):
    return {"output": output, "input": inp or {"messages": []}}


# --------------------------------------------------------------------------- #
# outcome classification
# --------------------------------------------------------------------------- #
def test_answer_with_tools():
    out = {
        "messages": [
            human("Analyse tree cover loss in Brazil"),
            ai(
                "",
                tool_calls=[{"name": "pull_data", "id": "1", "args": {}}],
                usage=usage(100, 5),
            ),
            tool("pull_data", "ok"),
            ai(
                "Here is the analysis.", finish="end_turn", usage=usage(50, 30)
            ),
        ],
        "aoi_selection": {
            "name": "Brazil",
            "aois": [
                {"name": "Brazil", "subtype": "country", "source": "gadm"}
            ],
        },
        "statistics": [{"id": "s1", "dataset_name": "Tree cover loss"}],
        "insight_id": "ins-1",
        "insight": "...",
    }
    r = P.parse_trace(trace(out))
    assert r["outcome"] == "ANSWER"
    assert r["has_answer"] is True
    assert r["had_tool_call"] is True
    assert r["aoi_name"] == "Brazil"
    assert r["aoi_type"] == "country"
    assert r["has_insight"] is True
    assert r["insight_id"] == "ins-1"
    assert r["primary_dataset_name"] == "Tree cover loss"
    assert r["derived"]["statistics_ids"] == ["s1"]
    assert r["recognized_contract"] is True


def test_defer_no_tools():
    out = {
        "messages": [
            human("What can you do?"),
            ai(
                "I can analyse land data.",
                finish="end_turn",
                usage=usage(10, 5),
            ),
        ]
    }
    r = P.parse_trace(trace(out))
    assert r["outcome"] == "DEFER"
    assert r["had_tool_call"] is False


def test_refusal_is_soft_error():
    out = {
        "messages": [
            human("Do X"),
            ai(
                "I'm sorry, I cannot help with that.",
                finish="end_turn",
                usage=usage(10, 5),
            ),
        ]
    }
    r = P.parse_trace(trace(out))
    assert r["answer_is_refusal"] is True
    assert r["outcome"] == "SOFT_ERROR"


def test_recovered_tool_error_is_not_error():
    """A tool result with status=error inside the active turn must NOT flip the
    outcome to ERROR when the agent still produced a good answer (tracey's bug)."""
    out = {
        "messages": [
            human("Analyse X"),
            ai(
                "",
                tool_calls=[
                    {"name": "generate_insights", "id": "1", "args": {}}
                ],
                usage=usage(10, 2),
            ),
            tool("generate_insights", "Analysis failed: 503", status="error"),
            ai(
                "Here is the analysis anyway.",
                finish="end_turn",
                usage=usage(20, 8),
            ),
        ]
    }
    r = P.parse_trace(trace(out))
    assert r["tool_error_count"] == 1
    assert r["has_answer"] is True
    assert r["outcome"] == "ANSWER"


def test_empty_output_is_empty_outcome_and_na_contract():
    r = P.parse_trace(
        trace(None, inp={"messages": [human("How much forest was lost?")]})
    )
    assert r["outcome"] == "EMPTY"
    assert r["has_answer"] is False
    # prompt still recovered from input
    assert r["prompt"] == "How much forest was lost?"
    # output absent => contract recognition is N/A, not a violation
    assert r["recognized_contract"] is None


# --------------------------------------------------------------------------- #
# turn-level attribution (the key correctness property)
# --------------------------------------------------------------------------- #
def test_turn_level_tokens_not_inflated_across_thread():
    """output.messages carries the whole thread; per-turn metrics must reflect
    only the active (latest) turn, not the accumulated history."""
    out = {
        "messages": [
            # --- turn 1 (should be excluded) ---
            human("Question 1"),
            ai(
                "",
                tool_calls=[{"name": "pull_data", "id": "1", "args": {}}],
                usage=usage(1000, 100),
            ),
            tool("pull_data", "ok"),
            ai("Answer 1", finish="end_turn", usage=usage(500, 200)),
            # --- turn 2 (the active turn) ---
            human("Question 2"),
            ai("Answer 2", finish="end_turn", usage=usage(30, 5)),
        ]
    }
    r = P.parse_trace(trace(out))
    assert r["prompt"] == "Question 2"
    assert r["answer"] == "Answer 2"
    assert r["turn_input_tokens"] == 30  # NOT 1000+500+30
    assert r["turn_output_tokens"] == 5  # NOT 100+200+5
    assert r["turn_tool_calls"] == 0  # turn 2 used no tools


def test_synthetic_human_message_skipped_for_prompt():
    out = {
        "messages": [
            human("User selected AOI: Brazil"),
            human("Show me real deforestation data"),
            ai("Here you go.", finish="end_turn", usage=usage(10, 5)),
        ]
    }
    r = P.parse_trace(trace(out))
    assert r["prompt"] == "Show me real deforestation data"


# --------------------------------------------------------------------------- #
# state parsing
# --------------------------------------------------------------------------- #
def test_global_aoi():
    out = {
        "messages": [
            human("Compare all countries"),
            ai("Done.", finish="end_turn", usage=usage(5, 5)),
        ],
        "aoi_selection": {
            "name": "All countries in the world",
            "aois": [
                {"name": "Brazil", "subtype": "country", "source": "gadm"}
            ],
        },
    }
    r = P.parse_trace(trace(out))
    assert r["is_global"] is True


def test_cumulative_datasets_and_ids():
    out = {
        "messages": [
            human("Q"),
            ai("A", finish="end_turn", usage=usage(5, 5)),
        ],
        "statistics": [
            {"id": "s1", "dataset_name": "Dataset A"},
            {"id": "s2", "dataset_name": "Dataset B"},
            {"id": "s3", "dataset_name": "Dataset A"},  # dup name
        ],
    }
    r = P.parse_trace(trace(out))
    assert r["derived"]["statistics_ids"] == ["s1", "s2", "s3"]
    assert r["derived"]["datasets_analysed_cumulative"] == [
        "Dataset A",
        "Dataset B",
    ]


def test_unknown_output_key_is_flagged_but_recognized():
    out = {
        "messages": [
            human("Q"),
            ai("A", finish="end_turn", usage=usage(5, 5)),
        ],
        "forecast": {"some": "new state key"},  # additive drift
    }
    r = P.parse_trace(trace(out))
    assert r["derived"]["unknown_output_keys"] == ["forecast"]
    assert r["recognized_contract"] is True


def test_malformed_dict_output_flags_unrecognized():
    # a dict output without 'messages' is a genuine contract anomaly
    r = P.parse_trace(
        {"output": {"aoi_selection": {}}, "input": {"messages": []}}
    )
    assert r["recognized_contract"] is False


def test_does_not_crash_on_garbage():
    for bad in [{}, {"output": []}, {"output": {"messages": [None, "x", 3]}}]:
        P.parse_trace(bad)  # should not raise


# --------------------------------------------------------------------------- #
# contract tests: bind to the live agent contract so drift fails CI
# --------------------------------------------------------------------------- #
def test_expected_state_keys_match_agent_state():
    from src.agent.state import AgentState

    assert P.EXPECTED_STATE_KEYS == set(AgentState.__annotations__), (
        "AgentState changed: update EXPECTED_STATE_KEYS in parse.py (and consider "
        "whether the new/removed key needs parsing + a PARSER_VERSION bump)."
    )


def test_global_aoi_name_matches_agent_constant():
    from src.agent.subagents.pick_aoi.global_queries import (
        GLOBAL_AOI_SELECTION_NAME,
    )

    assert GLOBAL_AOI_SELECTION_NAME in P.GLOBAL_AOI_NAMES, (
        "GLOBAL_AOI_SELECTION_NAME changed in the agent: update GLOBAL_AOI_NAMES "
        "in parse.py or is_global will silently break."
    )
