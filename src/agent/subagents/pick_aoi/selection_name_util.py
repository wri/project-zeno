"""Utilities for building concise display names for area-of-interest selections."""

_IRREGULAR_PLURALS = {
    "country": "Countries",
    "locality": "Localities",
    "municipality": "Municipalities",
}


def build_selection_name(
    match_names: list[str],
    subregion: str | None,
    num_aois: int,
) -> str:
    """Build a concise display name for a (multi-)area selection.

    Examples:
        (["Brazil"], None, 1)                    -> "Brazil"
        (["Brazil"], "state", 26)                -> "26 States in Brazil"
        (["Brazil", "Peru"], "state", 3)         -> "3 States in Brazil & Peru"
        (["Brazil", "Peru"], None, 2)            -> "Brazil & Peru"
        (["Africa"], "country", 54)              -> "54 Countries in Africa"
        (["Brazil"], "municipality", 5570)       -> "5570 Municipalities in Brazil"
    """
    parent_names = " & ".join(match_names)
    if not subregion:
        return parent_names
    label = _IRREGULAR_PLURALS.get(
        subregion.lower(), f"{subregion.capitalize()}s"
    )
    return f"{num_aois} {label} in {parent_names}"
