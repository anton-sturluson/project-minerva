"""Verify the trust boundary between Serve and the loopback app."""

import pytest
from fastapi.testclient import TestClient

from investor_platform.app import create_app

ORIGIN = "https://test.tail123.ts.net:8444"
LOGIN = "investor@example.com"


@pytest.fixture
def remote_env(monkeypatch, tmp_path):
    monkeypatch.setenv("INVESTOR_MODE", "tailscale")
    monkeypatch.setenv("TAILSCALE_ORIGIN", ORIGIN)
    monkeypatch.setenv("TAILSCALE_USER_LOGIN", LOGIN)
    (tmp_path / "index.html").write_text("<h1>Private portfolio</h1>")
    (tmp_path / "asset.js").write_text("// private application asset")
    return tmp_path


def remote_client(remote_env, peer="127.0.0.1"):
    return TestClient(create_app(web_dist=remote_env), base_url=ORIGIN, client=(peer, 12345))


@pytest.mark.parametrize("path", ["/", "/asset.js", "/api/health", "/api/account", "/docs"])
@pytest.mark.parametrize("login", [None, "someone-else@example.com"])
def test_missing_or_foreign_identity_cannot_read_any_surface(remote_env, path, login):
    with remote_client(remote_env) as client:
        headers = {"Tailscale-User-Login": login} if login else {}
        response = client.get(path, headers=headers)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"


def test_allowed_identity_serves_ui_and_api(remote_env):
    with remote_client(remote_env) as client:
        client.headers["Tailscale-User-Login"] = LOGIN
        assert "Private portfolio" in client.get("/").text
        assert client.get("/asset.js").status_code == 200
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.post("/api/account", json={}).status_code == 403
        # Reaches payload validation, without creating any database record.
        assert client.post("/api/account", headers={"Origin": ORIGIN}, json={}).status_code == 422


def test_non_loopback_peer_cannot_spoof_identity(remote_env):
    with remote_client(remote_env, peer="100.64.0.2") as client:
        assert client.get("/", headers={"Tailscale-User-Login": LOGIN}).status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "127.0.0.1"},
        {"Host": "test.tail123.ts.net"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "http://127.0.0.1:5173"},
    ],
)
def test_identity_does_not_bypass_host_or_origin(remote_env, headers):
    with remote_client(remote_env) as client:
        assert (
            client.get("/", headers={"Tailscale-User-Login": LOGIN, **headers}).status_code == 403
        )


def test_duplicate_identity_is_rejected(remote_env):
    with remote_client(remote_env) as client:
        response = client.get(
            "/", headers=[("Tailscale-User-Login", LOGIN), ("Tailscale-User-Login", LOGIN)]
        )
        assert response.status_code == 403


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("TAILSCALE_USER_LOGIN", ""),
        ("TAILSCALE_ORIGIN", ""),
        ("TAILSCALE_ORIGIN", "https://test.tail123.ts.net:443"),
        ("TAILSCALE_ORIGIN", "http://test.tail123.ts.net:8444"),
        ("TAILSCALE_ORIGIN", ORIGIN + "/"),
        ("INVESTOR_MODE", "server"),
    ],
)
def test_invalid_configuration_fails_closed(remote_env, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        create_app(web_dist=remote_env)


def test_missing_build_refuses_startup(remote_env):
    (remote_env / "index.html").unlink()
    with pytest.raises(RuntimeError, match="Build the frontend"):
        create_app(web_dist=remote_env)
