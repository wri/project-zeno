"""Unit tests for build_selection_name — pure label generation, no DB needed."""

import pytest

from src.agent.tools.pick_aoi.selection_name_util import build_selection_name

# ---------------------------------------------------------------------------
# No subregion — direct area selections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "match_names, num_aois, expected",
    [
        # Single country / state / protected area
        (["Brazil"], 1, "Brazil"),
        (["Indonesia"], 1, "Indonesia"),
        # Two countries — joined with &, not comma
        (["Brazil", "Peru"], 2, "Brazil & Peru"),
        # Three or more (e.g. user: "compare Congo, Brazil and Indonesia")
        (["Congo", "Brazil", "Indonesia"], 3, "Congo & Brazil & Indonesia"),
        # Areas whose names already contain commas — no extra commas added
        (["Para, Brazil"], 1, "Para, Brazil"),
        (
            ["Para, Brazil", "Amazonas, Brazil"],
            2,
            "Para, Brazil & Amazonas, Brazil",
        ),
    ],
)
def test_no_subregion(match_names, num_aois, expected):
    assert build_selection_name(match_names, None, num_aois) == expected


# ---------------------------------------------------------------------------
# With subregion — count-forward format
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "match_names, subregion, num_aois, expected",
    [
        # Single parent, various subregion types
        (["Brazil"], "state", 26, "26 States in Brazil"),
        (["Bolivia"], "state", 9, "9 States in Bolivia"),
        (["Brazil"], "district", 5570, "5570 Districts in Brazil"),
        # Two parents (cross-country comparison)
        (
            ["Ecuador", "Bolivia"],
            "state",
            33,
            "33 States in Ecuador & Bolivia",
        ),
        (["Brazil", "Peru"], "state", 3, "3 States in Brazil & Peru"),
        # Irregular plurals
        (["Africa"], "country", 54, "54 Countries in Africa"),
        (["Brazil"], "municipality", 5570, "5570 Municipalities in Brazil"),
        (["Brazil"], "locality", 12, "12 Localities in Brazil"),
        # Regular plurals that just get +s
        (["Brazil"], "district", 1, "1 Districts in Brazil"),
        (["Brazil"], "neighbourhood", 8, "8 Neighbourhoods in Brazil"),
        (["Brazil"], "kba", 14, "14 Kbas in Brazil"),
        (["Brazil"], "wdpa", 3, "3 Wdpas in Brazil"),
        (["Brazil"], "landmark", 7, "7 Landmarks in Brazil"),
        # Case insensitivity of subregion arg
        (["Brazil"], "State", 26, "26 States in Brazil"),
        (["Brazil"], "MUNICIPALITY", 100, "100 Municipalities in Brazil"),
        (["Brazil"], "COUNTRY", 1, "1 Countries in Brazil"),
        # Three parents
        (
            ["Brazil", "Peru", "Colombia"],
            "state",
            60,
            "60 States in Brazil & Peru & Colombia",
        ),
    ],
)
def test_with_subregion(match_names, subregion, num_aois, expected):
    assert build_selection_name(match_names, subregion, num_aois) == expected


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_single_result_subregion():
    """Subregion queries always return all children, so num_aois=1 only occurs
    for genuine single-subdivision countries (e.g. city-states). Accepted as-is."""
    result = build_selection_name(["Belize"], "state", 1)
    assert result == "1 States in Belize"


def test_empty_subregion_string_treated_as_no_subregion():
    """Empty string is falsy — should fall through to plain join."""
    result = build_selection_name(["Brazil"], "", 1)
    assert result == "Brazil"


def test_area_with_ampersand_in_name():
    """If a place name itself contains & it should survive unmodified."""
    result = build_selection_name(["Trinidad & Tobago"], "state", 9)
    assert result == "9 States in Trinidad & Tobago"


def test_many_parents_no_subregion():
    """Five parents — still no count prefix, just joined."""
    names = ["Brazil", "Peru", "Colombia", "Ecuador", "Bolivia"]
    result = build_selection_name(names, None, 5)
    assert result == "Brazil & Peru & Colombia & Ecuador & Bolivia"
