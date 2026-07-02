"""Tests for the shared insight visibility/edit rules."""

from types import SimpleNamespace

import pytest

from src.api.repositories.insight_access import (
    is_editable_by_user,
    is_visible_to_user,
)


def _row(user_id="owner", is_public=False):
    return SimpleNamespace(user_id=user_id, is_public=is_public)


@pytest.mark.parametrize(
    ("row", "user_id", "visible"),
    [
        (_row(user_id="me"), "me", True),  # own private
        (_row(user_id="someone-else"), "me", False),  # other's private
        (_row(user_id="someone-else", is_public=True), "me", True),  # public
        (_row(user_id=None), "me", False),  # ownerless private
        (_row(user_id=None, is_public=True), "me", True),  # ownerless public
        (_row(user_id="me"), None, False),  # unauthenticated, private
        (_row(user_id="me", is_public=True), None, True),  # unauth, public
    ],
)
def test_is_visible_to_user(row, user_id, visible):
    assert is_visible_to_user(row, user_id) is visible


@pytest.mark.parametrize(
    ("row", "user_id", "editable"),
    [
        (_row(user_id="me"), "me", True),  # own
        (_row(user_id="someone-else"), "me", False),  # other's
        (_row(user_id="someone-else", is_public=True), "me", False),  # public
        (_row(user_id=None), "me", False),  # ownerless
        (_row(user_id="me"), None, False),  # unauthenticated
        (_row(user_id=None), None, False),  # unauthenticated + ownerless
    ],
)
def test_is_editable_by_user(row, user_id, editable):
    assert is_editable_by_user(row, user_id) is editable
