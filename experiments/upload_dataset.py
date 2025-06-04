import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

from langfuse import Langfuse


"""
Parser Template:
---------------
def parse_my_format(row: Dict[str, str]) -> Dict[str, Any]:
    # Extract values from CSV columns
    value1 = row.get("column1", "")
    value2 = row.get("column2", "")

    # Process/transform the values as needed
    processed_data = {...}

    # Must return dict with 'expected_output' key
    return {"expected_output": processed_data}

Example usage:
    config = ColumnConfig(
        input_column="query",  # Column containing the input text
        parser=parse_my_format
    )
    upload_csv("my_dataset", "path/to/file.csv", config)
"""


# This is an example CSV parser
def parse_simple_location(row: Dict[str, str]) -> Dict[str, Any]:
    """Example parser for simple location datasets with single values.

    Expected CSV columns:
    - location: location name (e.g., "Paris, France")
    - code: location code (e.g., "FR-PAR")
    - population: population number (optional)

    Returns:
        {"expected_output": {"location": "Paris, France", "code": "FR-PAR", "population": "2000000"}}
    """
    expected = {
        "location": row.get("location", ""),
        "code": row.get("code", ""),
    }

    # Include optional fields if present
    if "population" in row:
        expected["population"] = row["population"]

    return {"expected_output": expected}


@dataclass
class ColumnConfig:
    input_column: str  # Column name for the input text
    parser: Callable[
        [Dict[str, str]], Dict[str, Any]
    ]  # Function to parse row into expected_output


# Usage:
# gadm_config = ColumnConfig(input_column="text", parser=parse_gadm_location)
# create_langfuse_dataset("s2_gadm_0_1")
# upload_csv("s2_gadm_0_1", "experiments/Zeno test dataset(S2 GADM 0-1).csv", gadm_config)

langfuse = Langfuse(
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    host=os.getenv("LANGFUSE_HOST"),
)


def create_langfuse_dataset(dataset_name):
    langfuse.create_dataset(name=dataset_name)


def insert_langfuse_item(dataset_name, input, expected_output, filename):
    langfuse.create_dataset_item(
        dataset_name=dataset_name,
        # any python object or value, optional
        input=input,
        # any python object or value, optional
        expected_output=expected_output,
        metadata={"filename": filename},
    )


def as_expected_gadm_output(location_name, gadm_id):
    return {"name": location_name, "gadm_id": gadm_id}


def parse_gadm_location(row: Dict[str, str]) -> Dict[str, Any]:
    """Parser for GADM location datasets with 'id' and 'name' columns.

    Expected CSV columns:
    - id: semicolon-separated GADM IDs (e.g., "USA.1_1;USA.2_1")
    - name: semicolon-separated location names (e.g., "California;Texas")

    Args:
        row: Dict with CSV column names as keys

    Returns:
        Dict with 'expected_output' key containing list of location objects:
        {"expected_output": [{"name": "California", "gadm_id": "USA.1_1"}, ...]}
    """
    gadm_ids_str = row.get("id", "")
    location_names_str = row.get("name", "")

    gadm_ids = [gid.strip() for gid in gadm_ids_str.split(";") if gid.strip()]
    location_names = [
        name.strip() for name in location_names_str.split(";") if name.strip()
    ]

    expected_output = []
    for gadm_id, location_name in zip(gadm_ids, location_names):
        expected_output.append({"name": location_name, "gadm_id": gadm_id})

    return {"expected_output": expected_output}


def upload_csv(dataset_name: str, csv_filepath: str, config: ColumnConfig):
    """Uploads rows from a CSV file to a Langfuse dataset using the provided configuration."""
    try:
        with open(csv_filepath, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            csv_filename = Path(csv_filepath).name

            for row_number, row in enumerate(reader, 1):
                input_text = row.get(config.input_column)

                if input_text is None:
                    print(
                        f"Skipping row {row_number} due to missing input column '{config.input_column}': {row}"
                    )
                    continue

                try:
                    parsed_data = config.parser(row)
                    expected_output = parsed_data.get("expected_output", {})

                    insert_langfuse_item(
                        dataset_name=dataset_name,
                        input=input_text,
                        expected_output=expected_output,
                        filename=csv_filename,
                    )
                except Exception as e:
                    print(f"Error parsing row {row_number}: {e}")
                    continue

        print(
            f"Successfully processed data from {csv_filename} for dataset {dataset_name}"
        )
    except FileNotFoundError:
        print(f"Error: The file {csv_filepath} was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")
