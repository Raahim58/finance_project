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
