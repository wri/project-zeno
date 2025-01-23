import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from zeno.agents.layerfinder.prompts import LAYER_FINDER_RAG_PROMPT
from zeno.agents.layerfinder.state import LayerFinderState
from zeno.agents.layerfinder.tool_layer_retrieve import retriever
from zeno.agents.layerfinder.utils import clean_json_response, make_context

model = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)


def retrieve_node(state: LayerFinderState, config: RunnableConfig):
    print("---RETRIEVE---")
    question = state["question"]
    documents = retriever.invoke(question)
    return {"documents": documents}


def generate_node(state: LayerFinderState, config: RunnableConfig):
    print("---GENERATE---")
    question = state["question"]
    documents = state["documents"]
    loop_step = state.get("loop_step", 0)

    # RAG generation
    docs_txt = make_context(documents)
    rag_prompt_fmt = LAYER_FINDER_RAG_PROMPT.format(
        context=docs_txt, question=question
    )

    generation = model.invoke([HumanMessage(content=rag_prompt_fmt)])
    datasets = clean_json_response(generation.content)["datasets"]
    for dataset in datasets:
        dataset["uri"] = (
            f"https://data-api.globalforestwatch.org/dataset/{dataset['dataset']}"
        )
        dataset["tilelayer"] = (
            f"https://tiles.globalforestwatch.org/{dataset['dataset']}/latest/dynamic/{{z}}/{{x}}/{{y}}.png"
        )

    return {
        "messages": json.dumps(datasets),
        "loop_step": loop_step + 1,
    }


wf = StateGraph(LayerFinderState)

wf.add_node("retrieve", retrieve_node)
wf.add_node("generate", generate_node)

wf.add_edge(START, "retrieve")
wf.add_edge("retrieve", "generate")
wf.add_edge("generate", END)

memory = MemorySaver()
graph = wf.compile(checkpointer=memory)
graph.name = "layerfinder"
