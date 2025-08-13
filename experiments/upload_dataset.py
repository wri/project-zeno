import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

from langfuse import Langfuse

# Usage:
# create_langfuse_dataset("s2_gadm_0_1")
# gadm_config = ColumnConfig(input_column="text", parser=parse_gadm_location)
# upload_csv("s2_gadm_0_1", "experiments/Zeno test dataset(S2 GADM 0-1).csv", gadm_config)
#
# create_langfuse_dataset("s5_t2_02_investigator")
# tree_cover_config = ColumnConfig( input_column="Question", parser=parse_tree_cover_qa)
# upload_csv("s5_t2_02_investigator", "experiments/Zeno test dataset(S5 T2-02 Investigator).csv", tree_cover_config)
#
# create_langfuse_dataset("s2_t1_02_tcl_identification")
# tcl_config = ColumnConfig( input_column="query", parser=parse_tree_cover_loss_identification)
# upload_csv( "s2_t1_02_tcl_identification", "experiments/S2 T1-02 TCL(TCL dataset ID).csv", tcl_config)

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


def parse_tree_cover_qa(row: Dict[str, str]) -> Dict[str, Any]:
    """Parser for tree cover Q&A datasets with questions and expert answers.

    Expected CSV columns:
    - Question: the question text (used as input)
    - Answer*: any column starting with "Answer" (e.g., "Answer (definitive answer based on GFW dashboards)")
    - Notes: additional context (e.g., "2010, 30%")

    Returns:
        {"expected_output": {"answer": "...", "notes": "..."}}
    """
    expected = {
        "answer": next(
            (v.strip() for k, v in row.items() if k.startswith("Answer")), ""
        ),
    }

    # Include notes if present
    notes = row.get("Notes", "").strip()
    if notes:
        expected["notes"] = notes

    return {"expected_output": expected}


def parse_tree_cover_loss_identification(
    row: Dict[str, str],
) -> Dict[str, Any]:
    """Parser for tree cover loss identification datasets.

    Expected CSV columns:
    - query: the query text (used as input)
    - expected_data_layer: data layer specification, may have "ANY:" prefix for multiple options
    - expected_context_layer: context layer specification
    - expected_daterange: date range specification
    - expected_threshold: threshold specification

    Returns:
        For single data_layer:
        {"expected_output": {"data_layer": "...", "context_layer": "...", "daterange": "...", "threshold": "..."}}
        For multiple data_layer options (ANY: prefix):
        {"expected_output": {"data_layer": {"any_of": [...]}, "context_layer": "...", "daterange": "...", "threshold": "..."}}
    """
    data_layer_str = row.get("expected_data_layer", "").strip()
    data_layer_output: Any

    # Handle ANY: prefix for multiple valid options
    if data_layer_str.startswith("ANY:"):
        # Remove "ANY:" prefix and split by semicolon
        data_layer_content = data_layer_str[len("ANY:") :].strip()
        options = [
            item.strip()
            for item in data_layer_content.split(";")
            if item.strip()
        ]
        data_layer_output = {"any_of": options}
    else:
        # Single option
        data_layer_output = data_layer_str

    expected = {
        "data_layer": data_layer_output,
        "context_layer": row.get("expected_context_layer", "").strip(),
        "daterange": row.get("expected_daterange", "").strip(),
        "threshold": row.get("expected_threshold", "").strip(),
    }

    return {"expected_output": expected}


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
