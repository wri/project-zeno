import os
from uuid import uuid4

import pandas as pd
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama.embeddings import OllamaEmbeddings

load_dotenv()

df = pd.read_csv("data/gfw_layer_metadata_v20251402.csv", index_col=0)

embedder = OllamaEmbeddings(
    model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
)
db = Chroma(
    persist_directory="data/chroma_layers",
    embedding_function=embedder,
    create_collection_if_not_exists=True,
)

documents = []
for rownr, row in df.iterrows():
    data = row.to_dict()
    overview = f"Overview: \n {data.get('overview')} \n"
    cautions = f"Cautions: \n {data.get('cautions')}"
    geographic_coverage = f"Geograhic coverage: \n {data.get('geographic_coverage')}"
    data["zeno_id"] = str(uuid4())
    documents.append(
        Document(
            page_content=overview + cautions + geographic_coverage,
            metadata=data,
            id=data["zeno_id"],
        )
    )

uuids = [doc.id for doc in documents]

db.add_documents(documents=documents, ids=uuids)
