"""Tests for the add_map_widget agent tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.agent.tools.add_map_widget import (
    _dataset_config,
    _imagery_config,
    add_map_widget,
)
from src.shared.request_context import bound_user_id


def _content(command):
    return command.update["messages"][0].content


def _dashboard(user_id="user-1", name="Paraná"):
    return SimpleNamespace(
        id=uuid4(), user_id=user_id, name=name, is_public=False
    )


def _dataset_state():
    """A dataset state dump with render keys plus prose keys to strip."""
    return {
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "tile_url": "https://tiles.example.com/tcl/{z}/{x}/{y}.png?t=30",
        "context_layer": "driver",
        "context_layers": [
            {"name": "driver", "tile_url": "https://tiles.example.com/d.png"}
        ],
        "parameters": [
            {
                "name": "canopy_cover",
                "description": "Minimum canopy density.",
                "values": [30],
            }
        ],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        # Prose fields that must never end up in widget config.
        "description": "A long dataset description.",
        "methodology": "Hansen et al.",
        "prompt_instructions": "Do things.",
        "cautions": "Beware.",
        "citation": "Someone 2024",
        "reason": "Best match.",
        "analytics_api_endpoint": "tree-cover-loss",
        "content_date": "2024",
    }


def _imagery_state():
    return {
        "tile_url": "https://tiles.example.com/mosaic/{z}/{x}/{y}.png?url=x",
        "tilejson_url": "https://tiles.example.com/tilejson.json?url=x",
        "mosaic_id": "abc123",
        "item_count": 12,
        "date_start": "2024-05-28",
        "date_end": "2024-06-04",
        "target_date": "2024-06-01",
        "window_days": 7,
        "max_cloud_cover": 20,
        "aoi_names": ["Paraná"],
    }


def _patches(dashboard, widget_id="widget-1"):
    return (
        patch(
            "src.api.repositories.dashboard_writer.get_dashboard",
            new=AsyncMock(return_value=dashboard),
        ),
        patch(
            "src.api.repositories.dashboard_writer.add_widget",
            new=AsyncMock(return_value=widget_id),
        ),
    )


async def test_add_map_widget_dataset_from_state():
    dashboard = _dashboard()
    get_dash, add_widget = _patches(dashboard)
    state = {"dataset": _dataset_state(), "dashboard_id": str(dashboard.id)}
    with (
        get_dash,
        add_widget as add_widget_mock,
        bound_user_id("user-1"),
    ):
        command = await add_map_widget.coroutine(
            layer="dataset", state=state, tool_call_id="t1"
        )

    message = command.update["messages"][0]
    assert message.status == "success"
    assert message.response_metadata == {
        "msg_type": "dashboard_updated",
        "dashboard_id": str(dashboard.id),
    }
    assert command.update["dashboard_id"] == str(dashboard.id)
    add_widget_mock.assert_awaited_once()
    kwargs = add_widget_mock.await_args.kwargs
    assert kwargs["widget_type"] == "map"
    config = kwargs["config"]
    assert config["default_view"] == "map"
    assert "viewport" not in config
    dataset = config["dataset"]
    assert set(dataset) == {
        "dataset_id",
        "dataset_name",
        "tile_url",
        "context_layer",
        "context_layers",
        "parameters",
        "start_date",
        "end_date",
    }
    assert dataset["dataset_id"] == 4
    assert dataset["tile_url"].startswith("https://tiles.example.com/tcl")
    # Parameter prose is projected away.
    assert dataset["parameters"] == [{"name": "canopy_cover", "values": [30]}]


async def test_add_map_widget_imagery_from_state():
    dashboard = _dashboard()
    get_dash, add_widget = _patches(dashboard)
    state = {"imagery": _imagery_state(), "dashboard_id": str(dashboard.id)}
    with (
        get_dash,
        add_widget as add_widget_mock,
        bound_user_id("user-1"),
    ):
        command = await add_map_widget.coroutine(
            layer="imagery", state=state, tool_call_id="t1"
        )

    assert command.update["messages"][0].status == "success"
    config = add_widget_mock.await_args.kwargs["config"]
    imagery = config["imagery"]
    assert imagery == _imagery_state()
    assert imagery["mosaic_id"] == "abc123"
    assert imagery["tilejson_url"].startswith("https://")


async def test_add_map_widget_title_passthrough():
    dashboard = _dashboard()
    get_dash, add_widget = _patches(dashboard)
    state = {"dataset": _dataset_state(), "dashboard_id": str(dashboard.id)}
    with (
        get_dash,
        add_widget as add_widget_mock,
        bound_user_id("user-1"),
    ):
        await add_map_widget.coroutine(
            layer="dataset", title="Loss layer", state=state, tool_call_id="t1"
        )
    assert add_widget_mock.await_args.kwargs["config"]["title"] == "Loss layer"


async def test_add_map_widget_falls_back_to_view_context():
    dashboard = _dashboard()
    get_dash, add_widget = _patches(dashboard)
    state = {
        "dataset": _dataset_state(),
        "view_context": {
            "page": "dashboard",
            "dashboard_id": str(dashboard.id),
        },
    }
    with (
        get_dash,
        add_widget,
        bound_user_id("user-1"),
    ):
        command = await add_map_widget.coroutine(
            layer="dataset", state=state, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "success"
    assert command.update["dashboard_id"] == str(dashboard.id)


async def test_add_map_widget_rejects_unknown_layer():
    with bound_user_id("user-1"):
        command = await add_map_widget.coroutine(
            layer="chart", state={}, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "error"
    assert "layer must be" in _content(command)


async def test_add_map_widget_requires_dataset_in_state():
    with bound_user_id("user-1"):
        command = await add_map_widget.coroutine(
            layer="dataset",
            dashboard_id=str(uuid4()),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "No dataset layer selected" in _content(command)


async def test_add_map_widget_requires_dataset_tile_url():
    state = {"dataset": {"dataset_id": 4, "dataset_name": "TCL"}}
    with bound_user_id("user-1"):
        command = await add_map_widget.coroutine(
            layer="dataset",
            dashboard_id=str(uuid4()),
            state=state,
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "No dataset layer selected" in _content(command)


async def test_add_map_widget_requires_imagery_in_state():
    with bound_user_id("user-1"):
        command = await add_map_widget.coroutine(
            layer="imagery",
            dashboard_id=str(uuid4()),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "No imagery built" in _content(command)


async def test_add_map_widget_requires_dashboard():
    with bound_user_id("user-1"):
        command = await add_map_widget.coroutine(
            layer="dataset",
            state={"dataset": _dataset_state()},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "No dashboard to add to" in _content(command)


async def test_add_map_widget_owner_only():
    # A public dashboard someone else owns is readable but not editable.
    dashboard = _dashboard(user_id="someone-else")
    dashboard.is_public = True
    get_dash, add_widget = _patches(dashboard)
    with (
        get_dash,
        add_widget as add_widget_mock,
        bound_user_id("user-1"),
    ):
        command = await add_map_widget.coroutine(
            layer="dataset",
            dashboard_id=str(dashboard.id),
            state={"dataset": _dataset_state()},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "not found or not editable" in _content(command)
    add_widget_mock.assert_not_awaited()


def test_dataset_config_date_fallback_to_state():
    dataset = _dataset_state()
    dataset["start_date"] = None
    dataset["end_date"] = None
    state = {
        "dataset": dataset,
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
    }
    config = _dataset_config(state)
    assert config["start_date"] == "2023-01-01"
    assert config["end_date"] == "2023-12-31"


def test_dataset_config_none_without_tile_url():
    assert _dataset_config({}) is None
    assert _dataset_config({"dataset": {"tile_url": ""}}) is None


def test_imagery_config_none_without_essentials():
    assert _imagery_config({}) is None
    assert _imagery_config({"imagery": {"tile_url": "x"}}) is None
    assert _imagery_config({"imagery": {"mosaic_id": "x"}}) is None
