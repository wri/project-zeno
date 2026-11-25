"""The recipe token is shared with the frontend and persisted in threads and
dashboard widgets: it must stay byte-stable."""

from datetime import date

import pytest

from src.shared.imagery_recipe import (
    InvalidRecipeError,
    MosaicRecipe,
    decode_recipe,
    encode_recipe,
)

# The same tokens the frontend tests pin (project-zeno-next
# src/features/imagery/model/__tests__/request.test.ts).
TWO_AREAS = MosaicRecipe(
    aois=(("gadm", "PER.11.3_1"), ("kba", "Pacaya-Samiria é")),
    target_date=date(2026, 6, 15),
    window_days=30,
    max_cloud_cover=50,
)
TWO_AREAS_TOKEN = (
    "eyJhIjpbWyJnYWRtIiwiUEVSLjExLjNfMSJdLFsia2JhIiwiUGFjYXlhLVNhbWlyaWEg"
    "XHUwMGU5Il1dLCJjIjo1MCwiZCI6IjIwMjYtMDYtMTUiLCJuIjo1MCwidyI6MzB9"
)
CUSTOM = MosaicRecipe(
    aois=(("custom", "abc"),), target_date=date(2026, 6, 15), user_id="u-1"
)
CUSTOM_TOKEN = (
    "eyJhIjpbWyJjdXN0b20iLCJhYmMiXV0sImMiOjIwLCJkIjoiMjAyNi0wNi0xNSIsIm4i"
    "OjUwLCJ1IjoidS0xIiwidyI6N30"
)


def test_token_matches_the_frontend():
    assert encode_recipe(TWO_AREAS) == TWO_AREAS_TOKEN
    assert encode_recipe(CUSTOM) == CUSTOM_TOKEN


def test_token_round_trips():
    assert decode_recipe(TWO_AREAS_TOKEN) == TWO_AREAS
    assert decode_recipe(CUSTOM_TOKEN) == CUSTOM


@pytest.mark.parametrize(
    "token", ["", "not-a-token", "planet_medres_normalized_2026-08"]
)
def test_malformed_tokens_raise(token):
    with pytest.raises(InvalidRecipeError):
        decode_recipe(token)
