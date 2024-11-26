from dotenv import load_dotenv

import json

from tools.layerretrieve.layer_retrieve_tool import retriever, retriever_tool
from langgraph.prebuilt import ToolNode
from langchain_core.runnables.config import RunnableConfig
from agents.maingraph.models import ModelFactory
from langchain_core.messages import HumanMessage


from zeno.tools.layerretrieve.layer_retrieve_tool import retriever

# local_llm = "qwen2.5:7b"
# llm = ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0)
# llm = ChatOllama(model=local_llm, temperature=0)
# llm_with_tools = llm.bind_tools(tools)

# llm_json_mode = ChatOllama(model=local_llm, temperature=0, format="json")


rag_prompt = """You are a World Resources Institute (WRI) assistant specializing in dataset recommendations.

Instructions:
1. Use the following context to inform your response:
{context}

2. User Question:
{question}

3. Response Format to be a valid JSON with list of datasets in the following format:
    {{
        "datasets": [
            {{
                "dataset": The slug of the dataset,
                "explanation": A two-line explanation of why this dataset is relevant to the user's problem
            }},
            ...
        ]
    }}
"""


def clean_json_response(response: str) -> dict:
    """Clean JSON response from LLM by removing any markdown formatting."""
    # Remove markdown code block indicators if present
    cleaned = response.strip().replace("```json", "").replace("```", "")
    # Parse the cleaned string into a dict
    return json.loads(cleaned)


def make_context(docs):
    fmt_docs = []
    for doc in docs:
        dataset = doc.metadata["dataset"]
        content = f"Dataset: {dataset}\n{doc.page_content}"
        fmt_docs.append(content)

    # Join all formatted documents with double newlines
    return "\n\n".join(fmt_docs)


def retrieve(state):
    print("---RETRIEVE---")
    question = state["question"]
    documents = retriever.invoke(question)
    return {"documents": documents}


def generate(state, config: RunnableConfig):
    print("---GENERATE---")
    question = state["question"]
    documents = state["documents"]
    loop_step = state.get("loop_step", 0)

    model_id = config["configurable"].get("model_id")
    model = ModelFactory().get(model_id)

    # RAG generation
    docs_txt = make_context(documents)
    rag_prompt_fmt = rag_prompt.format(context=docs_txt, question=question)

    generation = model.invoke([HumanMessage(content=rag_prompt_fmt)])
    print("\n\n")
    print(generation.content)
    generation_content = clean_json_response(generation.content)
    print(generation_content)
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
        "route": "layerfinder",
    }


# def assistant(state, config: RunnableConfig):
#     sys_msg = SystemMessage(
#         content="""You are a helpful assistant tasked with answering the user queries for WRI data API.
#         Use the `location-tool` to get iso, adm1 & adm2 of any region or place.
#         Use the `glad-weekly-alerts-tool` to get forest fire information for a particular year. Think through the solution step-by-step first and then execute.

#         For eg: If the query is "Find forest fires in Milan for the year 2024"
#         Steps
#         1. Use the `location_tool` to get iso, adm1, adm2 for place `Milan` by passing `query=Milan`
#         2. Pass iso, adm1, adm2 along with year `2024` as args to `glad-weekly-alerts-tool` to get information about forest fire alerts.
#         """
#     )
#     if not state["messages"]:
#         state["messages"] = [HumanMessage(state["question"])]

#     model_id = config["configurable"].get("model_id")
#     model = ModelFactory().get(model_id)

#     llm_with_tools = model.bind_tools(tools)

#     return {"messages": [llm_with_tools.invoke([sys_msg] + state["messages"])]}


# def router(state, config: RunnableConfig):
#     print("---ROUTER---")

#     model_id = config["configurable"].get("model_id")
#     model = ModelFactory().get(model_id, json_mode=True)

#     response = model.invoke(
#         [SystemMessage(content=router_instructions)]
#         + [HumanMessage(content=state["question"])]
#     )
#     route = json.loads(response.content)["route"]
#     if route == "vectorstore":
#         print("---ROUTING-TO-RAG---")
#         return "retrieve"
#     elif route == "glad-tool":
#         print("---ROUTING-TO-TOOLS---")
#         return "assistant"


# tool_node = ToolNode(tools)
