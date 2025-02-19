import os
from uuid import uuid4

import pandas as pd
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama.embeddings import OllamaEmbeddings

load_dotenv()

df = pd.read_csv("data/gfw_layer_metadata_v20251402_3.csv")
df = df.fillna("")

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
    overview = data.get("overview")
    if not overview:
        print("No overview for", data["gfw_layer_name"])
        continue
    cautions = data.get("cautions")
    geographic_coverage = data.get("geographic_coverage", "")

    data["zeno_id"] = str(uuid4())
    documents.append(
        Document(
            page_content=data["gfw_dataset_name"] + data["gfw_layer_name"] + overview,
            metadata=data,
            id=data["zeno_id"],
        )
    )

uuids = [doc.id for doc in documents]

db.add_documents(documents=documents, ids=uuids)

# Print test search results
print(
    [
        (doc[0].metadata["gfw_layer_name"], doc[1])
        for doc in db.similarity_search_with_relevance_scores(
            query="Fire", k=10, score_threshold=0.3
        )
    ]
)
