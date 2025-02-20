from zeno.agents.layerfinder.graph import graph as layerfinder


def test_layerfinder_agent():
    query = "Suggest datasets to understand deforestation in Brazil"
    stream = layerfinder.stream(
        {"question": query},
        stream_mode="updates",
        config={"configurable": {"thread_id": "test"}},
    )
    nodes = []
    for update in stream:
        node = next(iter(update.keys()))
        nodes.append(node)
        if node == "retrieve":
            if not update[node]:
                continue
            datasets = update[node]["datasets"]
            assert len(datasets) > 0
        if node == "cautions":
            pass

    assert nodes == ["retrieve", "cautions"]


def test_layerfinder_agent_detail():
    query = "Suggest datasets that are fire related"
    layerfinder.invoke(
        {"question": query},
        config={"configurable": {"thread_id": "test"}},
    )
    stream = layerfinder.stream(
        {"question": query},
        stream_mode="updates",
        config={"configurable": {"thread_id": "test"}},
    )
    query = "Can you provide more detail about this dataset?"
    nodes = []
    for update in stream:
        node = next(iter(update.keys()))
        print("node", node)
        print("update", update)
        nodes.append(node)
    assert nodes == ["detail"]
