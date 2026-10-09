"""Authentication fixture builder shared by API and assistant tests."""


def signup_user(client, email: str) -> dict[str, str]:
    response = client.post("/auth/signup", json={"email": email, "password": "password123"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
