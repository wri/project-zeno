import json
import operator
from typing import Annotated, List, TypedDict

from dotenv import load_dotenv

_ = load_dotenv()

import folium
import streamlit as st
from langchain_anthropic import ChatAnthropic
from langchain_chroma import Chroma
from langchain_core.messages import HumanMessage
from langchain_ollama.embeddings import OllamaEmbeddings
from langgraph.graph import StateGraph
from streamlit_folium import st_folium


def make_context(docs):
    fmt_docs = []
    for doc in docs:
        dataset_slug = doc.metadata["dataset"]
        url = f"https://data-api.globalforestwatch.org/dataset/{dataset_slug}"
        tilelayer = f"https://tiles.globalforestwatch.org/{dataset_slug}/latest/dynamic/{{z}}/{{x}}/{{y}}.png"
        content = (
            f"URL: {url}\n"
            f"TILELAYER: {tilelayer}\n"
            f"DESCRIPTION: {doc.page_content}"
        )
        fmt_docs.append(content)
    return "\n\n".join(fmt_docs)


# Initialize RAG components
embedder = OllamaEmbeddings(model="nomic-embed-text")
db = Chroma(persist_directory="../data/chroma_db", embedding_function=embedder)
retriever = db.as_retriever(k=4)
llm = ChatAnthropic(model="claude-3-5-sonnet-20240620", temperature=0)
rag_prompt = """You are a World Resources Institute (WRI) assistant specializing in dataset recommendations.

Instructions:
1. Use the following context to inform your response:
{context}

2. User Question:
{question}

3. Response Format to be a valid JSON with list of datasets that have the following keys:
     - "url": The URL of the dataset
     - "tilelayer": The tile layer information
     - "explanation": A two-line explanation of why this dataset is relevant to the user's problem
Don't add any prefix statements to the response, let it be a JSON.
"""


class GraphState(TypedDict):
    question: str  # User question
    generation: str  # LLM generation
    loop_step: Annotated[int, operator.add]
    documents: List[str]  # List of retrieved documents


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
    return {"generation": generation, "loop_step": loop_step + 1}


# Create the graph
workflow = StateGraph(GraphState)
workflow.add_node("retrieve", retrieve)
workflow.add_node("generate", generate)
workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "generate")
workflow.set_finish_point("generate")
graph = workflow.compile()


# Initialize session state for messages and selected dataset
if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "selected_dataset" not in st.session_state:
    st.session_state["selected_dataset"] = None

# Set the page layout to wide mode
st.set_page_config(layout="wide")
col1, col2 = st.columns([4, 6])

# Left column (40% width) - Chat Interface
with col1:
    st.header("Chat Interface")
    st.write("Ask a question to get dataset recommendations.")

    # User input
    user_input = st.text_input("You:", key="user_input")
    if user_input:
        result = graph.invoke({"question": user_input})
        response = json.loads(result["generation"].content)["datasets"]
        print("RESPONSE", response)

        # Parse the response and extract dataset recommendations
        # Assuming the LLM returns a structured response with dataset info
        try:
            # Store both user input and bot response
            st.session_state["messages"].append({"user": user_input})
            st.session_state["messages"].append({"bot": response})
        except Exception as e:
            st.error(f"Error processing response: {str(e)}")

    # Display the conversation and dataset selection buttons
    for message in st.session_state["messages"]:
        if "user" in message:
            st.write(f"**You**: {message['user']}")
        else:
            st.write("**Assistant**:")
            response = message["bot"]
            try:
                for idx, dataset in enumerate(response):
                    st.write(f"**Dataset {idx+1}:** {dataset['explanation']}")
                    st.write(f"**URL**: {dataset['url']}")
                    st.write(f"**Tilelayer**: {dataset['tilelayer']}")
                    if st.button(
                        f"Show Dataset {idx+1}", key=f"dataset_{idx}"
                    ):
                        st.session_state["selected_dataset"] = dataset[
                            "tilelayer"
                        ]
            except Exception as e:
                st.error(f"Error processing response: {str(e)}")

# Right column (60% width) - Map Visualization
with col2:
    st.header("Map Visualization")
    m = folium.Map(location=[0, 0], zoom_start=2)

    if st.session_state["selected_dataset"]:
        folium.TileLayer(
            tiles=st.session_state["selected_dataset"],
            attr="Global Forest Watch",
            name="Selected Dataset",
            overlay=True,
            control=True,
        ).add_to(m)

    folium.LayerControl().add_to(m)
    st_folium(m, width=700, height=500)
