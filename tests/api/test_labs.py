"""Tests for labs monitoring endpoint.

These tests validate that the /api/labs/monitoring endpoint returns responses
that are compliant with AgentState from state.py, ensuring consistency between
the labs API and the normal agent workflow.
"""

import json

import pytest


@pytest.mark.asyncio
async def test_labs_monitoring_requires_auth(client):
    """Test that the endpoint requires authentication."""
    response = await client.get(
        "/api/labs/monitoring",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["gadm:BRA"],
        },
    )
    assert response.status_code == 401
    assert "Missing Bearer token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_labs_monitoring_requires_area_ids(client, auth_override):
    """Test that area_ids parameter is required."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400
    assert "area_id is required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_labs_monitoring_invalid_area_id_format(client, auth_override):
    """Test that invalid area_id format returns 400."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["invalid-format"],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400
    assert "Invalid area_id format" in response.json()["detail"]


@pytest.mark.asyncio
async def test_labs_monitoring_invalid_dataset_id(client, auth_override):
    """Test that invalid dataset_id returns 400."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring",
        params={
            "dataset_id": 999,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["gadm:BRA"],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400
    assert "Invalid dataset_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_labs_monitoring_invalid_source(client, auth_override):
    """Test that invalid source type returns 400."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["invalid_source:123"],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400
    assert "Invalid source" in response.json()["detail"]


@pytest.mark.asyncio
async def test_labs_monitoring_area_not_found(client, auth_override):
    """Test that non-existent area returns 404."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["gadm:NONEXISTENT"],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404
    assert "Area not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_labs_monitoring_success(client, auth_override):
    """Test successful monitoring request with real API calls."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["gadm:BRA"],
            # "insights_query": "",  # Empty to skip insights generation
        },
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    data = response.json()

    # Verify response structure matches LabsMonitoringResponse model
    # which is aligned with AgentState from state.py
    assert "aoi_selection" in data
    assert "dataset" in data
    assert "analytics_data" in data
    assert "query" in data
    assert "date_range" in data

    # Verify AgentState-compatible fields are present
    assert "insights" in data  # list[str], aligned with AgentState.insights
    assert "charts_data" in data  # list[ChartDataModel]
    assert "codeact_parts" in data  # list[CodeActPartModel]
    assert "follow_up_suggestions" in data
    assert isinstance(data["insights"], list)
    assert isinstance(data["charts_data"], list)
    assert isinstance(data["codeact_parts"], list)

    # Verify AOI selection matches AOISelectionModel
    assert len(data["aoi_selection"]["aois"]) == 1
    assert data["aoi_selection"]["aois"][0]["src_id"] == "BRA"
    assert "name" in data["aoi_selection"]["aois"][0]
    assert "subtype" in data["aoi_selection"]["aois"][0]
    assert "aoi_type" in data["aoi_selection"]["aois"][0]

    # Verify dataset matches DatasetModel
    assert data["dataset"]["dataset_id"] == 4
    assert data["dataset"]["dataset_name"] == "Tree cover loss"

    # Verify date range matches DateRangeModel
    assert data["date_range"]["start_date"] == "2024-01-01"
    assert data["date_range"]["end_date"] == "2024-12-31"

    # Verify analytics data matches AnalyticsDataModel
    assert len(data["analytics_data"]) > 0
    assert "data" in data["analytics_data"][0]
    assert "source_url" in data["analytics_data"][0]
    assert "dataset_name" in data["analytics_data"][0]
    assert "start_date" in data["analytics_data"][0]
    assert "end_date" in data["analytics_data"][0]
    assert "aoi_names" in data["analytics_data"][0]


@pytest.mark.asyncio
async def test_labs_monitoring_response_matches_agent_state(
    client, auth_override
):
    """
    Test that response structure is compliant with AgentState from state.py.

    This ensures the labs endpoint returns state updates in the same format
    as the normal agent workflow, enabling consistent frontend handling.
    """
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["gadm:BRA"],
            "insights_query": "",  # Empty to skip insights generation
        },
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    data = response.json()

    # Validate against AgentState TypedDict structure:
    # - aoi_selection: AOISelection (name: str, aois: list[dict])
    assert isinstance(data["aoi_selection"]["name"], str)
    assert isinstance(data["aoi_selection"]["aois"], list)

    # - dataset: dict
    assert isinstance(data["dataset"], dict)

    # - analytics_data: list[AnalyticsData]
    assert isinstance(data["analytics_data"], list)
    if data["analytics_data"]:
        analytics_item = data["analytics_data"][0]
        # Validate AnalyticsData TypedDict fields
        assert "dataset_name" in analytics_item
        assert "start_date" in analytics_item
        assert "end_date" in analytics_item
        assert "source_url" in analytics_item
        assert "data" in analytics_item
        assert "aoi_names" in analytics_item

    # - insights: list (AgentState field)
    assert isinstance(data["insights"], list)

    # - charts_data: list (AgentState field)
    assert isinstance(data["charts_data"], list)

    # - codeact_parts: list[CodeActPart] (AgentState field)
    assert isinstance(data["codeact_parts"], list)


# Streaming endpoint tests


@pytest.mark.asyncio
async def test_labs_monitoring_stream_requires_auth(client):
    """Test that the streaming endpoint requires authentication."""
    response = await client.get(
        "/api/labs/monitoring/stream",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["gadm:BRA"],
        },
    )
    assert response.status_code == 401
    assert "Missing Bearer token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_labs_monitoring_stream_requires_area_ids(client, auth_override):
    """Test that streaming endpoint returns error event for missing area_ids."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring/stream",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    # Streaming endpoint returns 200 but streams error event
    assert response.status_code == 200

    # Parse NDJSON stream
    lines = response.text.strip().split("\n")
    assert len(lines) >= 1

    event = json.loads(lines[0])
    assert event["type"] == "error"
    assert "area_id is required" in event["data"]["message"]


@pytest.mark.asyncio
async def test_labs_monitoring_stream_invalid_dataset_id(
    client, auth_override
):
    """Test that streaming endpoint returns error event for invalid dataset_id."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring/stream",
        params={
            "dataset_id": 999,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["gadm:BRA"],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200

    lines = response.text.strip().split("\n")
    event = json.loads(lines[0])
    assert event["type"] == "error"
    assert "Invalid dataset_id" in event["data"]["message"]


@pytest.mark.asyncio
async def test_labs_monitoring_stream_invalid_area_id_format(
    client, auth_override
):
    """Test that streaming endpoint returns error event for invalid area_id format."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring/stream",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["invalid-format"],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200

    lines = response.text.strip().split("\n")
    event = json.loads(lines[0])
    assert event["type"] == "error"
    assert "Invalid area_id format" in event["data"]["message"]


@pytest.mark.asyncio
async def test_labs_monitoring_stream_success(client, auth_override):
    """Test successful streaming monitoring request."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring/stream",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["gadm:BRA"],
            "insights_query": "",  # Empty to skip insights generation
        },
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200

    # Parse NDJSON stream
    lines = response.text.strip().split("\n")
    events = [json.loads(line) for line in lines if line]

    # Should have at least metadata, analytics_data, and complete events
    event_types = [e["type"] for e in events]
    assert "metadata" in event_types
    assert "analytics_data" in event_types
    assert "complete" in event_types

    # Verify metadata event structure
    metadata_event = next(e for e in events if e["type"] == "metadata")
    assert "query" in metadata_event["data"]
    assert "date_range" in metadata_event["data"]
    assert "aoi_selection" in metadata_event["data"]
    assert "dataset" in metadata_event["data"]

    # Verify analytics_data event structure
    analytics_event = next(e for e in events if e["type"] == "analytics_data")
    assert "analytics_data" in analytics_event["data"]
    assert len(analytics_event["data"]["analytics_data"]) > 0

    # Verify dataset info
    assert metadata_event["data"]["dataset"]["dataset_id"] == 4
    assert (
        metadata_event["data"]["dataset"]["dataset_name"] == "Tree cover loss"
    )


@pytest.mark.asyncio
async def test_labs_monitoring_stream_with_insights(client, auth_override):
    """Test streaming monitoring request with insights generation."""
    auth_override("test-user-1")

    response = await client.get(
        "/api/labs/monitoring/stream",
        params={
            "dataset_id": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area_ids": ["gadm:BRA"],
            "insights_query": "Analyse this data",
        },
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200

    # Parse NDJSON stream
    lines = response.text.strip().split("\n")
    events = [json.loads(line) for line in lines if line]

    event_types = [e["type"] for e in events]

    # Should have metadata, analytics_data, insights, and complete events
    assert "metadata" in event_types
    assert "analytics_data" in event_types
    assert "insights" in event_types
    assert "complete" in event_types

    # Verify insights event structure
    insights_event = next(e for e in events if e["type"] == "insights")
    assert "insights" in insights_event["data"]
    assert "charts_data" in insights_event["data"]
    assert "codeact_parts" in insights_event["data"]
    assert "follow_up_suggestions" in insights_event["data"]
    assert isinstance(insights_event["data"]["insights"], list)
    assert isinstance(insights_event["data"]["charts_data"], list)
