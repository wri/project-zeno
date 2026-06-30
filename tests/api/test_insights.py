"""Tests for insight endpoints: list, get, toggle public, auth and ownership."""

import uuid

import pytest

from src.api.app import app
from src.api.auth.dependencies import fetch_user_from_rw_api
from src.api.data_models import (
    InsightChartOrm,
    InsightOrm,
    StatisticsOrm,
    UserOrm,
)
from tests.conftest import async_session_maker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_user(user_id: str, email: str | None = None) -> UserOrm:
    async with async_session_maker() as session:
        user = UserOrm(
            id=user_id,
            name=user_id,
            email=email or f"{user_id}@example.com",
        )
        session.add(user)
        await session.commit()
        return user


async def _create_statistic(
    *,
    user_id: str | None,
    dataset_name: str,
    aoi_names: list[str],
) -> StatisticsOrm:
    async with async_session_maker() as session:
        row = StatisticsOrm(
            user_id=user_id,
            thread_id="thread-1",
            dataset_name=dataset_name,
            start_date="2020-01-01",
            end_date="2020-12-31",
            aoi_names=aoi_names,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def _create_insight(
    *,
    user_id: str | None,
    thread_id: str | None = "thread-1",
    title: str = "Test Insight",
    is_public: bool = False,
    insight_text: str = "Sample insight text",
    statistics_ids: list[str] | None = None,
) -> InsightOrm:
    async with async_session_maker() as session:
        row = InsightOrm(
            user_id=user_id,
            thread_id=thread_id,
            insight_text=insight_text,
            follow_up_suggestions=["Try a different area"],
            statistics_ids=statistics_ids or [],
            codeact_types=["code_block"],
            codeact_contents=["print('hi')"],
            is_public=is_public,
        )
        session.add(row)
        await session.flush()
        chart = InsightChartOrm(
            insight_id=row.id,
            position=0,
            title=title,
            chart_type="bar",
            x_axis="x",
            y_axis="y",
            chart_data=[{"x": 1, "y": 2}],
        )
        session.add(chart)
        await session.commit()
        await session.refresh(row)
        return row


# ---------------------------------------------------------------------------
# GET /api/insights (list)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_insights_requires_auth(client):
    response = await client.get("/api/insights")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_insights_returns_own(client, auth_override):
    user = await _create_user("list-owner")
    auth_override(user.id)
    await _create_user("someone-else")

    i1 = await _create_insight(user_id=user.id, thread_id="t1")
    i2 = await _create_insight(user_id=user.id, thread_id="t2")
    await _create_insight(user_id="someone-else", thread_id="t3")

    response = await client.get(
        "/api/insights", headers={"Authorization": "Bearer t"}
    )
    assert response.status_code == 200
    ids = {i["id"] for i in response.json()}
    assert str(i1.id) in ids
    assert str(i2.id) in ids
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_list_insights_filter_by_thread(client, auth_override):
    user = await _create_user("filter-owner")
    auth_override(user.id)

    await _create_insight(user_id=user.id, thread_id="thread-a")
    i2 = await _create_insight(user_id=user.id, thread_id="thread-b")
    await _create_insight(user_id=user.id, thread_id="thread-a")

    response = await client.get(
        "/api/insights",
        params={"thread_id": "thread-b"},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == str(i2.id)


@pytest.mark.asyncio
async def test_list_insights_filter_by_text(client, auth_override):
    user = await _create_user("text-owner")
    auth_override(user.id)

    match = await _create_insight(
        user_id=user.id, insight_text="Deforestation spiked in 2021"
    )
    await _create_insight(
        user_id=user.id, insight_text="Tree cover gain was steady"
    )

    response = await client.get(
        "/api/insights",
        params={"text": "deforestation"},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200
    data = response.json()
    assert [i["id"] for i in data] == [str(match.id)]


@pytest.mark.asyncio
async def test_list_insights_filter_by_dataset(client, auth_override):
    user = await _create_user("dataset-owner")
    auth_override(user.id)

    stat_a = await _create_statistic(
        user_id=user.id, dataset_name="Tree cover loss", aoi_names=["Brazil"]
    )
    stat_b = await _create_statistic(
        user_id=user.id, dataset_name="Tree cover gain", aoi_names=["Brazil"]
    )
    match = await _create_insight(
        user_id=user.id, statistics_ids=[str(stat_a.id)]
    )
    await _create_insight(user_id=user.id, statistics_ids=[str(stat_b.id)])
    await _create_insight(user_id=user.id, statistics_ids=[])

    response = await client.get(
        "/api/insights",
        params={"dataset": "Tree cover loss"},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200
    data = response.json()
    assert [i["id"] for i in data] == [str(match.id)]


@pytest.mark.asyncio
async def test_list_insights_filter_by_aoi(client, auth_override):
    user = await _create_user("aoi-owner")
    auth_override(user.id)

    stat_a = await _create_statistic(
        user_id=user.id,
        dataset_name="Tree cover loss",
        aoi_names=["Brazil", "Peru"],
    )
    stat_b = await _create_statistic(
        user_id=user.id, dataset_name="Tree cover loss", aoi_names=["Kenya"]
    )
    match = await _create_insight(
        user_id=user.id, statistics_ids=[str(stat_a.id)]
    )
    await _create_insight(user_id=user.id, statistics_ids=[str(stat_b.id)])

    response = await client.get(
        "/api/insights",
        params={"aoi": "Peru"},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200
    data = response.json()
    assert [i["id"] for i in data] == [str(match.id)]


@pytest.mark.asyncio
async def test_list_insights_filter_by_aoi_and_dataset(client, auth_override):
    user = await _create_user("aoi-dataset-owner")
    auth_override(user.id)

    stat_match = await _create_statistic(
        user_id=user.id, dataset_name="Tree cover loss", aoi_names=["Brazil"]
    )
    # Same AOI, different dataset — must be excluded.
    stat_other = await _create_statistic(
        user_id=user.id, dataset_name="Tree cover gain", aoi_names=["Brazil"]
    )
    match = await _create_insight(
        user_id=user.id, statistics_ids=[str(stat_match.id)]
    )
    await _create_insight(user_id=user.id, statistics_ids=[str(stat_other.id)])

    response = await client.get(
        "/api/insights",
        params={"aoi": "Brazil", "dataset": "Tree cover loss"},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200
    data = response.json()
    assert [i["id"] for i in data] == [str(match.id)]


@pytest.mark.asyncio
async def test_list_insights_filter_no_matching_statistics(
    client, auth_override
):
    user = await _create_user("no-match-owner")
    auth_override(user.id)

    stat = await _create_statistic(
        user_id=user.id, dataset_name="Tree cover loss", aoi_names=["Brazil"]
    )
    await _create_insight(user_id=user.id, statistics_ids=[str(stat.id)])

    response = await client.get(
        "/api/insights",
        params={"dataset": "Nonexistent dataset"},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_insights_ordered_newest_first(client, auth_override):
    user = await _create_user("order-owner")
    auth_override(user.id)

    i1 = await _create_insight(user_id=user.id, title="First")
    i2 = await _create_insight(user_id=user.id, title="Second")

    response = await client.get(
        "/api/insights", headers={"Authorization": "Bearer t"}
    )
    ids = [i["id"] for i in response.json()]
    assert ids == [str(i2.id), str(i1.id)]


# ---------------------------------------------------------------------------
# GET /api/insights/{insight_id} (single)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_own_private_insight(client, auth_override):
    user = await _create_user("get-owner")
    auth_override(user.id)

    insight = await _create_insight(user_id=user.id)

    response = await client.get(
        f"/api/insights/{insight.id}",
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(insight.id)
    assert body["charts"][0]["title"] == "Test Insight"
    assert body["is_public"] is False
    assert body["codeact_parts"] == [
        {"type": "code_block", "content": "print('hi')"}
    ]


@pytest.mark.asyncio
async def test_get_insight_with_null_thread_id(client, auth_override):
    """Insights created without a thread_id (e.g. via /api/analyze without a
    thread_id) must still serialize — thread_id is nullable."""
    user = await _create_user("null-thread-owner")
    auth_override(user.id)

    insight = await _create_insight(user_id=user.id, thread_id=None)

    response = await client.get(
        f"/api/insights/{insight.id}",
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200
    assert response.json()["thread_id"] is None


@pytest.mark.asyncio
async def test_get_private_insight_other_user_returns_404(
    client, auth_override
):
    owner = await _create_user("insight-owner")
    other = await _create_user("insight-other")
    insight = await _create_insight(user_id=owner.id)

    auth_override(other.id)
    response = await client.get(
        f"/api/insights/{insight.id}",
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_private_insight_no_auth_returns_401(client):
    user = await _create_user("private-noauth")
    insight = await _create_insight(user_id=user.id)

    response = await client.get(f"/api/insights/{insight.id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_public_insight_no_auth(client):
    user = await _create_user("pub-owner")
    insight = await _create_insight(user_id=user.id, is_public=True)

    response = await client.get(f"/api/insights/{insight.id}")
    assert response.status_code == 200
    assert response.json()["is_public"] is True


@pytest.mark.asyncio
async def test_get_public_insight_other_user(client, auth_override):
    owner = await _create_user("pub-insight-owner")
    viewer = await _create_user("pub-insight-viewer")
    insight = await _create_insight(user_id=owner.id, is_public=True)

    auth_override(viewer.id)
    response = await client.get(
        f"/api/insights/{insight.id}",
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_nonexistent_insight_returns_404(client, auth_override):
    await _create_user("nobody")
    auth_override("nobody")

    fake_id = uuid.uuid4()
    response = await client.get(
        f"/api/insights/{fake_id}",
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_access_private_insight(
    client, auth_override, admin_user_factory
):
    owner = await _create_user("admin-test-owner")
    admin = await admin_user_factory("insight-admin@example.com")
    insight = await _create_insight(user_id=owner.id)

    auth_override(admin.id)
    response = await client.get(
        f"/api/insights/{insight.id}",
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# PATCH /api/insights/{insight_id}/public (toggle)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_toggle_public_requires_auth(client):
    user = await _create_user("toggle-noauth")
    insight = await _create_insight(user_id=user.id)

    response = await client.patch(
        f"/api/insights/{insight.id}/public",
        json={"is_public": True},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_toggle_public_on(client, auth_override):
    user = await _create_user("toggle-on")
    auth_override(user.id)
    insight = await _create_insight(user_id=user.id)

    response = await client.patch(
        f"/api/insights/{insight.id}/public",
        headers={"Authorization": "Bearer t"},
        json={"is_public": True},
    )
    assert response.status_code == 200
    assert response.json()["is_public"] is True


@pytest.mark.asyncio
async def test_toggle_public_off(client, auth_override):
    user = await _create_user("toggle-off")
    auth_override(user.id)
    insight = await _create_insight(user_id=user.id, is_public=True)

    response = await client.patch(
        f"/api/insights/{insight.id}/public",
        headers={"Authorization": "Bearer t"},
        json={"is_public": False},
    )
    assert response.status_code == 200
    assert response.json()["is_public"] is False


@pytest.mark.asyncio
async def test_toggle_other_user_returns_404(client, auth_override):
    owner = await _create_user("toggle-owner")
    other = await _create_user("toggle-other")
    insight = await _create_insight(user_id=owner.id)

    auth_override(other.id)
    response = await client.patch(
        f"/api/insights/{insight.id}/public",
        headers={"Authorization": "Bearer t"},
        json={"is_public": True},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_toggle_nonexistent_returns_404(client, auth_override):
    await _create_user("toggle-miss")
    auth_override("toggle-miss")

    fake_id = uuid.uuid4()
    response = await client.patch(
        f"/api/insights/{fake_id}/public",
        headers={"Authorization": "Bearer t"},
        json={"is_public": True},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_toggle_any_insight(
    client, auth_override, admin_user_factory
):
    owner = await _create_user("admin-toggle-owner")
    admin = await admin_user_factory("toggle-admin@example.com")
    insight = await _create_insight(user_id=owner.id)

    auth_override(admin.id)
    response = await client.patch(
        f"/api/insights/{insight.id}/public",
        headers={"Authorization": "Bearer t"},
        json={"is_public": True},
    )
    assert response.status_code == 200
    assert response.json()["is_public"] is True


@pytest.mark.asyncio
async def test_toggle_invalid_body_returns_422(client, auth_override):
    user = await _create_user("toggle-bad")
    auth_override(user.id)
    insight = await _create_insight(user_id=user.id)

    response = await client.patch(
        f"/api/insights/{insight.id}/public",
        headers={"Authorization": "Bearer t"},
        json={"is_public": "not-a-bool"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Integration: toggle then verify public access
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_make_public_then_access_without_auth(client, auth_override):
    user = await _create_user("e2e-owner")
    auth_override(user.id)
    insight = await _create_insight(user_id=user.id)

    # Toggle public
    await client.patch(
        f"/api/insights/{insight.id}/public",
        headers={"Authorization": "Bearer t"},
        json={"is_public": True},
    )

    # Access without auth
    response = await client.get(f"/api/insights/{insight.id}")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Revoke
    await client.patch(
        f"/api/insights/{insight.id}/public",
        headers={"Authorization": "Bearer t"},
        json={"is_public": False},
    )

    # Remove auth override so this request is truly anonymous.
    app.dependency_overrides.pop(fetch_user_from_rw_api, None)

    # Access without auth should now fail
    response = await client.get(f"/api/insights/{insight.id}")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_insight_response_shape(client, auth_override):
    user = await _create_user("shape-owner")
    auth_override(user.id)
    await _create_insight(user_id=user.id)

    response = await client.get(
        "/api/insights", headers={"Authorization": "Bearer t"}
    )
    assert response.status_code == 200
    item = response.json()[0]

    expected_keys = {
        "id",
        "user_id",
        "thread_id",
        "insight_text",
        "follow_up_suggestions",
        "charts",
        "codeact_parts",
        "is_public",
        "statistics_ids",
        "created_at",
    }
    assert set(item.keys()) == expected_keys
    assert len(item["charts"]) == 1
    assert set(item["charts"][0].keys()) == {
        "id",
        "position",
        "title",
        "chart_type",
        "x_axis",
        "y_axis",
        "color_field",
        "stack_field",
        "group_field",
        "series_fields",
        "chart_data",
    }
