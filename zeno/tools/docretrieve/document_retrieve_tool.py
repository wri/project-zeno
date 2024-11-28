import os

from langchain.tools.retriever import create_retriever_tool
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

# Vector store
vectorstore = Chroma(
    persist_directory="data/chroma_gfw",
    embedding_function=OllamaEmbeddings(
        model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
    ),
    create_collection_if_not_exists=False,
)
retriever = vectorstore.as_retriever()

retriever_tool = create_retriever_tool(
    retriever,
    "retrieve_blog_posts",
    "Search and return information about the World Resources Institute (WRI).",
)
