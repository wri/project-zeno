"""Tests for the superuser-gated admin endpoints."""

import csv
import io
import json
import re
from datetime import datetime

import pytest
from sqlalchemy import select

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
    pro = await _seed_user("pro-list", "pro_list@example.com", UserType.PRO)
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


# --- PATCH /api/admin/users/{user_id}/user-type ---------------------------


@pytest.mark.asyncio
async def test_patch_user_type_requires_auth(client):
    """Unauthenticated PATCH must return 401."""
    response = await client.patch(
        "/api/admin/users/some-id/user-type",
        json={"user_type": "admin"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_user_type_requires_superuser_not_regular(
    client, auth_override
):
    """A regular user must receive 403."""
    regular = await _seed_user(
        "reg-patch", "reg_patch@example.com", UserType.REGULAR
    )
    target = await _seed_user(
        "target-patch-r", "target_patch_r@example.com", UserType.REGULAR
    )
    auth_override(regular.id)

    response = await client.patch(
        f"/api/admin/users/{target.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "admin"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_patch_user_type_requires_superuser_not_admin(
    client, auth_override, admin_user_factory
):
    """An admin (not superuser) must receive 403 — admins cannot promote."""
    admin = await admin_user_factory("admin_patch@example.com")
    target = await _seed_user(
        "target-patch-a", "target_patch_a@example.com", UserType.REGULAR
    )
    auth_override(admin.id)

    response = await client.patch(
        f"/api/admin/users/{target.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "pro"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_patch_user_type_requires_superuser_not_pro(
    client, auth_override
):
    """A pro user must receive 403."""
    pro = await _seed_user("pro-patch", "pro_patch@example.com", UserType.PRO)
    target = await _seed_user(
        "target-patch-p", "target_patch_p@example.com", UserType.REGULAR
    )
    auth_override(pro.id)

    response = await client.patch(
        f"/api/admin/users/{target.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "admin"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_superuser_can_promote_user_to_admin(
    client, auth_override, superuser_factory
):
    """Superuser promotes a regular user to admin."""
    su = await superuser_factory("su_promote_a@example.com")
    target = await _seed_user(
        "target-promote-a", "target_promote_a@example.com", UserType.REGULAR
    )
    auth_override(su.id)

    response = await client.patch(
        f"/api/admin/users/{target.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "admin"},
    )
    assert response.status_code == 200
    assert response.json()["userType"] == UserType.ADMIN.value

    async with async_session_maker() as session:
        result = await session.execute(
            select(UserOrm).where(UserOrm.id == target.id)
        )
        db_user = result.scalar_one()
        assert db_user.user_type == UserType.ADMIN.value


@pytest.mark.asyncio
async def test_superuser_can_promote_user_to_pro(
    client, auth_override, superuser_factory
):
    """Superuser promotes a regular user to pro."""
    su = await superuser_factory("su_promote_p@example.com")
    target = await _seed_user(
        "target-promote-p", "target_promote_p@example.com", UserType.REGULAR
    )
    auth_override(su.id)

    response = await client.patch(
        f"/api/admin/users/{target.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "pro"},
    )
    assert response.status_code == 200
    assert response.json()["userType"] == UserType.PRO.value


@pytest.mark.asyncio
async def test_superuser_can_promote_user_to_superuser(
    client, auth_override, superuser_factory
):
    """Superuser promotes another user to superuser (multiple superusers allowed)."""
    su = await superuser_factory("su_promote_su@example.com")
    target = await _seed_user(
        "target-promote-su", "target_promote_su@example.com", UserType.REGULAR
    )
    auth_override(su.id)

    response = await client.patch(
        f"/api/admin/users/{target.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "superuser"},
    )
    assert response.status_code == 200
    assert response.json()["userType"] == UserType.SUPERUSER.value


@pytest.mark.asyncio
async def test_superuser_can_demote_admin_to_regular(
    client, auth_override, superuser_factory, admin_user_factory
):
    """Superuser demotes an admin back to regular."""
    su = await superuser_factory("su_demote@example.com")
    target_admin = await admin_user_factory("demote_me@example.com")
    auth_override(su.id)

    response = await client.patch(
        f"/api/admin/users/{target_admin.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "regular"},
    )
    assert response.status_code == 200
    assert response.json()["userType"] == UserType.REGULAR.value


@pytest.mark.asyncio
async def test_superuser_cannot_self_demote(
    client, auth_override, superuser_factory
):
    """Superuser cannot demote themselves; expect 400."""
    su = await superuser_factory("su_self_demote@example.com")
    auth_override(su.id)

    response = await client.patch(
        f"/api/admin/users/{su.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "regular"},
    )
    assert response.status_code == 400

    # DB unchanged
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserOrm).where(UserOrm.id == su.id)
        )
        db_user = result.scalar_one()
        assert db_user.user_type == UserType.SUPERUSER.value


@pytest.mark.asyncio
async def test_superuser_can_set_self_to_superuser(
    client, auth_override, superuser_factory
):
    """A no-op self-update to superuser is allowed."""
    su = await superuser_factory("su_self_noop@example.com")
    auth_override(su.id)

    response = await client.patch(
        f"/api/admin/users/{su.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "superuser"},
    )
    assert response.status_code == 200
    assert response.json()["userType"] == UserType.SUPERUSER.value


@pytest.mark.asyncio
async def test_patch_user_type_invalid_value(
    client, auth_override, superuser_factory
):
    """Unknown user_type value is rejected with 422."""
    su = await superuser_factory("su_invalid@example.com")
    target = await _seed_user(
        "target-invalid", "target_invalid@example.com", UserType.REGULAR
    )
    auth_override(su.id)

    response = await client.patch(
        f"/api/admin/users/{target.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "moderator"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_user_type_machine_rejected(
    client, auth_override, superuser_factory
):
    """`machine` is not a valid promotion target; expect 422."""
    su = await superuser_factory("su_machine@example.com")
    target = await _seed_user(
        "target-machine", "target_machine@example.com", UserType.REGULAR
    )
    auth_override(su.id)

    response = await client.patch(
        f"/api/admin/users/{target.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "machine"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_user_type_user_not_found(
    client, auth_override, superuser_factory
):
    """PATCH on unknown user_id returns 404."""
    su = await superuser_factory("su_404@example.com")
    auth_override(su.id)

    response = await client.patch(
        "/api/admin/users/does-not-exist/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "admin"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_user_type_response_shape(
    client, auth_override, superuser_factory
):
    """Response is the updated user serialized as UserModel (camelCase)."""
    su = await superuser_factory("su_shape_patch@example.com")
    target = await _seed_user(
        "target-shape-patch",
        "target_shape_patch@example.com",
        UserType.REGULAR,
    )
    auth_override(su.id)

    response = await client.patch(
        f"/api/admin/users/{target.id}/user-type",
        headers={"Authorization": "Bearer test-token"},
        json={"user_type": "pro"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == target.id
    assert data["email"] == target.email
    assert data["userType"] == UserType.PRO.value
    assert "createdAt" in data
    assert "updatedAt" in data


@pytest.mark.asyncio
async def test_superuser_can_view_other_users_private_threads(
    client, auth_override, superuser_factory, thread_factory
):
    """Smoke test for superset-of-admin: superusers inherit admin privileges
    (e.g. accessing other users' private threads)."""
    owner_id = "thread-owner-su"
    auth_override(owner_id)
    thread = await thread_factory(owner_id)

    su = await superuser_factory("su_view_thread@example.com")
    auth_override(su.id)

    response = await client.get(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200


# --- GET /api/admin/users/export ------------------------------------------

EXPORT_COLUMNS = [
    "id",
    "name",
    "email",
    "created_at",
    "updated_at",
    "user_type",
    "first_name",
    "last_name",
    "profile_description",
    "sector_code",
    "role_code",
    "job_title",
    "company_organization",
    "country_code",
    "preferred_language_code",
    "gis_expertise_level",
    "areas_of_interest",
    "has_profile",
    "topics",
    "receive_news_emails",
    "help_test_features",
]


@pytest.mark.asyncio
async def test_export_users_requires_auth(client):
    """Unauthenticated requests must return 401."""
    response = await client.get("/api/admin/users/export?format=csv")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_export_users_forbidden_for_regular(client, auth_override):
    """Regular users must receive 403."""
    regular = await _seed_user(
        "regular-export", "regular-export@example.test", UserType.REGULAR
    )
    auth_override(regular.id)

    response = await client.get(
        "/api/admin/users/export?format=csv",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_export_users_forbidden_for_admin(
    client, auth_override, admin_user_factory
):
    """Admin (not superuser) must receive 403."""
    admin = await admin_user_factory("admin-export@example.test")
    auth_override(admin.id)

    response = await client.get(
        "/api/admin/users/export?format=csv",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_export_users_forbidden_for_pro(client, auth_override):
    """Pro users must receive 403."""
    pro = await _seed_user(
        "pro-export", "pro-export@example.test", UserType.PRO
    )
    auth_override(pro.id)

    response = await client.get(
        "/api/admin/users/export?format=csv",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_export_users_rejects_unknown_format(
    client, auth_override, superuser_factory
):
    """An unsupported format query value must return 400."""
    su = await superuser_factory("su-export-badfmt@example.test")
    auth_override(su.id)

    response = await client.get(
        "/api/admin/users/export?format=xml",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_export_users_defaults_to_csv(
    client, auth_override, superuser_factory
):
    """Omitting the format param defaults to csv."""
    su = await superuser_factory("su-export-default@example.test")
    auth_override(su.id)

    response = await client.get(
        "/api/admin/users/export",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")


@pytest.mark.asyncio
async def test_export_users_response_headers(
    client, auth_override, superuser_factory
):
    """Response carries text/csv content-type and attachment disposition
    with a date-stamped filename of the form gnw-users-YYYY-MM-DD.csv."""
    su = await superuser_factory("su-export-headers@example.test")
    auth_override(su.id)

    response = await client.get(
        "/api/admin/users/export?format=csv",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")

    cd = response.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert re.search(r'filename="gnw-users-\d{4}-\d{2}-\d{2}\.csv"', cd), (
        f"Unexpected Content-Disposition: {cd!r}"
    )


@pytest.mark.asyncio
async def test_export_users_header_row(
    client, auth_override, superuser_factory
):
    """First CSV row is the expected 21-column header in exact order."""
    su = await superuser_factory("su-export-header-row@example.test")
    auth_override(su.id)

    response = await client.get(
        "/api/admin/users/export?format=csv",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200

    reader = csv.reader(io.StringIO(response.text))
    rows = list(reader)
    assert rows[0] == EXPORT_COLUMNS


@pytest.mark.asyncio
async def test_export_users_renders_rows_correctly(
    client, auth_override, superuser_factory
):
    """Rows carry the expected formatting:
    - booleans serialize as 'true'/'false'
    - datetimes as ISO-8601 (round-trip via fromisoformat)
    - topics: NULL → empty cell; '[]' → '[]'; JSON array → unchanged
    - rows ordered by created_at DESC, id ASC
    - quoting handles commas in values
    """
    su = await superuser_factory("su-export-rows@example.test")
    auth_override(su.id)

    full_created = datetime(2025, 1, 15, 10, 30, 0)
    full_updated = datetime(2025, 6, 20, 14, 45, 30, 123456)
    minimal_created = datetime(2024, 8, 1, 9, 0, 0)
    comma_created = datetime(2026, 3, 10, 12, 0, 0)

    async with async_session_maker() as session:
        session.add(
            UserOrm(
                id="export-full",
                name="Fictitious Fullprofile",
                email="full-export@example.test",
                created_at=full_created,
                updated_at=full_updated,
                user_type=UserType.REGULAR.value,
                first_name="Fictitious",
                last_name="Fullprofile",
                profile_description="An entirely made-up profile.",
                sector_code="sample_sector",
                role_code="sample_role",
                job_title="Imaginary Title",
                company_organization="Made-Up Org",
                country_code="ZZ",
                preferred_language_code="xx",
                gis_expertise_level="intermediate",
                areas_of_interest="placeholder_interest",
                topics='["topic_alpha", "topic_beta"]',
                receive_news_emails=True,
                help_test_features=True,
                has_profile=True,
            )
        )
        session.add(
            UserOrm(
                id="export-minimal",
                name="Minimal Tester",
                email="minimal-export@example.test",
                created_at=minimal_created,
                updated_at=minimal_created,
                user_type=UserType.REGULAR.value,
                topics=None,
            )
        )
        session.add(
            UserOrm(
                id="export-comma",
                name="Lastname, Firstname",
                email="comma-export@example.test",
                created_at=comma_created,
                updated_at=comma_created,
                user_type=UserType.REGULAR.value,
                topics="[]",
            )
        )
        await session.commit()

    response = await client.get(
        "/api/admin/users/export?format=csv",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200

    reader = csv.reader(io.StringIO(response.text))
    rows = list(reader)
    header, data_rows = rows[0], rows[1:]
    assert header == EXPORT_COLUMNS

    by_id = {row[header.index("id")]: row for row in data_rows}
    assert "export-full" in by_id
    assert "export-minimal" in by_id
    assert "export-comma" in by_id

    seeded_ids = [
        "export-full",
        "export-minimal",
        "export-comma",
        su.id,
    ]
    ordered = [
        row[header.index("id")]
        for row in data_rows
        if row[header.index("id")] in seeded_ids
    ]
    # created_at DESC, id ASC → comma (2026), full (2025-06 via created 2025-01;
    # superuser created at fixture time ~ now), minimal (2024). Superuser is
    # created during this test, so its created_at is the most recent. Verify
    # the three seeded rows are in their expected relative order.
    seeded_order = [
        i
        for i in ordered
        if i in {"export-full", "export-minimal", "export-comma"}
    ]
    assert seeded_order == ["export-comma", "export-full", "export-minimal"]

    full_row = by_id["export-full"]

    def cell(name):
        return full_row[header.index(name)]

    assert cell("name") == "Fictitious Fullprofile"
    assert cell("email") == "full-export@example.test"
    assert cell("user_type") == UserType.REGULAR.value
    assert cell("first_name") == "Fictitious"
    assert cell("last_name") == "Fullprofile"
    assert cell("profile_description") == "An entirely made-up profile."
    assert cell("sector_code") == "sample_sector"
    assert cell("role_code") == "sample_role"
    assert cell("job_title") == "Imaginary Title"
    assert cell("company_organization") == "Made-Up Org"
    assert cell("country_code") == "ZZ"
    assert cell("preferred_language_code") == "xx"
    assert cell("gis_expertise_level") == "intermediate"
    assert cell("areas_of_interest") == "placeholder_interest"
    assert cell("has_profile") == "true"
    assert cell("receive_news_emails") == "true"
    assert cell("help_test_features") == "true"

    assert datetime.fromisoformat(cell("created_at")) == full_created
    assert datetime.fromisoformat(cell("updated_at")) == full_updated
    assert json.loads(cell("topics")) == ["topic_alpha", "topic_beta"]

    minimal_row = by_id["export-minimal"]

    def m(name):
        return minimal_row[header.index(name)]

    assert m("first_name") == ""
    assert m("last_name") == ""
    assert m("profile_description") == ""
    assert m("sector_code") == ""
    assert m("topics") == ""
    assert m("has_profile") == "false"
    assert m("receive_news_emails") == "false"
    assert m("help_test_features") == "false"

    comma_row = by_id["export-comma"]
    assert comma_row[header.index("name")] == "Lastname, Firstname"
    assert comma_row[header.index("topics")] == "[]"
