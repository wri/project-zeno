from datetime import date

import pytest

from src.shared.imagery.contract import LayerPeriod


def test_a_bare_layer_period_cannot_be_built():
    with pytest.raises(TypeError, match="LayerPeriod"):
        LayerPeriod(start=date(2026, 8, 1), end=date(2026, 8, 31))
