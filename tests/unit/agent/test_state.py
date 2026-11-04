"""AgentState keys reach the graph state. LangGraph drops a Command update
key that is not in the schema without an error, so these pin the keys the
frontend reads from the stream."""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.agent.state import AgentState

ANALYSIS_INPUTS = [
    {
        "areas": [{"name": "Brazil", "source": "gadm", "src_id": "BRA"}],
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "start_date": "2020-01-01",
        "end_date": "2020-12-31",
        "canopy_cover": 30,
        "context_layer": None,
    }
]


def _run(update: dict) -> dict:
    graph = StateGraph(AgentState)
    graph.add_node("insight", lambda state: Command(update=update))
    graph.add_edge(START, "insight")
    graph.add_edge("insight", END)
    return graph.compile().invoke({"messages": []})


def test_analysis_inputs_survive_a_command_update():
    state = _run(
        {"insight_id": "insight-1", "analysis_inputs": ANALYSIS_INPUTS}
    )
    assert state["analysis_inputs"] == ANALYSIS_INPUTS


def test_a_null_analysis_inputs_is_kept_as_null():
    state = _run({"insight_id": "insight-1", "analysis_inputs": None})
    assert "analysis_inputs" in state
    assert state["analysis_inputs"] is None
