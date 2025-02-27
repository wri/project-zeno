"""
Module to do chunking of GFW blog posts and create a Chroma vector
database to support a simple RAG agent.
"""

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from langchain_chroma.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

data = pd.read_csv("data/gfw_blog_titles_links.csv", index_col=0)

FIXTURES = {
    175: "https://www.wri.org/insights/amazon-forest-fires-2024",
    181: "https://www.wri.org/insights/how-mining-impacts-forests",
    186: "https://www.wri.org/insights/rethinking-definition-forest-monitoring",
    204: "https://www.wri.org/insights/europe-forest-loss-drivers",
    206: "https://www.wri.org/insights/canada-wildfire-emissions",
    214: "",
    216: "",
    218: "",
    231: "https://www.wri.org/insights/los-angeles-fires-january-2025-explained"
}

documents = []
for idx, row in data.iterrows():
    if not isinstance(row.content, str):
        print("No content for", idx, row.title, row.link)
        continue
    content = BeautifulSoup(row.content, "html.parser").get_text()
    data = row.to_dict()
    data.pop("content")
    documents.append(
        Document(
            page_content=content,
            metadata=data,
        )
    )

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1024, chunk_overlap=200)
splits = text_splitter.split_documents(documents)

vectorstore = Chroma.from_documents(
    documents=splits,
    embedding=OllamaEmbeddings(model="nomic-embed-text"),
    persist_directory="data/chroma_gfw",
)
