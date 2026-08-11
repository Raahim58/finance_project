from app.core.config import settings


def test_signup_login_and_me(client):
    signup = client.post(
        "/auth/signup",
        json={"email": "user@example.com", "password": "password123", "full_name": "Test User"},
    )
    assert signup.status_code == 201
    token = signup.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"
    assert me.json()["full_name"] == "Test User"

    login = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_duplicate_signup_is_rejected(client):
    payload = {"email": "user@example.com", "password": "password123"}
    assert client.post("/auth/signup", json=payload).status_code == 201
    duplicate = client.post("/auth/signup", json=payload)
    assert duplicate.status_code == 409


def test_demo_login_is_disabled_by_default(client):
    response = client.get("/auth/demo-login", params={"token": "demo-secret"})
    assert response.status_code == 404


def test_demo_login_requires_matching_token_and_active_demo_user(client, monkeypatch):
    signup = client.post(
        "/auth/signup",
        json={"email": "portfolio.manager@example.com", "password": "password123"},
    )
    assert signup.status_code == 201
    monkeypatch.setattr(settings, "enable_demo_access", True)
    monkeypatch.setattr(settings, "demo_access_token", "a-long-test-demo-token")

    assert client.get("/auth/demo-login", params={"token": "wrong"}).status_code == 403
    response = client.get(
        "/auth/demo-login",
        params={"token": "a-long-test-demo-token"},
    )
    assert response.status_code == 200
    jwt = response.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {jwt}"})
    assert me.status_code == 200
    assert me.json()["email"] == "portfolio.manager@example.com"
