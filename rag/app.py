import time
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
from pylate import indexes, models, retrieve

_ = load_dotenv()
st.set_page_config(page_title="Zeno Search Engine", layout="wide")


def get_relevant_documents(query, indexer="openai"):
    results = []
    match indexer:
        case "openai":
            match_documents = openai_retriever.invoke(query)
            for doc in match_documents:
                results.append(
                    zeno_data[zeno_data.dataset_id == int(doc.id)]
                    .iloc[0]
                    .to_dict()
                )
        case "colbert":
            query_embedding = colbert_model.encode(
                query, batch_size=1, is_query=True, show_progress_bar=False
            )
            scores = colbert_retriever.retrieve(
                queries_embeddings=query_embedding, k=3
            )
            for score in scores[0]:
                results.append(
                    zeno_data[zeno_data.dataset_id == int(score["id"])]
                    .iloc[0]
                    .to_dict()
                )
        case _:
            raise ValueError(f"Unknown indexer: {indexer}")
    return results


@st.cache_resource(show_spinner=True)
def load_indexes():
    data_dir = Path("data")
    zeno_data = pd.read_csv(data_dir / "zeno_data_clean.csv")

    openai_embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

    openai_index = InMemoryVectorStore.load(
        data_dir / "zeno-docs-openai-index-v3", embedding=openai_embeddings
    )

    openai_retriever = openai_index.as_retriever(
        search_type="similarity", search_kwargs={"k": 3}
    )

    colbert_model = models.ColBERT(
        model_name_or_path="lightonai/GTE-ModernColBERT-v1"
    )
    colbert_index = indexes.PLAID(
        index_folder=data_dir / "colbert-index", index_name="dataset"
    )
    colbert_retriever = retrieve.ColBERT(index=colbert_index)

    return (
        openai_retriever,
        colbert_retriever,
        colbert_model,
        zeno_data,
    )


(
    openai_retriever,
    colbert_retriever,
    colbert_model,
    zeno_data,
) = load_indexes()

queries = [
    "What percent of 2000 forest did Kalimantan Barat lose from 2001 through 2024?",
    "What percent of Johor was tree cover in 2000?",
    "Which year recorded more alerts within Protected Areas in Ucayali, Peru? 2023 or 2024?",
    "Since 2001, do the forests within Gomba's KBAs act as a net carbon source or a net carbon sink, and by how much?",
    "Has Chai Nat or Krabi in Thailand has had the most forest-related annual carbon emissions since 2001?",
    "I'm researching carbon sequestration in Indonesian forests. Specifically, for Key Biodiversity Areas (KBAs), how much carbon has been absorbed from the atmosphere between 2000 and 2024?",
    "How many deforestation alerts were reported in protected areas of the Republic of the Congo april 2024 - april 2025?",
    "which country had the most deforestation in 2018",
]

# UI Controls in Sidebar
with st.sidebar:
    st.title("Zeno Search Engine")
    st.header("Query")
    use_example = st.selectbox(
        "Pick an example query", ["Type your own"] + queries
    )
    if use_example == "Type your own":
        query = st.text_area("Your query:", height=80, key="query_input")
    else:
        query = use_example

    # Use session_state to control when to run
    if "run_query" not in st.session_state:
        st.session_state["run_query"] = False

    if st.button("Run RAG Query", type="primary"):
        st.session_state["run_query"] = True

# Display query at the top of the main area
st.markdown(f"### Current Query\n```{query.strip()}```")

if not query:
    st.info("Select or enter a query in the sidebar.")
    st.session_state["run_query"] = False
    st.stop()

# Only run after submit
if st.session_state.get("run_query"):
    col1, col2, col3 = st.columns(3)
    with st.spinner("Retrieving documents..."):
        t0 = time.perf_counter()
        openai_results = get_relevant_documents(query, "openai")
        t_openai = time.perf_counter() - t0

        t0 = time.perf_counter()
        colbert_results = get_relevant_documents(query, "colbert")
        t_colbert = time.perf_counter() - t0

    def display_results(results, name, elapsed):
        st.markdown(f"**Retrieval Time:** `{elapsed:.2f} sec`")
        if not results:
            st.warning("No results.")
        for idx, ds in enumerate(results):
            # Combine all fields for simple code block
            block = f"""\
[{idx + 1}] {ds["data_layer"]}
-----------------------------
Description: {ds["description"]}
Vars: {ds.get("variables", "")}
Context: {ds.get("context_layer", "")}
Date: {ds.get("date", "")}
Dataset ID: {ds["dataset_id"]}
"""
            st.code(block, language="markdown")

    with col2:
        st.subheader("OpenAI Embedding")
        st.write("text-embed-3-large")
        display_results(openai_results, "OpenAI", t_openai)

    with col3:
        st.subheader("ColBERT")
        st.write("lightonai/GTE-ModernColBERT-v1")
        display_results(colbert_results, "ColBERT", t_colbert)

    # Reset after run so it doesn't rerun automatically
    st.session_state["run_query"] = False
