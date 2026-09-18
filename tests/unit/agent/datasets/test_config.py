"""_load_datasets loads each yml record as-is — it does not resolve tile_url
from `layers`. A dataset's tile_url is only ever meaningfully resolved
downstream, at persistence time, by add_map_widget.py's _default_layer (the
only place a single tile_url is actually required)."""

import yaml

from src.agent.datasets import config as datasets_config

REQUIRED_FIELDS = {
    "dataset_name": "Test dataset",
    "description": "A test dataset.",
    "selection_hints": "Use for testing.",
    "content_date": "2024",
    "context_layers": None,
    "parameters": None,
}


def _write_yml(tmp_path, dataset_id, **overrides):
    record = {"dataset_id": dataset_id, **REQUIRED_FIELDS, **overrides}
    path = tmp_path / f"{dataset_id}.yml"
    path.write_text(yaml.safe_dump(record))
    return path


def _load(tmp_path, monkeypatch):
    monkeypatch.setattr(datasets_config, "DATASETS_DIR", tmp_path)
    return datasets_config._load_datasets()


def test_layers_only_dataset_keeps_empty_tile_url(tmp_path, monkeypatch):
    """A dataset that only declares `layers` (e.g. LGMS) is loaded with its
    tile_url exactly as written — no resolution from `layers` at load time."""
    _write_yml(
        tmp_path,
        12,
        tile_url="",
        layers=[
            {"name": "lulucf", "tile_url": "https://tiles.example.com/a.png"},
            {
                "name": "agriculture",
                "tile_url": "https://tiles.example.com/b.png",
            },
        ],
    )

    [dataset] = _load(tmp_path, monkeypatch)

    assert dataset["tile_url"] == ""
    assert dataset["layers"][0]["name"] == "lulucf"


def test_leaves_explicit_tile_url_untouched(tmp_path, monkeypatch):
    _write_yml(
        tmp_path,
        4,
        tile_url="https://tiles.example.com/tcl.png",
    )

    [dataset] = _load(tmp_path, monkeypatch)

    assert dataset["tile_url"] == "https://tiles.example.com/tcl.png"


def test_analytics_only_dataset_keeps_empty_tile_url(tmp_path, monkeypatch):
    """A dataset with no renderable layer at all (no tile_url, no layers) is
    a valid, pre-existing shape."""
    _write_yml(tmp_path, 9, tile_url="")

    [dataset] = _load(tmp_path, monkeypatch)

    assert dataset["tile_url"] == ""
