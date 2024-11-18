from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
import json
from langchain_core.messages import HumanMessage, SystemMessage

from zeno.tools.layerretrieve.layer_retrieve_tool import retriever, retriever_tool
from zeno.tools.glad.weekly_alerts_tool import glad_weekly_alerts_tool
from zeno.tools.location.tool import location_tool
from langgraph.prebuilt import ToolNode


tools = [location_tool, glad_weekly_alerts_tool]

local_llm = "qwen2.5:7b"
# llm = ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0)
llm = ChatOllama(model=local_llm, temperature=0)
llm_with_tools = llm.bind_tools(tools)

llm_json_mode = ChatOllama(model=local_llm, temperature=0, format="json")


rag_prompt = """You are a World Resources Institute (WRI) assistant specializing in dataset recommendations.

Instructions:
1. Use the following context to inform your response:
{context}

2. User Question:
{question}

3. Response Format:
   - Only use information from the provided context
   - For each recommended dataset:
     - Dataset URL
     - Two-line explanation of why this dataset is relevant to the user's problem
"""

router_instructions = """You are an expert at routing a user question to a vectorstore or tool call.
The vectorstore contains details about datasets from World Resource Institute(WRI).
Use the vectorstore for questions on topics related to searching datasets. 
For specific question on forest fires use the tool call.
Return JSON with single key, route, that is 'vectorstore' or 'glad-tool' depending on the question."""


def make_context(docs):
    fmt_docs = []
    for doc in docs:
        url = f"https://data-api.globalforestwatch.org/dataset/{doc.metadata['dataset']}"
        content = "URL: " + url + "\n" + doc.page_content
        fmt_docs.append(content)
    return "\n\n".join(fmt_docs)


def retrieve(state):
    print("---RETRIEVE---")
    question = state["question"]
    documents = retriever.invoke(question)
    return {"documents": documents}

def generate(state):
    print("---GENERATE---")
    question = state["question"]
    documents = state["documents"]
    loop_step = state.get("loop_step", 0)

    # RAG generation
    docs_txt = make_context(documents)
    rag_prompt_fmt = rag_prompt.format(context=docs_txt, question=question)
    generation = llm.invoke([HumanMessage(content=rag_prompt_fmt)])
    return {"messages": [generation], "loop_step": loop_step + 1}

def assistant(state):
    sys_msg = SystemMessage(content="""You are a helpful assistant tasked with answering the user queries for WRI data API.
        Use the `location-tool` to get iso, adm1 & adm2 of any region or place.
        Use the `glad-weekly-alerts-tool` to get forest fire information for a particular year. Think through the solution step-by-step first and then execute.
        
        For eg: If the query is "Find forest fires in Milan for the year 2024"
        Steps
        1. Use the `location_tool` to get iso, adm1, adm2 for place `Milan` by passing `query=Milan`
        2. Pass iso, adm1, adm2 along with year `2024` as args to `glad-weekly-alerts-tool` to get information about forest fire alerts.
        """)
    if not state["messages"]:
        state["messages"] = [HumanMessage(state["question"])]
    return {"messages": [llm_with_tools.invoke([sys_msg] + state["messages"])]}


def router(state):
    print("---ROUTER---")
    response = llm_json_mode.invoke(
        [SystemMessage(content=router_instructions)]
        + [
            HumanMessage(
                content=state["question"]
            )
        ]
    )
    route = json.loads(response.content)["route"]
    if route == "vectorstore":
        print("---ROUTING-TO-RAG---")
        return "retrieve"
    elif route == "glad-tool":
        print("---ROUTING-TO-TOOLS---")
        return "assistant"


tool_node = ToolNode(tools)
