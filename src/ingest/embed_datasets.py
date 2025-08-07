"""
https://onewri.sharepoint.com/:x:/s/LandandCarbonWatch/ESllWse7dmFAnobmcA4IMXABbyDYhta0p81qnPH3-XUsBw
"""

from pathlib import Path

import pandas as pd
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings

from src.utils.env_loader import load_environment_variables

load_environment_variables()

# Set absolute path of current file
# SCRIPT_DIR = Path(__file__).parent.absolute()

data_dir = Path("data").absolute()

print(f"Loading zeno data from {data_dir}")

zeno_data = pd.read_csv(data_dir / "zeno_data_clean_v2.csv")

openai_embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

openai_index = InMemoryVectorStore(openai_embeddings)

zeno_docs = []

for idx, row in zeno_data.iterrows():
    content = {
        "DATA_LAYER": row["Layer Title"],
        "DESCRIPTION": row["Description"],
        "CONTEXTUAL_LAYERS": row[
            "Secondary/Contextual layers / Intersections"
        ],
        "DATE": row["Date"],
        "USAGE NOTES": row["Function / usage notes"],
    }

    formatted_content = "\n\n".join(
        [
            f"{key}\n{value}"
            for key, value in content.items()
            if pd.notna(value)
        ]
    )

    zeno_docs.append(
        Document(
            id=row["dataset_id"],
            page_content=formatted_content,
            metadata={
                "dataset_id": row["dataset_id"],
                "tile_url": row["Tile URL(s)"],
                "dataset_name": row["Layer Title"],
                "function_notes": row["Function / usage notes"],
                "providers": row["Providers"],
                "citation": row["Citation"],
                "methodology": row["Methodology"],
                "cautions": row["Cautions"],
                "license": row["License"],
                "geographic_coverage": row["Geographic coverage"],
                "resolution": row["Resolution"],
                "update_frequency": row["Update frequency"],
                "content_date": row["Content date"],
                "keywords": row["Keywords"],
                "prompt_examples": row["Prompt examples"],
                "band_values": row["Band values / meaning"],
                "source": row["Source"],
                "context_layers": row[
                    "Secondary/Contextual layers / Intersections"
                ],
            },
        )
    )

openai_index.add_documents(documents=zeno_docs)

openai_index.dump(data_dir / "zeno-docs-openai-index")
