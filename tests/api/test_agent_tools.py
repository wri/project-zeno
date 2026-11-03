import pytest
from fastapi import Request

from src.api.agent_tools import api_tools
from src.api.app import app
from src.api.auth.dependencies import fetch_user_from_rw_api
from src.api.data_models import UserOrm
from src.api.schemas import UserModel
from tests.conftest import async_session_maker

USER_ID = "mcp-user"
AUTH = {"Authorization": "Bearer secret"}


def user_for_token(request: Request):
    if request.headers.get("authorization") != AUTH["Authorization"]:
        return None
    return UserModel.model_validate(
        {
            "id": USER_ID,
            "name": USER_ID,
            "email": f"{USER_ID}@example.com",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
        }
    )


@pytest.fixture
async def dashboard(client):
    async with async_session_maker() as session:
        session.add(
            UserOrm(id=USER_ID, name=USER_ID, email=f"{USER_ID}@example.com")
        )
        await session.commit()
    app.dependency_overrides[fetch_user_from_rw_api] = user_for_token
    response = await client.post(
        "/api/dashboards",
        headers=AUTH,
        json={
            "name": "Forest watch",
            "aois": [
                {
                    "source": "gadm",
                    "src_id": "BRA",
                    "subtype": "country",
                    "name": "Brazil",
                }
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def by_name(tools):
    return {tool.name: tool for tool in tools}


@pytest.mark.asyncio
async def test_exposes_only_dashboard_list_and_alerts_summary():
    async with api_tools(app, AUTH) as tools:
        assert set(by_name(tools)) == {
            "list_dashboards",
            "summarize_dashboard_alerts",
        }


@pytest.mark.asyncio
async def test_calls_routes_as_the_forwarded_user(dashboard):
    async with api_tools(app, AUTH) as tools:
        result = await by_name(tools)["list_dashboards"].ainvoke({})

    assert "Forest watch" in str(result)


@pytest.mark.asyncio
async def test_rejects_calls_without_valid_credentials(dashboard):
    async with api_tools(app, {}) as tools:
        result = await by_name(tools)["list_dashboards"].ainvoke({})

    assert "Forest watch" not in str(result)
    assert "401" in str(result)
