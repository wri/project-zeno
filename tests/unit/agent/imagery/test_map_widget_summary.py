from src.agent.tools.inspect_view_context import _format_map_widget
from tests.unit.agent.imagery.factories import planet_imagery


def test_map_widget_summary_describes_planet_imagery_by_its_period():
    config = {"imagery": planet_imagery().model_dump(mode="json")}

    assert (
        _format_map_widget(config)
        == "map: planet imagery 2026-08-01 → 2026-08-31 (Novo Progresso)"
    )
