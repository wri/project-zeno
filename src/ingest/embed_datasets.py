"""Build the dataset embeddings index from the catalog.

https://onewri.sharepoint.com/:x:/s/LandandCarbonWatch/ESllWse7dmFAnobmcA4IMXABbyDYhta0p81qnPH3-XUsBw

The index is a build artifact of `src/agent/datasets/catalog/`. Every catalog
change (a dataset added, removed or reworded) needs a rebuild, or retrieval
keeps returning documents the catalog no longer has and cannot return the ones
it gained. See `_log_index_catalog_skew` in the pick_dataset tool.

Publish under a NEW version name each time. Do not overwrite a published
name: pods sync the index from S3 and pin it with DATASET_EMBEDDINGS_DB, so
one name with two contents makes the deployed index impossible to identify.

    DATASET_EMBEDDINGS_DB=gnw-dataset-index-gemini-v<N+1> \
        uv run python src/ingest/embed_datasets.py
    aws s3 cp data/gnw-dataset-index-gemini-v<N+1> s3://zeno-static-data/

Then point DATASET_EMBEDDINGS_DB in the Helm values (project-zeno-deploy) and
the default in `src.shared.config` at the new name.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from src.agent.datasets.handlers.analytics_handler import DATASETS
from src.shared.config import SharedSettings

load_dotenv()

embeddings = GoogleGenerativeAIEmbeddings(
    model=SharedSettings.dataset_embeddings_model,
    task_type="RETRIEVAL_DOCUMENT",
)
index = InMemoryVectorStore(embeddings)

data_dir = Path("data").absolute()

analytics_docs = []

for ds in DATASETS:
    content = {
        "DATA_LAYER": ds["dataset_name"],
        "DESCRIPTION": ds["description"],
        "SELECTION_HINTS": ds["selection_hints"],
        "CONTEXTUAL_LAYERS": ds["context_layers"],
        "DATE": ds["content_date"],
        "USAGE NOTES": ds["function_usage_notes"],
        "PARAMETERS": ds.get("parameters"),
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

print(
    f"Dumping dataset embeddings to database {SharedSettings.dataset_embeddings_db}..."
)

out_path = data_dir / SharedSettings.dataset_embeddings_db
index.dump(out_path)

# Verify the dump before it is published: the doc ids must be exactly the
# catalog dataset ids. A mismatch here means the file is unusable.
catalog_ids = sorted(ds["dataset_id"] for ds in DATASETS)
dumped_ids = sorted(int(doc_id) for doc_id in index.store)
if dumped_ids != catalog_ids:
    print(
        f"ERROR: {out_path} holds dataset ids {dumped_ids}, "
        f"but the catalog holds {catalog_ids}.",
        file=sys.stderr,
    )
    sys.exit(1)

print(
    f"Wrote {out_path} with {len(dumped_ids)} datasets, ids {catalog_ids}. "
    "Publish it under this name only; never overwrite a published name."
)
