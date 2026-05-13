"""Tests for the superuser-gated admin endpoints."""

import pytest

from src.api.data_models import UserOrm, UserType
from tests.conftest import async_session_maker


async def _seed_user(
    user_id: str,
    email: str,
    user_type: UserType = UserType.REGULAR,
    name: str | None = None,
) -> UserOrm:
    async with async_session_maker() as session:
        u = UserOrm(
            id=user_id,
            name=name or user_id,
            email=email,
            user_type=user_type.value,
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


# --- GET /api/admin/users --------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_requires_auth(client):
    """Unauthenticated requests must return 401."""
    response = await client.get("/api/admin/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_users_requires_superuser_not_regular(
    client, auth_override
):
    """A regular user must receive 403."""
    regular = await _seed_user(
        "regular-list", "regular_list@example.com", UserType.REGULAR
    )
    auth_override(regular.id)

    response = await client.get(
        "/api/admin/users",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_requires_superuser_not_admin(
    client, auth_override, admin_user_factory
):
    """An admin (not superuser) must receive 403 — admins cannot list users."""
    admin = await admin_user_factory("admin_list@example.com")
    auth_override(admin.id)

    response = await client.get(
        "/api/admin/users",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_requires_superuser_not_pro(client, auth_override):
    """A pro user must receive 403."""
    pro = await _seed_user(
        "pro-list", "pro_list@example.com", UserType.PRO
    )
    auth_override(pro.id)

    response = await client.get(
        "/api/admin/users",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_no_filter_returns_capped_list(
    client, auth_override, superuser_factory
):
    """With no filter, the endpoint returns at most 50 users."""
    su = await superuser_factory("su_cap@example.com")
    auth_override(su.id)

    # Seed 55 additional users so that, counting the superuser, there are 56 total.
    async with async_session_maker() as session:
        for i in range(55):
            session.add(
                UserOrm(
                    id=f"bulk-user-{i:03d}",
                    name=f"Bulk {i}",
                    email=f"bulk{i:03d}@example.com",
                    user_type=UserType.REGULAR.value,
                )
            )
        await session.commit()

    response = await client.get(
        "/api/admin/users",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 50


@pytest.mark.asyncio
async def test_list_users_email_exact_match(
    client, auth_override, superuser_factory
):
    """An exact email match returns the matching user."""
    su = await superuser_factory("su_exact@example.com")
    auth_override(su.id)
    await _seed_user("target-exact", "target_exact@example.com")

    response = await client.get(
        "/api/admin/users",
        params={"email": "target_exact@example.com"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    data = response.json()
    emails = {u["email"] for u in data}
    assert "target_exact@example.com" in emails


@pytest.mark.asyncio
async def test_list_users_email_substring_match(
    client, auth_override, superuser_factory
):
    """Substring match returns all users whose email contains the query."""
    su = await superuser_factory("su_sub@example.com")
    auth_override(su.id)
    await _seed_user("alice-1", "alice@example.com")
    await _seed_user("alicia-1", "alicia@example.com")
    await _seed_user("bob-1", "bob@example.com")

    response = await client.get(
        "/api/admin/users",
        params={"email": "ali"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    data = response.json()
    emails = {u["email"] for u in data}
    assert "alice@example.com" in emails
    assert "alicia@example.com" in emails
    assert "bob@example.com" not in emails


@pytest.mark.asyncio
async def test_list_users_email_case_insensitive(
    client, auth_override, superuser_factory
):
    """Email search is case-insensitive."""
    su = await superuser_factory("su_case@example.com")
    auth_override(su.id)
    await _seed_user("mixed-case", "MixedCase@Example.COM")

    response = await client.get(
        "/api/admin/users",
        params={"email": "mixedcase"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    data = response.json()
    emails = {u["email"] for u in data}
    assert "MixedCase@Example.COM" in emails


@pytest.mark.asyncio
async def test_list_users_no_matches_returns_empty(
    client, auth_override, superuser_factory
):
    """A query with no matches returns an empty list."""
    su = await superuser_factory("su_none@example.com")
    auth_override(su.id)

    response = await client.get(
        "/api/admin/users",
        params={"email": "no-such-email-anywhere"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_users_response_shape(
    client, auth_override, superuser_factory
):
    """Response items use the UserModel JSON shape (camelCase, includes userType)."""
    su = await superuser_factory("su_shape@example.com")
    auth_override(su.id)
    target = await _seed_user(
        "target-shape", "target_shape@example.com", UserType.PRO
    )

    response = await client.get(
        "/api/admin/users",
        params={"email": "target_shape"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    item = data[0]
    assert item["id"] == target.id
    assert item["email"] == target.email
    assert item["userType"] == UserType.PRO.value
    # createdAt and updatedAt should be present (camelCase) per UserModel config
    assert "createdAt" in item
    assert "updatedAt" in item


# --- GET /api/admin/users — pagination ------------------------------------


@pytest.mark.asyncio
async def test_list_users_respects_custom_limit(
    client, auth_override, superuser_factory
):
    """Custom limit caps the response size."""
    su = await superuser_factory("su_lim@example.com")
    auth_override(su.id)

    async with async_session_maker() as session:
        for i in range(10):
            session.add(
                UserOrm(
                    id=f"lim-user-{i:02d}",
                    name=f"Lim {i}",
                    email=f"lim{i:02d}@example.com",
                    user_type=UserType.REGULAR.value,
                )
            )
        await session.commit()

    response = await client.get(
        "/api/admin/users",
        params={"limit": 5},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 5


@pytest.mark.asyncio
async def test_list_users_respects_offset(
    client, auth_override, superuser_factory
):
    """offset + limit returns the expected slice with no overlap between pages."""
    su = await superuser_factory("su_off@example.com")
    auth_override(su.id)

    # Seed users with explicit, distinct created_at so ordering is deterministic.
    from datetime import datetime, timedelta

    base = datetime(2025, 1, 1, 12, 0, 0)
    async with async_session_maker() as session:
        for i in range(5):
            session.add(
                UserOrm(
                    id=f"off-user-{i:02d}",
                    name=f"Off {i}",
                    email=f"off{i:02d}@example.com",
                    user_type=UserType.REGULAR.value,
                    created_at=base + timedelta(seconds=i),
                    updated_at=base + timedelta(seconds=i),
                )
            )
        await session.commit()

    page1 = await client.get(
        "/api/admin/users",
        params={"limit": 2, "offset": 0},
        headers={"Authorization": "Bearer test-token"},
    )
    page2 = await client.get(
        "/api/admin/users",
        params={"limit": 2, "offset": 2},
        headers={"Authorization": "Bearer test-token"},
    )
    assert page1.status_code == 200
    assert page2.status_code == 200
    page1_ids = [u["id"] for u in page1.json()]
    page2_ids = [u["id"] for u in page2.json()]

    assert len(page1_ids) == 2
    assert len(page2_ids) == 2
    # No overlap between pages
    assert set(page1_ids).isdisjoint(set(page2_ids))
    # created_at DESC: page1 should contain the newest seeded users
    # The superuser itself was created after the seeded users in this test
    # (`superuser_factory` uses datetime.now default), so it lands on page1.
    # We just verify that no offset-style duplicates appear.


@pytest.mark.asyncio
async def test_list_users_offset_past_end_returns_empty(
    client, auth_override, superuser_factory
):
    """Offset beyond the total returns an empty list."""
    su = await superuser_factory("su_past@example.com")
    auth_override(su.id)
    await _seed_user("past-user-1", "past1@example.com")
    # Total = 2 users (the superuser + one seeded). offset=10 ⇒ empty.

    response = await client.get(
        "/api/admin/users",
        params={"offset": 10},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_users_limit_caps_at_200(
    client, auth_override, superuser_factory
):
    """limit > 200 is rejected with 422."""
    su = await superuser_factory("su_max@example.com")
    auth_override(su.id)

    response = await client.get(
        "/api/admin/users",
        params={"limit": 500},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_users_limit_zero_rejected(
    client, auth_override, superuser_factory
):
    """limit=0 is rejected with 422."""
    su = await superuser_factory("su_zero@example.com")
    auth_override(su.id)

    response = await client.get(
        "/api/admin/users",
        params={"limit": 0},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_users_negative_offset_rejected(
    client, auth_override, superuser_factory
):
    """offset < 0 is rejected with 422."""
    su = await superuser_factory("su_neg@example.com")
    auth_override(su.id)

    response = await client.get(
        "/api/admin/users",
        params={"offset": -1},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_users_pagination_with_email_filter(
    client, auth_override, superuser_factory
):
    """Pagination applies on top of an email filter."""
    su = await superuser_factory("su_combo@example.com")
    auth_override(su.id)

    for i in range(5):
        await _seed_user(
            f"alice-pg-{i}", f"alice_pg_{i}@example.com", UserType.REGULAR
        )

    page1 = await client.get(
        "/api/admin/users",
        params={"email": "alice_pg", "limit": 2, "offset": 0},
        headers={"Authorization": "Bearer test-token"},
    )
    page2 = await client.get(
        "/api/admin/users",
        params={"email": "alice_pg", "limit": 2, "offset": 2},
        headers={"Authorization": "Bearer test-token"},
    )
    assert page1.status_code == 200
    assert page2.status_code == 200
    p1_ids = [u["id"] for u in page1.json()]
    p2_ids = [u["id"] for u in page2.json()]
    assert len(p1_ids) == 2
    assert len(p2_ids) == 2
    assert set(p1_ids).isdisjoint(set(p2_ids))
    # All returned users should match the filter (`alice_pg`).
    for item in page1.json() + page2.json():
        assert "alice_pg" in item["email"].lower()
