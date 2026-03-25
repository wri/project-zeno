"""
Centralized dataset configuration to avoid circular imports.
"""

from pathlib import Path

import yaml

DATASETS_DIR = Path(__file__).parent / "datasets"


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
        datasets.append(record)
    datasets.sort(key=lambda d: d["dataset_id"])
    if len(datasets) != len(set(d["dataset_id"] for d in datasets)):
        raise ValueError(
            f"duplicate dataset_id in {DATASETS_DIR}. Each dataset must have a unique dataset_id."
        )
    return datasets


DATASETS = _load_datasets()
