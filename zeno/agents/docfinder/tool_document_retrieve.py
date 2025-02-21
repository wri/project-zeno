import os

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

vectorstore = Chroma(
    persist_directory="data/chroma_gfw",
    embedding_function=OllamaEmbeddings(
        model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
    ),
    create_collection_if_not_exists=False,
)
