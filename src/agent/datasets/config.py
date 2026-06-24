"""
Centralized dataset configuration to avoid circular imports.
"""

from pathlib import Path

import yaml

DATASETS_DIR = Path(__file__).parent / "catalog"
CANDIDATE_DATASET_REQUIRED_COLUMNS = [
    "dataset_id",
    "dataset_name",
    "description",
    "selection_hints",
    "content_date",
    "context_layers",
    "parameters",
]


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
    return datasets


DATASETS = _load_datasets()


def agent_datasets() -> list[dict]:
    """Datasets the agent may select and advertise.

    All datasets stay in ``DATASETS`` (handlers and metadata lookups need
    them), but a dataset can be hidden from the agent — kept loaded yet not
    embedded for retrieval nor listed in capabilities — by setting
    ``agent_enabled: false`` in its YAML.
    """
    return [d for d in DATASETS if d.get("agent_enabled", True)]
