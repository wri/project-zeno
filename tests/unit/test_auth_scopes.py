"""Unit tests for scope-based authorization (src/api/auth/dependencies.py
require_scope). A superuser always passes; a machine key passes iff its scopes
(read from request.state) include the required scope; anyone else is forbidden."""

import types

import pytest
from fastapi import HTTPException

from src.api.auth.dependencies import require_scope
from src.api.auth.scopes import TRACES_READ
from src.api.schemas import UserModel


def _user(user_type: str) -> UserModel:
    return UserModel.model_validate(
        {
            "id": "u",
            "name": "u",
            "email": "u@example.com",
            "user_type": user_type,
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
        }
    )


def _request(token_scopes=None) -> object:
    state = types.SimpleNamespace()
    if token_scopes is not None:
        state.token_scopes = token_scopes
    return types.SimpleNamespace(state=state)


@pytest.mark.asyncio
async def test_superuser_always_allowed_even_without_scopes():
    dep = require_scope(TRACES_READ)
    user = _user("superuser")
    assert await dep(_request(), user=user) is user


@pytest.mark.asyncio
async def test_machine_with_scope_allowed():
    dep = require_scope(TRACES_READ)
    user = _user("machine")
    assert await dep(_request([TRACES_READ]), user=user) is user


@pytest.mark.asyncio
async def test_machine_without_scope_forbidden():
    dep = require_scope(TRACES_READ)
    with pytest.raises(HTTPException) as exc:
        await dep(_request([]), user=_user("machine"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_regular_user_with_no_scope_state_forbidden():
    dep = require_scope(TRACES_READ)
    # No token_scopes on request.state at all (e.g. an RW-token user).
    with pytest.raises(HTTPException) as exc:
        await dep(_request(), user=_user("regular"))
    assert exc.value.status_code == 403
