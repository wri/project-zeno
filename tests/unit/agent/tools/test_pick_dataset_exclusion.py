"""pick_dataset drops datasets the current agent profile excludes, so an
excluded dataset can never be selected under a flag that hides it."""

import pandas as pd

from src.agent.subagents.pick_dataset.tool import _drop_excluded_datasets


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "dataset_id": [12, 6, 4],
            "dataset_name": [
                "Land GHG Inventory",
                "Forest greenhouse gas net flux",
                "Tree cover loss",
            ],
        }
    )


def test_drops_excluded_datasets():
    df = _drop_excluded_datasets(
        _candidates(), frozenset({"Land GHG Inventory"})
    )
    names = set(df["dataset_name"])
    assert "Land GHG Inventory" not in names
    assert {"Forest greenhouse gas net flux", "Tree cover loss"} <= names


def test_no_excludes_keeps_all_candidates():
    df = _drop_excluded_datasets(_candidates(), frozenset())
    assert len(df) == 3
