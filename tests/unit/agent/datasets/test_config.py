"""_load_datasets loads each yml record as-is — it does not resolve tile_url
from `layers`. A dataset's tile_url is only ever meaningfully resolved
downstream, at persistence time, by add_map_widget.py's _default_layer (the
only place a single tile_url is actually required)."""

import re

import pytest
import yaml

from src.agent.datasets import config as datasets_config

REQUIRED_FIELDS = {
    "dataset_name": "Test dataset",
    "description": "A test dataset.",
    "selection_hints": "Use for testing.",
    "content_date": "2024",
    "context_layers": None,
    "parameters": None,
    "coverage": {
        "period": "2024",
        "time_step": "One year",
        "limits": "None.",
    },
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


def test_lgms_layers_carry_title_and_description():
    """Every LGMS layer names its measure (net flux vs gross emissions) in
    its description — the only place the selector and agent can read it."""
    [lgms] = [d for d in datasets_config.DATASETS if d.get("layers")]
    for layer in lgms["layers"]:
        assert layer.get("title"), layer["name"]
        description = layer.get("description") or ""
        flux_type = layer["tile_url"].split("flux_type=")[1]
        expected = "Net flux" if flux_type == "net" else "Gross emissions"
        assert expected in description, layer["name"]


@pytest.mark.parametrize(
    "coverage",
    [
        {"period": "2024", "time_step": "One year"},
        {"period": "2024", "time_step": "One year", "limits": " "},
        {"period": 2024, "time_step": "One year", "limits": "None."},
        "2024",
    ],
    ids=["missing field", "empty field", "not text", "not a mapping"],
)
def test_rejects_an_incomplete_coverage_block(tmp_path, monkeypatch, coverage):
    """The capabilities skill renders each dataset's coverage block as a
    table row, so a block with a missing or empty field must not load."""
    _write_yml(tmp_path, 4, coverage=coverage)

    with pytest.raises(ValueError, match="coverage"):
        _load(tmp_path, monkeypatch)


def test_rejects_a_dataset_without_coverage(tmp_path, monkeypatch):
    record = {"dataset_id": 4, **REQUIRED_FIELDS}
    del record["coverage"]
    (tmp_path / "4.yml").write_text(yaml.safe_dump(record))

    with pytest.raises(ValueError, match="coverage"):
        _load(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "dataset",
    datasets_config.DATASETS,
    ids=[d["dataset_name"] for d in datasets_config.DATASETS],
)
def test_coverage_period_matches_the_catalog_dates(dataset):
    """The skill's Coverage table shows `coverage.period` as text. Its first
    year must be the start_date year, and its last year the end_date year
    (or "today" for a dataset without an end_date), so a new year of data
    cannot leave the table stale."""
    period = dataset["coverage"]["period"]
    years = re.findall(r"\b\d{4}\b", period)

    assert years, period
    assert years[0] == dataset["start_date"][:4], period
    if dataset.get("end_date"):
        assert years[-1] == dataset["end_date"][:4], period
    else:
        assert period.endswith("to today"), period
