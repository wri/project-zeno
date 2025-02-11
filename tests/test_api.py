from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_read_main():
    response = client.post(
        "/stream/dist_alert",
        json=dict(query="Hi Zeno", thread_id="1", query_type="human_input"),
    )
    assert response.status_code == 200
    assert "Hello" in response.json()["content"]
