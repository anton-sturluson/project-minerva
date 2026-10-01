import pytest
from fastapi.testclient import TestClient

from investor_platform.app import app


@pytest.fixture
def client():
    with TestClient(app, base_url="http://127.0.0.1:8010") as client:
        yield client


def test_health_is_identifiable_and_not_cached(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "investor-platform"}
    assert response.headers["cache-control"] == "no-store"


def test_local_frontend_is_allowed(client):
    assert client.get("/api/health", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200


@pytest.mark.parametrize("origin", ["https://example.com", "null", "http://localhost:9999"])
def test_untrusted_origin_is_rejected(client, origin):
    assert client.get("/api/health", headers={"Origin": origin}).status_code == 403


def test_untrusted_host_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "example.com"}).status_code == 400
