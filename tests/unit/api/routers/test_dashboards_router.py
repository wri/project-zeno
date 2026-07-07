"""Unit tests for the dashboards router's pure mapping helpers."""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.api.data_models import UserType
from src.api.routers.dashboards import _is_privileged, _row_to_response
from src.api.schemas import UserModel

NOW = datetime(2026, 7, 7, 12, 0, 0)


def _user(user_type=UserType.REGULAR):
    return UserModel(
        id="user-1",
        name="Test User",
        email="test@example.com",
        created_at=NOW,
        updated_at=NOW,
        user_type=user_type,
    )


def _aoi_row(position=0, name="Paraná"):
    return SimpleNamespace(
        id=uuid4(),
        source="gadm",
        src_id="BRA.16_1",
        subtype="state-province",
        name=name,
        position=position,
    )


def _widget_row(widget_type="insight", insight_id=None, config=None):
    return SimpleNamespace(
        id=uuid4(),
        position=0,
        widget_type=widget_type,
        insight_id=insight_id,
        config=config,
        created_at=NOW,
    )


def _insight_row(insight_id):
    return SimpleNamespace(
        id=insight_id,
        user_id="user-1",
        thread_id="thread-1",
        insight_text="Tree cover loss peaked in 2016.",
        follow_up_suggestions=["Compare with 2023"],
        statistics_ids=[],
        charts=[],
        codeact_types=[],
        codeact_contents=[],
        is_public=False,
        created_at=NOW,
    )


def _dashboard_row(aois=None, widgets=None, **overrides):
    row = SimpleNamespace(
        id=uuid4(),
        user_id="user-1",
        name="Paraná",
        description=None,
        is_public=False,
        created_at=NOW,
        updated_at=NOW,
        aois=aois or [],
        widgets=widgets or [],
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


@pytest.mark.parametrize(
    ("user", "privileged"),
    [
        (None, False),
        (_user(UserType.REGULAR), False),
        (_user(UserType.ADMIN), True),
        (_user(UserType.SUPERUSER), True),
    ],
)
def test_is_privileged(user, privileged):
    assert _is_privileged(user) is privileged


class TestRowToResponse:
    def test_maps_dashboard_fields(self):
        row = _dashboard_row(description="Notes", is_public=True)
        response = _row_to_response(row)
        assert response.id == row.id
        assert response.user_id == "user-1"
        assert response.name == "Paraná"
        assert response.description == "Notes"
        assert response.is_public is True
        assert response.aois == []
        assert response.widgets == []

    def test_maps_aois_in_row_order(self):
        row = _dashboard_row(
            aois=[_aoi_row(0, "Paraná"), _aoi_row(1, "Santa Catarina")]
        )
        response = _row_to_response(row)
        assert [a.name for a in response.aois] == [
            "Paraná",
            "Santa Catarina",
        ]
        assert [a.position for a in response.aois] == [0, 1]

    def test_widget_config_none_becomes_empty_dict(self):
        row = _dashboard_row(widgets=[_widget_row(config=None)])
        assert _row_to_response(row).widgets[0].config == {}

    def test_widget_insight_expanded_when_preloaded(self):
        insight_id = uuid4()
        row = _dashboard_row(widgets=[_widget_row(insight_id=insight_id)])
        response = _row_to_response(
            row, insights_by_id={insight_id: _insight_row(insight_id)}
        )
        widget = response.widgets[0]
        assert widget.insight_id == insight_id
        assert widget.insight is not None
        assert widget.insight.insight_text == (
            "Tree cover loss peaked in 2016."
        )

    def test_widget_insight_none_when_not_preloaded(self):
        """A widget whose insight the viewer may not see keeps insight=None."""
        visible_id, hidden_id = uuid4(), uuid4()
        row = _dashboard_row(
            widgets=[
                _widget_row(insight_id=visible_id),
                _widget_row(insight_id=hidden_id),
            ]
        )
        response = _row_to_response(
            row, insights_by_id={visible_id: _insight_row(visible_id)}
        )
        by_id = {w.insight_id: w for w in response.widgets}
        assert by_id[visible_id].insight is not None
        assert by_id[hidden_id].insight is None
        assert by_id[hidden_id].insight_id == hidden_id

    def test_non_insight_widget_has_no_insight(self):
        config = {"dataset": {"tile_url": "https://t.example/x"}}
        row = _dashboard_row(
            widgets=[_widget_row(widget_type="map", config=config)]
        )
        widget = _row_to_response(row).widgets[0]
        assert widget.widget_type == "map"
        assert widget.insight is None
        assert widget.config == config
