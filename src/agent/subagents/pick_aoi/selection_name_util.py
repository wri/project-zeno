"""Utilities for building concise display names for area-of-interest selections."""


def _pluralize(word: str) -> str:
    """Pluralize *word*, handling the consonant+"y" -> "ies" case (country ->
    countries, municipality -> municipalities). Everything else gets a plain
    "s", which is correct for every subregion/admin term this module sees."""
    if (
        len(word) > 1
        and word[-1].lower() == "y"
        and word[-2].lower() not in "aeiou"
    ):
        return word[:-1] + "ies"
    return word + "s"


def build_selection_name(
    match_names: list[str],
    subregion: str | None,
    num_aois: int,
    display_term: str | None = None,
) -> str:
    """Build a concise display name for a (multi-)area selection.

    *display_term* overrides the label with the country-specific admin term
    the user actually asked for (e.g. "Province" for Spain instead of the
    generic "district" depth it resolved to), when the geocoder resolved one.

    Examples:
        (["Brazil"], None, 1)                    -> "Brazil"
        (["Brazil"], "state", 26)                -> "26 States in Brazil"
        (["Brazil", "Peru"], "state", 3)         -> "3 States in Brazil & Peru"
        (["Brazil", "Peru"], None, 2)            -> "Brazil & Peru"
        (["Africa"], "country", 54)              -> "54 Countries in Africa"
        (["Brazil"], "municipality", 5570)       -> "5570 Municipalities in Brazil"
        (["Spain"], "district", 52, "Province")  -> "52 Provinces in Spain"
    """
    parent_names = " & ".join(match_names)
    if not subregion:
        return parent_names
    # display_term (from the GADM admin-type enum) is already properly cased
    # and may be multiple words ("Constituent Country"); subregion is a
    # lowercase single-word literal and needs title-casing.
    term = display_term if display_term else subregion.capitalize()
    return f"{num_aois} {_pluralize(term)} in {parent_names}"
