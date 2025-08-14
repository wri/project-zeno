"""
https://onewri.sharepoint.com/:x:/s/LandandCarbonWatch/ESllWse7dmFAnobmcA4IMXABbyDYhta0p81qnPH3-XUsBw
"""

from pathlib import Path

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings

from src.tools.pick_dataset import DATASETS
from src.utils.env_loader import load_environment_variables

load_environment_variables()

openai_embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

openai_index = InMemoryVectorStore(openai_embeddings)

data_dir = Path("data").absolute()

analytics_docs = []

for ds in DATASETS:
    content = {
        "DATA_LAYER": ds["dataset_name"],
        "DESCRIPTION": ds["description"],
        "CONTEXTUAL_LAYERS": ds["context_layers"],
        "DATE": ds["content_date"],
        "USAGE NOTES": ds["function_usage_notes"],
    }

    formatted_content = "\n\n".join(
        [
            f"{key}\n{value}"
            for key, value in content.items()
            if value is not None
        ]
    )

    analytics_docs.append(
        Document(
            id=ds["dataset_id"],
            page_content=formatted_content,
        )
    )

openai_index.add_documents(documents=analytics_docs)

openai_index.dump(data_dir / "zeno-docs-openai-index")
