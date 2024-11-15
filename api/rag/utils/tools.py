from langchain.tools.retriever import create_retriever_tool
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
import os

# Vector store
vectorstore = Chroma(
    persist_directory="data/chroma_gfw",
    embedding_function=OllamaEmbeddings(
        model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
    ),
    create_collection_if_not_exists=False,
)
_vectorstore = Chroma(
    persist_directory="data/chroma_db",
    embedding_function=OllamaEmbeddings(
        model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
    ),
)
_vectorstore_data = _vectorstore._collection.get(
    include=["documents", "metadatas", "embeddings"]
)
vectorstore._collection.add(
    embeddings=_vectorstore_data["embeddings"],
    metadatas=_vectorstore_data["metadatas"],
    documents=_vectorstore_data["documents"],
    ids=_vectorstore_data["ids"],
)

retriever = vectorstore.as_retriever()

retriever_tool = create_retriever_tool(
    retriever,
    "retrieve_blog_posts",
    "Search and return information about the World Resources Institute (WRI).",
)
