"""Utility functions for evaluators."""


def normalize_gadm_id(gadm_id: str) -> str:
    """Normalize GADM ID for comparison."""
    if not gadm_id:
        return ""
    return gadm_id.split("_")[0].replace("-", ".").lower()


def normalize_value(value) -> str:
    """Normalize values for comparison, handling None, empty strings, and 'None' strings."""
    if value is None or value == "None" or str(value).strip() == "":
        return ""
    return str(value).strip()
