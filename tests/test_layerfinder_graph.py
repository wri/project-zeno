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
            datasets = update[node]["validated_documents"]
            prodes = [
                dataset for dataset in datasets if "inpe_prodes" in dataset.dataset
            ]
            assert len(prodes) == 1
            prodes = prodes[0]
            assert (
                prodes.uri
                == "https://data-api.globalforestwatch.org/dataset/inpe_prodes"
            )
            assert (
                prodes.tilelayer
                == "https://tiles.globalforestwatch.org/inpe_prodes/latest/dynamic/{z}/{x}/{y}.png"
            )

    assert nodes == ["retrieve"]


def test_layerfinder_agent_detail():
    query = "Suggest datasets to understand deforestation in Brazil"
    layerfinder.invoke(
        {"question": query},
        config={"configurable": {"thread_id": "test"}},
    )
    stream = layerfinder.stream(
        {"question": query, "ds_id": "inpe_prodes"},
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
