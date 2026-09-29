from datetime import date

import pytest

from src.shared.imagery.contract import LayerPeriod
from src.shared.imagery.planet import MonthlyPeriod


def test_a_bare_layer_period_cannot_be_built():
    with pytest.raises(TypeError, match="LayerPeriod"):
        LayerPeriod(start=date(2026, 8, 1), end=date(2026, 8, 31))


def test_a_layer_period_labels_itself_from_start_to_end():
    assert (
        MonthlyPeriod.from_month("2026-08").label()
        == "2026-08-01 → 2026-08-31"
    )
