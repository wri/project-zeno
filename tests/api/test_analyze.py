"""Tests for the analyze endpoint: auth and request validation."""

from src.api.data_models import UserOrm
from tests.conftest import async_session_maker

PAYLOAD = {
    "aois": [
        {"source": "gadm", "src_id": "CRI", "subtype": "country"},
    ],
    "dataset_id": 999,
    "start_date": "2020-01-01",
    "end_date": "2020-12-31",
}


async def _create_user(user_id: str) -> UserOrm:
    async with async_session_maker() as session:
        user = UserOrm(
            id=user_id,
            name=user_id,
            email=f"{user_id}@example.com",
        )
        session.add(user)
        await session.commit()
        return user


async def test_analyze_requires_auth(client):
    response = await client.post("/api/analyze", json=PAYLOAD)
    assert response.status_code == 401


async def test_analyze_rejects_unknown_dataset_id(client, auth_override):
    await _create_user("user-analyze")
    auth_override("user-analyze")

    response = await client.post(
        "/api/analyze",
        json=PAYLOAD,
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    assert "Unknown dataset_id" in response.json()["detail"]
