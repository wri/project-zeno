"""The dataset selector sees a multi-layer dataset's layers as a prompt block
(name, title, description) rather than as a raw CSV cell, and never sees the
layers' tile URLs."""

import pandas as pd

from src.agent.datasets.config import (
    CANDIDATE_DATASET_REQUIRED_COLUMNS,
    DATASETS,
)
from src.agent.subagents.pick_dataset.tool import _format_layer_options

LGMS = next(d for d in DATASETS if d.get("layers"))


def test_layer_options_render_name_title_and_description():
    block = _format_layer_options(pd.DataFrame([LGMS]))

    assert block.startswith(f"{LGMS['dataset_name']}:\n")
    for layer in LGMS["layers"]:
        assert (
            f"- {layer['name']} ({layer['title']}): {layer['description']}"
            in block
        )
    assert "tile_url" not in block
    assert "http" not in block


def test_layer_options_skip_single_layer_and_layerless_datasets():
    rows = pd.DataFrame(
        [
            {"dataset_name": "One layer", "layers": [{"name": "only"}]},
            {"dataset_name": "No layers", "layers": None},
        ]
    )
    assert _format_layer_options(rows) == "None"


def test_candidate_csv_has_no_layer_tile_urls():
    csv = pd.DataFrame([LGMS])[CANDIDATE_DATASET_REQUIRED_COLUMNS].to_csv(
        index=False
    )
    for layer in LGMS["layers"]:
        assert layer["tile_url"] not in csv
