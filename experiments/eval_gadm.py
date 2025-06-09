"""GADM Location Evaluation Script"""

import json
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional

from experiments.eval_utils import get_langfuse, get_run_name, run_query


# Data structures
@dataclass
class GadmLocation:
    name: str
    gadm_id: str
    gadm_level: Optional[int] = None
    admin_level: Optional[int] = None

    def __eq__(self, other):
        if not isinstance(other, GadmLocation):
            return NotImplemented
        return normalize_gadm_id(self.gadm_id) == normalize_gadm_id(
            other.gadm_id
        )

    def __hash__(self):
        return hash(normalize_gadm_id(self.gadm_id))


# Parsing utilities
def normalize_gadm_id(gadm_id: str) -> str:
    gadm_id = gadm_id.replace("-", ".").lower()
    return gadm_id


def parse_expected_output(data: List[dict]) -> List[GadmLocation]:
    """Convert list of dicts to list of GadmLocation objects."""
    return [
        GadmLocation(
            name=item.get("name"),
            gadm_id=item.get("gadm_id"),
            gadm_level=item.get("gadm_level"),
            admin_level=item.get("admin_level"),
        )
        for item in data
    ]


def parse_gadm_from_json(json_str: str) -> List[GadmLocation]:
    """Extracts GADM location data from Langgraph json output.

    Filters for "location-tool" messages and extracts GADM details
    (name, ID, level, admin_level) from their artifact properties.

    Args:
        json_str: The JSON serialized output from Langgraph.

    Returns:
        A list of GadmLocation objects.
    """

    data = json.loads(json_str)
    results: List[GadmLocation] = []

    for item in data:
        if "tools" in item and "messages" in item["tools"]:
            for message in item["tools"]["messages"]:
                # Extract the actual message data from kwargs
                msg_data = message.get("kwargs", message)
                if (
                    msg_data.get("type") == "tool"
                    and msg_data.get("name") == "location-tool"
                ):
                    for artifact_item in msg_data.get("artifact", []):
                        properties = artifact_item.get("properties", {})
                        location_info = GadmLocation(
                            name=properties.get("name"),
                            gadm_id=properties.get("gadm_id"),
                            gadm_level=properties.get("gadm_level"),
                            admin_level=properties.get("admin_level"),
                        )
                        results.append(location_info)

    return results


# Scoring
def score_gadm(actual, expected):
    """Score GADM matches."""
    expected = parse_expected_output(expected)

    if not actual and not expected:
        return 1.0
    if not actual or not expected:
        return 0.0

    matches = sum((Counter(actual) & Counter(expected)).values())
    return matches / max(len(actual), len(expected))


# Main execution
langfuse = get_langfuse()
run_name = get_run_name()
dataset = langfuse.get_dataset("gadm_location")

print(f"Evaluating {len(dataset.items)} items...")

for item in dataset.items:
    if item.status != "ACTIVE":
        continue

    # Execute
    handler = item.get_langchain_handler(run_name=run_name)
    response = run_query(item.input, handler, "researcher", item.id)

    # Score
    actual = parse_gadm_from_json(response)
    score = score_gadm(actual, item.expected_output)

    # Upload
    langfuse.score(
        trace_id=handler.get_trace_id(),
        name="gadm_matches_score",
        value=score,
        comment=f"Expected: {item.expected_output}\nActual: {actual}",
    )
    langfuse.flush()

    print(f"✓ {item.input} -> {score}")
