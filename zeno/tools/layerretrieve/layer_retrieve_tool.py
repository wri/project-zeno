from langchain.tools.retriever import create_retriever_tool

from langchain_ollama.embeddings import OllamaEmbeddings
from langchain_chroma import Chroma


embedder = OllamaEmbeddings(model="nomic-embed-text")
db = Chroma(
        persist_directory="data/chroma_layers",
        embedding_function=embedder,
        create_collection_if_not_exists=False,
)

retriever = db.as_retriever(k=4)

retriever_tool = create_retriever_tool(
    retriever,
    "retrieve_blog_posts",
    "Search and return information about the World Resources Institute (WRI).",
)
