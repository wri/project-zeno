"""get_tile_services_for_dataset appends the requested date range to the tile
URL for date-driven alert layers (DIST-ALERT and Integrated alerts), so the map
shows alerts only within the queried window."""

from types import SimpleNamespace

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.subagents.pick_dataset.tool import (
    get_tile_services_for_dataset,
)

IA_TILE = (
    "https://tiles.globalforestwatch.org/gfw_integrated_alerts/latest/"
    "dynamic/{z}/{x}/{y}.png?render_type=true_color"
)


def test_integrated_alerts_tile_url_gets_date_params():
    selection = SimpleNamespace(
        dataset_id=INTEGRATED_ALERTS_ID, context_layer=None, parameters=None
    )
    row = SimpleNamespace(
        dataset_id=INTEGRATED_ALERTS_ID,
        tile_url=IA_TILE,
        context_layers=None,
        parameters=None,
    )

    tile_url, context_layers = get_tile_services_for_dataset(
        selection, row, "2024-03-01", "2024-10-31"
    )

    assert "start_date=2024-03-01" in tile_url
    assert "end_date=2024-10-31" in tile_url
    assert tile_url.startswith(IA_TILE)  # date params appended, base preserved
    assert context_layers == []
