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
# output transport shape
# --------------------------------------------------------------------------- #
def test_json_string_output_is_decoded_not_silently_zeroed():
    """A trace whose output arrives as a JSON string must still parse. It used
    to zero every metric AND report the contract as N/A rather than violated,
    so nothing flagged it."""
    import json as _json

    out = {
        "messages": [
            human("Q"),
            ai("A", finish="end_turn", usage=usage(30, 5)),
        ]
    }
    r = P.parse_trace(trace(_json.dumps(out)))
    assert r["turn_tokens"] == 35
    assert r["answer"] == "A"
    assert r["recognized_contract"] is True


def test_double_encoded_output_is_decoded():
    """The shape a Langfuse UI export actually produces."""
    import json as _json

    out = {"messages": [human("Q"), ai("A", finish="end_turn")]}
    r = P.parse_trace(trace(_json.dumps(_json.dumps(out))))
    assert r["answer"] == "A"
    assert r["recognized_contract"] is True


def test_json_string_input_is_decoded_for_the_prompt():
    import json as _json

    inp = _json.dumps({"messages": [human("How much forest was lost?")]})
    r = P.parse_trace(trace(None, inp=inp))
    assert r["prompt"] == "How much forest was lost?"


def test_undecodable_output_still_reports_not_applicable():
    for bad in ["not json at all", '"a bare string"', "[]", "42"]:
        r = P.parse_trace(trace(bad))
        assert r["recognized_contract"] is None
        assert r["outcome"] == "EMPTY"


# --------------------------------------------------------------------------- #
# usage from observations (the agent/tool split)
# --------------------------------------------------------------------------- #
def gen(oid, parent=None, inp=0, out=0, cache=0, cost=0.0, name="ChatModel"):
    """A GENERATION observation, shaped like the Langfuse observations API."""
    total = inp + out + cache
    return {
        "id": oid,
        "parentObservationId": parent,
        "type": "GENERATION",
        "name": name,
        "usageDetails": {
            "input": inp,
            "output": out,
            "total": total,
            "input_cache_read": cache,
        },
        "totalCost": cost,
    }


def span(oid, name, otype="CHAIN", parent=None):
    return {
        "id": oid,
        "parentObservationId": parent,
        "type": otype,
        "name": name,
    }


def agent_turn_observations():
    """The real shape: LangGraph > model > generation for the agent's own call,
    LangGraph > tools > TOOL > RunnableSequence > generation for a tool's."""
    return [
        span("root", "LangGraph"),
        span("m1", "model", parent="root"),
        gen("g1", parent="m1", inp=2000, out=50, cache=4000, cost=0.001),
        span("t1", "tools", parent="root"),
        span("tool1", "pick_aoi", otype="TOOL", parent="t1"),
        span("seq1", "RunnableSequence", parent="tool1"),
        gen("g2", parent="seq1", inp=1400, out=40, cost=0.0008),
    ]


def test_observations_split_agent_from_tool_spend():
    u = P.parse_observations(agent_turn_observations())
    assert u["agent_tokens"] == 6050  # 2000 + 50 + 4000 cached
    assert u["tool_tokens"] == 1440
    assert u["turn_tokens"] == 7490
    assert u["agent_cost"] == 0.001
    assert u["tool_cost"] == 0.0008
    assert u["generation_count"] == 2
    assert u["tokens_by_component"] == {"agent": 6050, "pick_aoi": 1440}
    assert u["cost_by_component"] == {"agent": 0.001, "pick_aoi": 0.0008}


def test_agent_plus_tool_always_equals_turn():
    """The invariant the columns are documented on: whatever the component
    labels turn out to be, the two halves must reconstruct the total."""
    u = P.parse_observations(agent_turn_observations())
    assert u["agent_tokens"] + u["tool_tokens"] == u["turn_tokens"]


def test_cached_input_tokens_are_added_back_into_input():
    """Langfuse excludes cached tokens from `input`; LangChain's usage_metadata
    includes them. The columns keep LangChain's meaning, or the series would
    silently drop by the cache-hit rate."""
    u = P.parse_observations(
        [
            span("root", "LangGraph"),
            gen("g", parent="root", inp=100, out=10, cache=900),
        ]
    )
    assert u["turn_input_tokens"] == 1000
    assert u["cache_read_tokens"] == 900


def test_generation_outside_agent_and_tools_is_other_not_agent():
    """A manually instrumented span must not be silently credited to the agent."""
    obs = [span("root", "LangGraph"), gen("g", parent="root", inp=10, out=1)]
    u = P.parse_observations(obs)
    assert u["tokens_by_component"] == {P.OTHER_COMPONENT: 11}
    assert u["agent_tokens"] == 0
    assert u["tool_tokens"] == 11


def test_component_walk_survives_a_parent_cycle():
    """Defensive: a cycle in parentObservationId must not hang ingestion."""
    a = {"id": "a", "parentObservationId": "b", "type": "CHAIN", "name": "a"}
    b = {"id": "b", "parentObservationId": "a", "type": "CHAIN", "name": "b"}
    g = gen("g", parent="a", inp=5, out=1)
    u = P.parse_observations([a, b, g])
    assert u["turn_tokens"] == 6


def test_component_attribution_needs_the_ancestor_spans():
    """Why the ingest layer fetches every observation type, not just
    generations: the agent/tool label lives on a generation's ANCESTORS. Both
    an agent call and a tool's call are named "ChatGoogleGenerativeAI", so with
    the parents missing the whole turn reads as non-agent spend."""
    gens_only = [
        o for o in agent_turn_observations() if o["type"] == "GENERATION"
    ]
    u = P.parse_observations(gens_only)
    assert u["turn_tokens"] == 7490  # the totals still come out right
    assert u["tokens_by_component"] == {P.OTHER_COMPONENT: 7490}
    assert u["agent_tokens"] == 0


def test_no_observations_falls_back_to_message_usage():
    out = {
        "messages": [
            human("Q"),
            ai("A", finish="end_turn", usage=usage(30, 5)),
        ]
    }
    r = P.parse_trace(trace(out))
    assert r["derived"]["usage_source"] == "messages"
    assert r["turn_tokens"] == 35
    # The split would be a lie without observations, so it is left unset.
    assert "agent_tokens" not in r


def test_observations_take_over_the_token_columns():
    out = {
        "messages": [
            human("Q"),
            ai("A", finish="end_turn", usage=usage(6000, 50)),
        ]
    }
    r = P.parse_trace(trace(out), agent_turn_observations())
    assert r["derived"]["usage_source"] == "observations"
    assert r["turn_tokens"] == 7490  # includes the tool's 1440
    # The message stream is kept as an independent measurement of the same
    # agent-level calls, so a divergence between the two is a drift signal.
    assert r["derived"]["agent_tokens_from_messages"] == 6050


def test_split_drift_flag_is_true_when_both_measurements_agree():
    out = {
        "messages": [
            human("Q"),
            ai("A", finish="end_turn", usage=usage(6000, 50)),
        ]
    }
    r = P.parse_trace(trace(out), agent_turn_observations())
    assert r["derived"]["usage_split_agrees"] is True


def test_split_drift_flag_goes_false_if_the_agent_node_is_renamed():
    """The failure a fill-rate check cannot see: attribution breaks, every call
    lands in `other`, and agent_tokens is 0 rather than null."""
    observations = [
        # LangGraph renamed its model node; the parent walk no longer matches.
        o if o.get("name") != "model" else {**o, "name": "call_model"}
        for o in agent_turn_observations()
    ]
    out = {
        "messages": [
            human("Q"),
            ai("A", finish="end_turn", usage=usage(6000, 50)),
        ]
    }
    r = P.parse_trace(trace(out), observations)
    assert r["agent_tokens"] == 0
    assert r["derived"]["usage_split_agrees"] is False


def test_total_cost_falls_back_to_the_observation_sum():
    """trace.totalCost is frequently null even when the observations under it
    are priced -- that is why cost-per-query read as empty."""
    t = trace({"messages": []})
    t["totalCost"] = None
    r = P.parse_trace(t, agent_turn_observations())
    assert r["total_cost"] == 0.0018


def test_trace_total_cost_wins_when_langfuse_provides_it():
    t = trace({"messages": []})
    t["totalCost"] = 0.5
    r = P.parse_trace(t, agent_turn_observations())
    assert r["total_cost"] == 0.5


def test_observation_parsing_tolerates_junk():
    for bad in [
        None,
        [],
        [{}],
        [None],
        [{"type": "SPAN"}],
        [{"type": "GENERATION"}],
    ]:
        P.parse_observations(bad)  # must not raise


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
