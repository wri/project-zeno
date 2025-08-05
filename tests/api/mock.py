# Mock user responses for different scenarios
USERS = [
    {
        "id": "test-user-1",
        "name": "Test User",
        "email": "test@developmentseed.org",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
    },
    {
        "id": "test-user-2",
        "name": "WRI User",
        "email": "test@wri.org",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
    },
    {
        "id": "test-user-3",
        "name": "Unauthorized User",
        "email": "test@unauthorized.com",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
    }
]


def mock_rw_api_response(username):
    """Helper to create a mock response object."""

    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code
            self.text = str(json_data)

        def json(self):
            return self.json_data

    try:
        user = [u for u in USERS if u["name"] == username][0]
    except IndexError:
        user = USERS[2]

    return MockResponse(user, 200)
