"""A dataset id is permanently reserved once it is assigned. It is persisted
in `statistics.dataset_id` and it is a public filter on
`GET /api/insights?dataset_id=`, so reusing the id of a removed dataset
re-attributes that dataset's historical insights to the new one. An index
published before the removal makes the reuse wrong a second way: it still
holds the removed dataset's vector under that id, so retrieval answers under
the new dataset's identity and returns the wrong data rather than raising.
The catalog loader refuses such a catalog outright.
"""

from pathlib import Path

import pytest
import yaml

from src.agent.datasets.config import (
    DATASETS,
    DATASETS_DIR,
    RETIRED_DATASET_IDS,
    _load_datasets,
)


def test_catalog_uses_no_retired_id():
    assert RETIRED_DATASET_IDS
    assert not RETIRED_DATASET_IDS & {ds["dataset_id"] for ds in DATASETS}


def test_dist_alert_id_stays_reserved():
    """0 was DIST-ALERT, removed in #802, and every index published up to v9
    still holds its document under that id."""
    assert 0 in RETIRED_DATASET_IDS


def test_loader_refuses_a_reused_retired_id(tmp_path, monkeypatch):
    template = yaml.safe_load(
        (DATASETS_DIR / "tree_cover_loss.yml").read_text(encoding="utf-8")
    )
    template["dataset_id"] = sorted(RETIRED_DATASET_IDS)[0]
    template["dataset_name"] = "A new dataset on a retired id"
    (tmp_path / "reused.yml").write_text(
        yaml.safe_dump(template), encoding="utf-8"
    )
    monkeypatch.setattr(
        "src.agent.datasets.config.DATASETS_DIR", Path(tmp_path)
    )

    with pytest.raises(ValueError, match="is retired and must not be reused"):
        _load_datasets()


def test_loader_accepts_the_real_catalog():
    assert len(_load_datasets()) == len(DATASETS)
