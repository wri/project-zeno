"""UI-selected datasets get their layers from the backend catalog."""

from src.api.services.chat import _with_catalog_layers

LGMS_ID = 12


def _ui_lgms(selected_layer=None):
    return {
        "dataset_id": LGMS_ID,
        "dataset_name": "Land GHG Monitoring System (LGMS)",
        "layers": [{"name": "lgms", "tile_url": "https://tiles/lgms"}],
        "selected_layer": selected_layer,
    }


def test_layers_come_from_catalog_with_title_and_description():
    dataset = _with_catalog_layers(_ui_lgms("agriculture"))
    by_name = {layer["name"]: layer for layer in dataset["layers"]}
    assert set(by_name) == {
        "lgms",
        "lulucf",
        "agriculture",
        "cropland",
        "livestock",
    }
    assert by_name["agriculture"]["title"] == "Agriculture"
    assert by_name["agriculture"]["description"].startswith("Gross emissions")
    assert dataset["selected_layer"] == "agriculture"


def test_unknown_selected_layer_is_dropped():
    dataset = _with_catalog_layers(_ui_lgms("not-a-layer"))
    assert dataset["selected_layer"] is None


def test_dataset_without_catalog_layers_is_unchanged():
    dataset = {"dataset_id": 4, "dataset_name": "Tree cover loss"}
    assert _with_catalog_layers(dataset) == dataset
