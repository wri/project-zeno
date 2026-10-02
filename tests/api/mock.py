# Mock user responses for different scenarios. RW's /auth/user/me carries
# the apps the account is registered with under extraUserData.apps (GFW's
# sign-up writes ["gfw"]); the live shape is unconfirmed, so one user has
# no extraUserData at all.
USERS = [
    {
        "id": "test-user-1",
        "name": "Test User",
        "email": "test@developmentseed.org",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
        "extraUserData": {"apps": ["gfw"]},
    },
    {
        "id": "test-user-2",
        "name": "WRI User",
        "email": "test@wri.org",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
        "extraUserData": {"apps": ["gnw"]},
    },
    {
        "id": "test-user-3",
        "name": "Unauthorized User",
        "email": "test@unauthorized.com",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
    },
]


class MockResponse:
    """A minimal stand-in for an httpx response from Resource Watch."""

    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code
        self.text = str(json_data)

    def json(self):
        return self.json_data


def mock_rw_api_response(username):
    """Helper to create a mock response object."""
    try:
        user = [u for u in USERS if u["name"] == username][0]
    except IndexError:
        user = USERS[2]

    return MockResponse(user, 200)


def mock_rw_me_response(user_id, extra_user_data=None):
    """RW ``GET /auth/user/me`` for a fresh account (a new dict each call).

    ``extra_user_data`` becomes ``extraUserData``; None leaves the key out.
    """
    user = {
        "id": user_id,
        "name": f"RW {user_id}",
        "email": f"{user_id}@example.org",
        "createdAt": "2019-05-01T10:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
    }
    if extra_user_data is not None:
        user["extraUserData"] = extra_user_data
    return MockResponse(user)


def mock_rw_profile_response(user_id, attributes, status_code=200):
    """RW ``GET /v2/user/{id}``: the JSON:API body the gfw frontend reads."""
    return MockResponse(
        {"data": {"id": user_id, "type": "user", "attributes": attributes}},
        status_code,
    )
