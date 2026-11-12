from typing import Any, Optional

# Zeno's context layer for each filter an analytics API payload can apply.
FOREST_FILTER_LAYERS = {
    "primary_forest": "primary_forest",
    "intact_forest": "intact_forest",
    "natural_forest_only": "natural_forest",
}
LAND_FILTER_LAYERS = {
    "natural_lands": "natural_lands",
    "natural_forests": "natural_forests",
}
NATURAL_FOREST_LAYER = "natural_forest"


class PayloadChoices:
    """The context layer and parameters an analytics API payload chose, as
    Zeno records them on a dataset selection. A canopy cover is only a choice
    when it differs from the default for its context layer."""

    def __init__(
        self, default_canopy_cover: int, natural_forest_canopy_cover: int
    ):
        self.default_canopy_cover = default_canopy_cover
        self.natural_forest_canopy_cover = natural_forest_canopy_cover

    def context_layer(self, payload: dict[str, Any]) -> Optional[str]:
        forest_filter = payload.get("forest_filter")
        if forest_filter in FOREST_FILTER_LAYERS:
            return FOREST_FILTER_LAYERS[forest_filter]
        return LAND_FILTER_LAYERS.get(payload.get("land_filter") or "")

    def canopy_cover(
        self, payload: dict[str, Any], context_layer: Optional[str]
    ) -> Optional[int]:
        canopy_cover = payload.get("canopy_cover")
        if canopy_cover is None:
            return None
        default = (
            self.natural_forest_canopy_cover
            if context_layer == NATURAL_FOREST_LAYER
            else self.default_canopy_cover
        )
        return None if int(canopy_cover) == default else int(canopy_cover)
