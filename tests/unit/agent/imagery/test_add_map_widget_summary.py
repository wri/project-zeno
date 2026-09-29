from src.agent.tools.add_map_widget import _imagery_summary
from src.api.services.widget_configs import imagery_config
from tests.unit.agent.imagery.factories import (
    planet_imagery,
    sentinel2_imagery,
)


def test_map_widget_reply_describes_planet_imagery_by_its_period():
    snapshot = imagery_config(
        {"imagery": planet_imagery().model_dump(mode="json")}
    )

    assert _imagery_summary(snapshot) == (
        "planet 2026-08-01 → 2026-08-31 imagery map widget "
        "(areas: Novo Progresso)"
    )


def test_map_widget_reply_describes_sentinel2_imagery_by_its_period():
    snapshot = imagery_config(
        {"imagery": sentinel2_imagery().model_dump(mode="json")}
    )

    assert _imagery_summary(snapshot) == (
        "sentinel-2 2026-08-08 → 2026-08-22 imagery map widget "
        "(areas: Odzala-Kokoua)"
    )
