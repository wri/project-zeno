"""
Module to do chunking of GFW blog posts and create a Chroma vector
database to support a simple RAG agent.
"""

import unicodedata

import pandas as pd
from bs4 import BeautifulSoup
from langchain_chroma.vectorstores import Chroma
from langchain_community.document_loaders import CSVLoader
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Open blog posts from WordPress export
with open("data/gfw-blog-and-help-center-posts.xml") as fl:
    soup = BeautifulSoup(fl, "xml")

# Parse xml and extract blog content as text
bodies = []
titles = []
for item in soup.channel.find_all("item"):
    if not item.find_all("wp:post_id"):
        print(item)
    html = item.find_all("content:encoded")[0]
    sopa = BeautifulSoup(html.contents[0], "html.parser").get_text()
    txt = unicodedata.normalize("NFKC", sopa)
    txt = txt.replace("\n", "")
    bodies.append(txt)

    title = item.title.contents[0]
    titles.append(title)
    break

# Persist resulting data as csv
df = pd.DataFrame({"title": titles, "body": bodies})
df.to_csv("data/gfw-blog.csv", index=False, columns=["title", "body"])

# Load data from csv
loader = CSVLoader(
    file_path="data/gfw-blog.csv",
    source_column="title",
)
docs = loader.load()

# Split into chunks
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1024, chunk_overlap=200)
splits = text_splitter.split_documents(docs)

vectorstore = Chroma.from_documents(
    documents=splits,
    embedding=OllamaEmbeddings(model="nomic-embed-text"),
    persist_directory="data/chroma_gfw",
)
