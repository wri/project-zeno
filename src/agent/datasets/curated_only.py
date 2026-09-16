"""Datasets the agent may only show as curated charts.

A catalog entry with `curated_only: true` gets the dataset's deterministic
chart generator and nothing else: no code-executor charts, no restyle, one
area per pull, and no interpretation of its values by any model. Every guard
reads this module rather than checking a dataset id, so the rule follows the
catalog flag.

The guards, from strongest to weakest:

- `generate_insights` writes a fixed narrative (no LLM text stage) and
  sends no chart rows to the orchestrator.
- `format_chart_data` withholds the rows of these charts wherever insights
  reach the agent (insights on screen, dashboards).
- `pull_data` refuses more than one area, and `update_insight_display`
  refuses these insights.
- The instructions below, in the tool result and in the session block of
  every turn.
"""

from typing import Optional

from src.agent.datasets.config import DATASETS

CURATED_ONLY_DATASET_IDS = frozenset(
    ds["dataset_id"] for ds in DATASETS if ds.get("curated_only")
)

# Model-facing, so English like the rest of the tool instructions.
CURATED_ONLY_TOOL_INSTRUCTION = (
    "The standard charts for this dataset are now shown to the user. They "
    "are the only output available for this dataset. Do not describe, "
    "summarise, compare, rank, or interpret any values or trends in them, "
    "and do not state any numbers from them. Only tell the user that the "
    "charts are shown. If the user asks for a figure, a trend, a "
    "comparison, a different chart, a change to these charts, or an "
    "explanation of the data, decline politely and say that only the "
    "standard charts are available for this dataset. You may still repeat "
    "the dataset's description, methodology, cautions, and citation."
)

CURATED_ONLY_DATA_WITHHELD = (
    "Data withheld: this chart belongs to a dataset shown as standard "
    "charts only. Do not interpret, summarise, or quote values from it, "
    "and do not guide the user to read values or trends off it. If the "
    "user asks for figures, rankings, trends, comparisons, or a breakdown, "
    "decline politely: only the standard charts are available for this "
    "dataset. Do not offer to pull, analyse, or break down its data in "
    "another way, and do not give reasons for this beyond that sentence."
)

CURATED_ONLY_SESSION_NOTE = (
    "standard charts only — do not interpret its data or state its values; "
    "politely decline figures, trends, comparisons, custom charts, and "
    "restyles"
)

CURATED_ONLY_RESTYLE_REFUSED = (
    "This insight shows the standard charts of a dataset that cannot be "
    "changed. Nothing was updated. Tell the user politely that only the "
    "standard charts are available for this dataset."
)


def is_curated_only(dataset_id: Optional[int]) -> bool:
    """Whether the agent may only show `dataset_id` as curated charts."""
    return dataset_id in CURATED_ONLY_DATASET_IDS
