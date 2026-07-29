"""
Canonical color registry for dataset categories, series colors, and divergent
colors, derived from the `categories` / `series_color` / `divergent_colors`
keys in the catalog YAMLs (`src/agent/datasets/catalog/*.yml`).

This is the single source of truth chart and map-legend colors are resolved
from — see docs/insight-chart-colors-plan.md. Colors are keyed by a stable
English slug (defined here, in the catalog), never by a translated display
label, so the same category gets the same color regardless of the user's
language.
"""

import re
from typing import Optional, TypedDict

from src.agent.datasets.config import DATASETS

_HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class PaletteCategory(TypedDict):
    slug: str
    label_en: str
    color: str


class DivergentColors(TypedDict):
    positive: str
    negative: str


class DatasetPalette(TypedDict):
    dataset_id: int
    dataset_name: str
    categories: list[PaletteCategory]
    series_color: Optional[str]
    divergent_colors: Optional[DivergentColors]
    # Whether a map legend should render `categories` verbatim. False for
    # datasets whose legend intentionally curates/collapses categories that
    # are less relevant at a glance (e.g. SBTN Natural Lands groups all
    # non-natural classes into one legend row) — chart colors are unaffected
    # either way, this only controls map legend display grouping.
    legend_categories: bool


def _validate_hex(color: str, context: str) -> str:
    if not _HEX_COLOR_RE.match(color):
        raise ValueError(f"invalid hex color {color!r} in {context}")
    return color


def _build_palettes() -> dict[int, DatasetPalette]:
    palettes: dict[int, DatasetPalette] = {}
    for dataset in DATASETS:
        raw_categories = dataset.get("categories") or []
        series_color = dataset.get("series_color")
        raw_divergent = dataset.get("divergent_colors")
        if not raw_categories and not series_color and not raw_divergent:
            continue

        dataset_id = dataset["dataset_id"]
        context = f"dataset_id={dataset_id} ({dataset['dataset_name']})"

        categories: list[PaletteCategory] = []
        seen_slugs: set[str] = set()
        for category in raw_categories:
            slug = category["slug"]
            if slug in seen_slugs:
                raise ValueError(
                    f"duplicate category slug {slug!r} in {context}"
                )
            seen_slugs.add(slug)
            categories.append(
                PaletteCategory(
                    slug=slug,
                    label_en=category["label_en"],
                    color=_validate_hex(category["color"], context),
                )
            )

        if series_color is not None:
            series_color = _validate_hex(series_color, context)

        divergent_colors: Optional[DivergentColors] = None
        if raw_divergent is not None:
            divergent_colors = DivergentColors(
                positive=_validate_hex(raw_divergent["positive"], context),
                negative=_validate_hex(raw_divergent["negative"], context),
            )

        palettes[dataset_id] = DatasetPalette(
            dataset_id=dataset_id,
            dataset_name=dataset["dataset_name"],
            categories=categories,
            series_color=series_color,
            divergent_colors=divergent_colors,
            legend_categories=dataset.get("legend_categories", True),
        )
    return palettes


PALETTES: dict[int, DatasetPalette] = _build_palettes()


def get_dataset_palette(dataset_id: int) -> Optional[DatasetPalette]:
    """Return the color registry entry for a dataset, or None if it has no colors defined."""
    return PALETTES.get(dataset_id)
