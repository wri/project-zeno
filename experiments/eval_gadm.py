"""
GADM Location Evaluation Script

This script evaluates the GADM location extraction capabilities by running queries from
a Langfuse dataset and comparing actual outputs against expected outputs.

Usage:
    $ LANGFUSE_HOST=http://localhost:3000 \
      LANGFUSE_SECRET_KEY=<SECRET_KEY> \
      LANGFUSE_PUBLIC_KEY=<PUBLIC_KEY> \
      python -i experiments/eval_gadm.py

Required Environment Variables:
    - LANGFUSE_HOST: The Langfuse server URL (e.g., http://localhost:3000)
    - LANGFUSE_SECRET_KEY: Your Langfuse secret key
    - LANGFUSE_PUBLIC_KEY: Your Langfuse public key

Configuration:
    - DATASET_NAME: Set this constant to match the name of your Langfuse dataset
                    (default: "gadm_location"). This must correspond to an existing
                    dataset in your Langfuse instance.

The script will:
    1. Connect to Langfuse and fetch the dataset specified by DATASET_NAME
    2. Process all active items in the dataset
    3. Run each query through the chat system
    4. Extract GADM locations from the responses
    5. Compare actual vs expected GADM locations
    6. Score each result and upload scores to Langfuse

The -i flag keeps the Python interpreter open after execution for debugging.
"""

import os
import subprocess
from collections import Counter
from datetime import datetime
from typing import List, Optional

from langchain_core.load import dumps
from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.callback import CallbackHandler

from experiments.gadm_utils import (
    GadmLocation,
    parse_expected_output,
    parse_gadm_from_json,
)
from src.agents import zeno

# I don't know what this does. So just copied over from test_alerts.sh defaults
USER_PERSONA = "researcher"


def get_git_short_hash() -> str:
    """Get the short git hash of the current commit."""
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
            .decode("ascii")
            .strip()
        )
    except Exception:
        return "nogit"


# Langfuse Configuration
DATASET_NAME = "gadm_location"
# Generate a human-readable run name with timestamp and git short hash
current_date_str = datetime.now().strftime("%Y%m%d")
git_short_hash = get_git_short_hash()
RUN_NAME = f"eval_{current_date_str}_{git_short_hash}"


print(f"Starting evaluation [run name: {RUN_NAME}] ...")


# Copied over from api.app because I don't want to mess with Devseed code. It'd be easier if we just
# refactor the parent method.
# TODO: perhaps add a langfuse_handler argument to api.app.stream_chat so we don't need to dup this
# here
def stream_chat(
    query: str,
    langfuse_handler: CallbackHandler,
    user_persona: Optional[str] = None,
    thread_id: Optional[str] = None,
):
    config = {
        "configurable": {
            "thread_id": thread_id,
        },
        "callbacks": [langfuse_handler],
    }
    messages = [HumanMessage(content=query)]

    return list(
        zeno.stream(
            {
                "messages": messages,
                "user_persona": user_persona,
            },
            config=config,
            stream_mode="updates",
            subgraphs=False,
        )
    )


def langgraph_output_to_json(messages):
    return dumps(messages)


def score_gadm_matches(
    actual: List[GadmLocation], expected: List[GadmLocation]
) -> float:
    """Compare name and gadm_id of each actual and see if they match."""
    # Case 1: Both lists are empty.
    # This is considered a perfect match (or vacuously true).
    if not actual and not expected:
        return 1.0

    # Case 2: One list is empty, but the other is not.
    # This means either:
    #   - Nothing was expected, but something was returned (false positives).
    #   - Something was expected, but nothing was returned (false negatives).
    # In either scenario, the score is 0.0.
    if not actual or not expected:
        return 0.0

    # At this point, both `actual` and `expected` lists are non-empty.

    actual_counts = Counter(actual)
    expected_counts = Counter(expected)

    # Calculate the intersection of the two multisets
    # The '&' operator for Counters results in a new Counter where counts are min(count_in_actual, count_in_expected)
    intersection_counts = actual_counts & expected_counts

    # Sum of counts in the intersection gives the total number of matches
    matches = sum(intersection_counts.values())

    # The denominator is the length of the longer list, to penalize both false positives and false negatives.
    denominator = max(len(actual), len(expected))

    # Denominator will be > 0 here because empty list cases are handled above.
    return float(matches) / denominator


langfuse = Langfuse(
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    host=os.getenv("LANGFUSE_HOST"),
)

dataset = langfuse.get_dataset(DATASET_NAME)
# Filter for active items
active_dataset_items = [
    item for item in dataset.items if item.status == "ACTIVE"
]
print(
    f"Fetched dataset {DATASET_NAME}. Processing {len(active_dataset_items)} active items."
)


actual_outputs = []
for item in active_dataset_items:
    print(f"Evaluating item: input=[{item.input}]")
    handler = item.get_langchain_handler(run_name=RUN_NAME)
    actual_output = stream_chat(
        query=item.input,
        user_persona=USER_PERSONA,
        thread_id=item.id,
        langfuse_handler=handler,
    )
    actual_outputs.append(actual_output)
    actual_gadms = parse_gadm_from_json(
        langgraph_output_to_json(actual_output)
    )
    expected_gadms = parse_expected_output(item.expected_output)

    # Concise debug output
    print(f"  Expected: {[f'{g.name}({g.gadm_id})' for g in expected_gadms]}")
    print(f"  Actual:   {[f'{g.name}({g.gadm_id})' for g in actual_gadms]}")

    score = score_gadm_matches(actual_gadms, expected_gadms)
    langfuse.score(
        trace_id=handler.get_trace_id(), name="gadm_matches_score", value=score
    )
