from langgraph.graph import END, START, StateGraph

from src.agent.state import AgentState


def test_parallel_updates_to_the_selection_keep_the_last():
    def first(state):
        return {"dataset": {"dataset_id": 1}, "start_date": "2001-01-01"}

    def second(state):
        return {"dataset": {"dataset_id": 4}, "start_date": "2015-01-01"}

    graph = StateGraph(AgentState)
    graph.add_node("first", first)
    graph.add_node("second", second)
    graph.add_edge(START, "first")
    graph.add_edge(START, "second")
    graph.add_edge("first", END)
    graph.add_edge("second", END)

    state = graph.compile().invoke({"messages": []})

    assert state["dataset"] == {"dataset_id": 4}
    assert state["start_date"] == "2015-01-01"
