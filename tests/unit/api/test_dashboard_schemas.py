"""Unit tests for the dashboard request schemas.

The widget-config rules these check are the API's contract with the frontend:
map widgets must carry a renderable layer snapshot, text widgets a markdown
body, and the MVP allows exactly one AOI per dashboard.
"""

import pytest
from pydantic import ValidationError

from src.api.schemas import (
    DashboardCreateRequest,
    DashboardUpdateRequest,
    DashboardWidgetCreateRequest,
    DashboardWidgetUpdateRequest,
)

AOI = {
    "source": "gadm",
    "src_id": "BRA.16_1",
    "subtype": "state-province",
    "name": "Paraná",
}

DATASET_SNAPSHOT = {
    "dataset_id": 4,
    "dataset_name": "Tree cover loss",
    "tile_url": "https://tiles.example.com/tcl/{z}/{x}/{y}.png",
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
}

IMAGERY_SNAPSHOT = {
    "tile_url": "https://tiles.example.com/mosaic/{z}/{x}/{y}.png",
    "mosaic_id": "abc123",
    "target_date": "2024-06-01",
}


class TestDashboardCreateRequest:
    def test_single_aoi_accepted(self):
        body = DashboardCreateRequest(aois=[AOI])
        assert body.aois[0].name == "Paraná"
        assert body.name is None
        assert body.description is None

    def test_zero_aois_rejected(self):
        with pytest.raises(ValidationError):
            DashboardCreateRequest(aois=[])

    def test_two_aois_rejected_mvp_single_area(self):
        with pytest.raises(ValidationError):
            DashboardCreateRequest(aois=[AOI, AOI])

    @pytest.mark.parametrize(
        "missing", ["source", "src_id", "subtype", "name"]
    )
    def test_aoi_reference_fields_required(self, missing):
        aoi = {k: v for k, v in AOI.items() if k != missing}
        with pytest.raises(ValidationError):
            DashboardCreateRequest(aois=[aoi])

    def test_name_and_description_carried(self):
        body = DashboardCreateRequest(
            name="My dashboard", description="Notes", aois=[AOI]
        )
        assert body.name == "My dashboard"
        assert body.description == "Notes"


class TestWidgetType:
    @pytest.mark.parametrize("widget_type", ["insight", "map", "text"])
    def test_known_types_accepted(self, widget_type):
        config = {
            "insight": None,
            "map": {"dataset": DATASET_SNAPSHOT},
            "text": {"text": "# Hello"},
        }[widget_type]
        body = DashboardWidgetCreateRequest(
            widget_type=widget_type, config=config
        )
        assert body.widget_type == widget_type

    @pytest.mark.parametrize("widget_type", ["chart", "", "Map", "iframe"])
    def test_unknown_types_rejected(self, widget_type):
        with pytest.raises(ValidationError, match="widget_type"):
            DashboardWidgetCreateRequest(widget_type=widget_type)


class TestInsightWidget:
    def test_config_optional(self):
        body = DashboardWidgetCreateRequest(widget_type="insight")
        assert body.config is None
        assert body.insight_id is None
        assert body.position is None

    def test_insight_id_parsed_as_uuid(self):
        body = DashboardWidgetCreateRequest(
            widget_type="insight",
            insight_id="7c9e6679-7425-40de-944b-e07fc1f90ae7",
        )
        assert str(body.insight_id) == "7c9e6679-7425-40de-944b-e07fc1f90ae7"

    def test_malformed_insight_id_rejected(self):
        with pytest.raises(ValidationError):
            DashboardWidgetCreateRequest(
                widget_type="insight", insight_id="not-a-uuid"
            )

    def test_presentation_config_passes_through(self):
        body = DashboardWidgetCreateRequest(
            widget_type="insight",
            config={"default_view": "chart", "title": "Custom"},
        )
        assert body.config == {"default_view": "chart", "title": "Custom"}


class TestMapWidgetConfig:
    def test_requires_config(self):
        with pytest.raises(ValidationError, match="dataset.*imagery"):
            DashboardWidgetCreateRequest(widget_type="map")

    def test_requires_a_layer_key(self):
        with pytest.raises(ValidationError, match="dataset.*imagery"):
            DashboardWidgetCreateRequest(
                widget_type="map", config={"default_view": "map"}
            )

    def test_dataset_and_imagery_together_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            DashboardWidgetCreateRequest(
                widget_type="map",
                config={
                    "dataset": DATASET_SNAPSHOT,
                    "imagery": IMAGERY_SNAPSHOT,
                },
            )

    @pytest.mark.parametrize("kind", ["dataset", "imagery"])
    def test_layer_must_be_a_dict(self, kind):
        with pytest.raises(ValidationError, match="tile_url"):
            DashboardWidgetCreateRequest(
                widget_type="map", config={kind: "https://tiles.example.com"}
            )

    @pytest.mark.parametrize("kind", ["dataset", "imagery"])
    def test_layer_requires_tile_url(self, kind):
        with pytest.raises(ValidationError, match="tile_url"):
            DashboardWidgetCreateRequest(
                widget_type="map", config={kind: {"name": "no tiles here"}}
            )

    def test_valid_dataset_snapshot_accepted(self):
        body = DashboardWidgetCreateRequest(
            widget_type="map", config={"dataset": DATASET_SNAPSHOT}
        )
        assert body.config["dataset"]["tile_url"]

    def test_valid_imagery_snapshot_accepted(self):
        body = DashboardWidgetCreateRequest(
            widget_type="map", config={"imagery": IMAGERY_SNAPSHOT}
        )
        assert body.config["imagery"]["mosaic_id"] == "abc123"

    def test_extra_config_keys_tolerated(self):
        # The snapshot shape may evolve without a schema change here — only
        # the discriminator and tile_url are load-bearing.
        body = DashboardWidgetCreateRequest(
            widget_type="map",
            config={
                "dataset": {**DATASET_SNAPSHOT, "future_key": 1},
                "viewport": {"bbox": [-54.6, -26.7, -48.0, -22.5], "zoom": 6},
                "title": "Loss layer",
            },
        )
        assert body.config["viewport"]["zoom"] == 6


class TestTextWidgetConfig:
    def test_requires_config(self):
        with pytest.raises(ValidationError, match="'text' string"):
            DashboardWidgetCreateRequest(widget_type="text")

    def test_requires_text_key(self):
        with pytest.raises(ValidationError, match="'text' string"):
            DashboardWidgetCreateRequest(
                widget_type="text", config={"markdown": "# Hello"}
            )

    @pytest.mark.parametrize("text", [None, 42, ["# Hello"], {"md": "x"}])
    def test_text_must_be_a_string(self, text):
        with pytest.raises(ValidationError, match="'text' string"):
            DashboardWidgetCreateRequest(
                widget_type="text", config={"text": text}
            )

    def test_valid_text_widget_accepted(self):
        body = DashboardWidgetCreateRequest(
            widget_type="text", config={"text": "# Notes\nSome context."}
        )
        assert body.config["text"].startswith("# Notes")


class TestUpdateRequests:
    def test_dashboard_update_fields_optional(self):
        body = DashboardUpdateRequest()
        assert body.name is None
        assert body.description is None

    def test_widget_update_fields_optional(self):
        body = DashboardWidgetUpdateRequest()
        assert body.position is None
        assert body.config is None

    def test_widget_update_carries_position_and_config(self):
        body = DashboardWidgetUpdateRequest(
            position=3, config={"default_view": "table"}
        )
        assert body.position == 3
        assert body.config == {"default_view": "table"}
