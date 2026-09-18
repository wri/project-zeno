"""
Centralized dataset configuration to avoid circular imports.
"""

from pathlib import Path

import yaml

DATASETS_DIR = Path(__file__).parent / "catalog"

# Dataset ids that a removed dataset used. A dataset id is permanently
# reserved once it is assigned: it is persisted in `statistics.dataset_id`
# and it is a public filter on `GET /api/insights?dataset_id=`, so the same
# id on a new dataset re-attributes historical insights to it. A stale
# embeddings index makes the same reuse wrong in a second way — the index
# keeps the removed dataset's vector under that id, so retrieval answers
# under the new dataset's identity and returns the wrong data instead of
# raising. `_load_datasets` refuses to load a catalog that reuses one.
#
#   0 -- Global all ecosystem disturbance alerts (DIST-ALERT), removed in #802
RETIRED_DATASET_IDS = frozenset({0})

CANDIDATE_DATASET_REQUIRED_COLUMNS = [
    "dataset_id",
    "dataset_name",
    "description",
    "selection_hints",
    "content_date",
    "context_layers",
    "parameters",
]
# Columns shown to the dataset-selector LLM as CSV (tool.py's
# select_best_dataset). A superset of the required columns above: `layers`
# is genuinely optional (most datasets don't have it) so it can't be in the
# required list, but the LLM still needs to see it to populate
# `DatasetOption.selected_layer` for a multi-layer dataset like LGMS.
CANDIDATE_DATASET_LLM_COLUMNS = CANDIDATE_DATASET_REQUIRED_COLUMNS + ["layers"]


def _load_datasets() -> list[dict]:
    paths = sorted(DATASETS_DIR.glob("*.yml"))
    datasets: list[dict] = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            record = yaml.safe_load(f)
        if not isinstance(record, dict):
            raise ValueError(
                f"expected mapping in {path}, got {type(record).__name__}"
            )
        missing_columns = [
            col
            for col in CANDIDATE_DATASET_REQUIRED_COLUMNS
            if col not in record
        ]
        if missing_columns:
            raise ValueError(
                f"dataset {record.get('dataset_id', path.stem)} is missing required columns: {missing_columns}"
            )
        datasets.append(record)
    datasets.sort(key=lambda d: d["dataset_id"])
    if not len(datasets) == len(set(d["dataset_id"] for d in datasets)):
        raise ValueError(
            f"duplicate dataset_id in {DATASETS_DIR}. Each dataset must have a unique dataset_id."
        )
    reused = sorted(
        d["dataset_id"]
        for d in datasets
        if d["dataset_id"] in RETIRED_DATASET_IDS
    )
    if reused:
        raise ValueError(
            f"dataset_id {reused} in {DATASETS_DIR} is retired and must not be "
            "reused (see RETIRED_DATASET_IDS). Give the dataset a new id."
        )
    return datasets


DATASETS = _load_datasets()
