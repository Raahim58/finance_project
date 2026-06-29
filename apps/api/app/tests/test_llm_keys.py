from sqlalchemy import select

from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.models.llm_key import LLMApiKey


def _auth_headers(client):
    response = client.post(
        "/auth/signup",
        json={"email": "keys@example.com", "password": "password123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_llm_key_is_encrypted_and_masked(client):
    headers = _auth_headers(client)
    response = client.post(
        "/settings/llm-keys",
        headers=headers,
        json={"provider": "mock", "api_key": "mock-secret-1234"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["masked_api_key"] == "mock-s...1234"
    assert "encrypted_api_key" not in body

    list_response = client.get("/settings/llm-keys", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()[0]["masked_api_key"] == "mock-s...1234"

    with SessionLocal() as db:
        stored = db.scalar(select(LLMApiKey))
        assert stored is not None
        assert stored.encrypted_api_key != "mock-secret-1234"
        assert decrypt_secret(stored.encrypted_api_key) == "mock-secret-1234"


def test_key_validation_rejects_bad_mock_key(client):
    response = client.post(
        "/settings/llm-keys/test",
        json={"provider": "mock", "api_key": "not-valid"},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False
