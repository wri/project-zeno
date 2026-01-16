#!/usr/bin/env python3
"""
Generate minimal test data files for CI/testing environments.

This script creates the minimum data files needed for the API to start up
during testing, including CSV files and vector indices.
"""

import json
import pickle
from pathlib import Path

import pandas as pd

from src.utils.config import APISettings


def create_test_csv():
    """Create a minimal zeno_data_clean.csv for testing."""
    data = {
        "dataset_id": [0, 1, 2],
        "data_layer": [
            "Tree cover loss",
            "Tree cover loss by dominant driver",
            "Test dataset",
        ],
        "description": [
            "Tree Cover Loss test data for API testing",
            "Tree cover loss drivers test data for API testing",
            "Generic test dataset for API testing",
        ],
        "source": ["GFW", "GFW", "TEST"],
        "tile_url": [
            "https://example.com/test/tile1.png",
            "https://example.com/test/tile2.png",
            "https://example.com/test/tile3.png",
        ],
        "context_layer": [
            "Test context layer 1",
            "Test context layer 2",
            "Test context layer 3",
        ],
        "date": ["2001-2024 annual", "2001-2024", "2020-2024"],
        "variables": [">10, 15, 20, 25%", ">30%", "test variables"],
    }

    df = pd.DataFrame(data)
    return df


def create_mock_vector_index(index_path: Path):
    """Create a minimal mock vector index structure."""
    if index_path.exists():
        if index_path.is_file():
            print(f"⏭️  Skipping {index_path} - file already exists")
            return
        elif index_path.is_dir() and any(index_path.iterdir()):
            print(
                f"⏭️  Skipping {index_path} - directory exists and is not empty"
            )
            return

    index_path.mkdir(parents=True, exist_ok=True)

    # Create a minimal index.json that InMemoryVectorStore expects
    index_config = {
        "type": "InMemoryVectorStore",
        "version": "1.0",
        "num_vectors": 3,
        "dimension": 512,  # Common embedding dimension
    }

    with open(index_path / "index.json", "w") as f:
        json.dump(index_config, f)

    # Create mock embeddings file - InMemoryVectorStore typically looks for this
    mock_embeddings = {
        "embeddings": [
            [0.1] * 512,
            [0.2] * 512,
            [0.3] * 512,
        ],  # 3 mock embeddings
        "documents": [
            {"id": "0", "content": "Tree cover loss dataset"},
            {"id": "1", "content": "Tree cover loss drivers dataset"},
            {"id": "2", "content": "Test dataset"},
        ],
    }

    with open(index_path / "embeddings.pkl", "wb") as f:
        pickle.dump(mock_embeddings, f)

    print(f"✅ Created mock vector index at {index_path}")


def main():
    """Generate all required test data files."""
    print("Generating test data files for CI/testing environment...")

    # Create data directory
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    # 1. Create the main CSV file
    csv_path = data_dir / "zeno_data_clean.csv"
    if csv_path.exists():
        print(f"⏭️  Skipping {csv_path} - file already exists")
    else:
        print("Creating zeno_data_clean.csv...")
        df = create_test_csv()
        df.to_csv(csv_path, index=False)
        print(f"✅ Created {csv_path} with {len(df)} test records")

    # 2. Create mock vector indices
    print("Creating mock vector indices...")
    create_mock_vector_index(data_dir / APISettings.dataset_embeddings_db)

    print("✅ Test data generation complete!")
    print("\nChecked/created files:")
    print(f"  📄 {csv_path}")
    print(f"  📁 {data_dir / APISettings.dataset_embeddings_db}")
    print("\nNote: Existing files were preserved and not overwritten.")


if __name__ == "__main__":
    main()
