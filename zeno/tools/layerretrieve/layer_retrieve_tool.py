import os

from langchain.tools.retriever import create_retriever_tool
from langchain_chroma import Chroma
from langchain_ollama.embeddings import OllamaEmbeddings

embedder = OllamaEmbeddings(
    model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
)
db = Chroma(
    persist_directory="data/chroma_layers",
    embedding_function=embedder,
    create_collection_if_not_exists=False,
)

retriever = db.as_retriever(k=4)

retriever_tool = create_retriever_tool(
    retriever,
    "retrieve_data_layers",
    "Search and return layers about from the World Resources Institute and Land and Carbon Lab.",
)
