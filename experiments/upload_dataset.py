import csv
import os
from pathlib import Path
from typing import Dict, List

from langfuse import Langfuse

# Usage:
# create_langfuse_dataset("s2_gadm_0_1")
# upload_csv("s2_gadm_0_1", "experiments/Zeno test dataset(S2 GADM 0-1).csv")

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


def _parse_and_format_expected_output(
    gadm_ids_str: str, location_names_str: str
) -> List[Dict[str, str]]:
    """
    Parses semicolon-separated GADM ID and location name strings
    and formats them into a list of dictionaries.
    Assumes corresponding IDs and names.
    """
    gadm_ids = [gid.strip() for gid in gadm_ids_str.split(";") if gid.strip()]
    location_names = [
        name.strip() for name in location_names_str.split(";") if name.strip()
    ]

    expected_output = []
    # zip will stop when the shorter of gadm_ids or location_names is exhausted.
    # If lists are not of the same length, some data might be silently ignored.
    for gadm_id, location_name in zip(gadm_ids, location_names):
        expected_output.append({"name": location_name, "gadm_id": gadm_id})
    return expected_output


def upload_csv(dataset_name, csv_filepath):
    """Uploads rows from a CSV file to a Langfuse dataset.

    The CSV file must contain 'text', 'id', and 'name' columns.
    - 'text': Input query for the Langfuse dataset item.
    - 'id': Semicolon-separated GADM ID(s).
    - 'name': Semicolon-separated location name(s), corresponding to the 'id'(s).

    The 'id' and 'name' fields are parsed to create the 'expected_output'
    for each Langfuse item, formatted as a list of dictionaries:
    e.g., [{"name": "LocationName", "gadm_id": "GADM_ID"}].

    Example CSV content:
    text,id,name,type
    Compare logging rates in Peru and Colombia,PER;COL,Peru;Colombia,iso;iso
    Fires in Brazil last month,BRA,Brazil,iso

    The 'type' column, if present, is ignored. Rows with missing 'text',
    'id', or 'name' data are skipped.
    """

    try:
        with open(csv_filepath, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            csv_filename = Path(csv_filepath).name
            for row_number, row in enumerate(reader, 1):
                input_text = row.get("text")
                gadm_ids_str = row.get("id")
                location_names_str = row.get("name")
                # The 'type' column is present in the sample CSV but not used here.

                if (
                    input_text is None
                    or gadm_ids_str is None
                    or location_names_str is None
                ):
                    print(
                        f"Skipping row {row_number} due to missing essential data (text, id, or name): {row}"
                    )
                    continue

                expected_output = _parse_and_format_expected_output(
                    gadm_ids_str, location_names_str
                )

                # If gadm_ids_str or location_names_str were empty or just ";",
                # expected_output will be an empty list [], which is acceptable.
                # If counts of IDs and names differ after splitting, zip will pair them
                # up to the length of the shorter list.
                insert_langfuse_item(
                    dataset_name=dataset_name,
                    input=input_text,
                    expected_output=expected_output,
                    filename=csv_filename,
                )
        print(
            f"Successfully processed data from {csv_filename} for dataset {dataset_name}"
        )
    except FileNotFoundError:
        print(f"Error: The file {csv_filepath} was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")


