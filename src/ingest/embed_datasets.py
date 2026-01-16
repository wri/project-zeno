"""
https://onewri.sharepoint.com/:x:/s/LandandCarbonWatch/ESllWse7dmFAnobmcA4IMXABbyDYhta0p81qnPH3-XUsBw
"""

from pathlib import Path

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from src.tools.data_handlers.analytics_handler import DATASETS
from src.utils.config import APISettings
from src.utils.env_loader import load_environment_variables

load_environment_variables()

embeddings = GoogleGenerativeAIEmbeddings(
    model=APISettings.dataset_embeddings_model
)
index = InMemoryVectorStore(embeddings)

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

index.add_documents(documents=analytics_docs)

index.dump(data_dir / APISettings.dataset_embeddings_db)
