from datetime import date

import numpy as np

from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data
from app.services.portfolio_build_extras import max_drawdown


def test_max_drawdown_constant_weights():
    returns = np.array([[0.10], [-0.20], [0.05]])
    value = max_drawdown(returns, np.array([1.0]))
    assert abs(value - (-0.20)) < 1e-9
    assert abs(max_drawdown(returns, np.array([0.5])) - (-0.10)) < 1e-9
    assert max_drawdown(np.empty((0, 1)), np.array([1.0])) is None


def _auth(client, email):
    r = client.post("/auth/signup", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_build_extras_requires_ownership_and_returns_sectors(client):
    with SessionLocal() as db:
        generate_mock_market_data(db, days=30, end_date=date(2026, 8, 7))
    owner = _auth(client, "build-owner@example.com")
    other = _auth(client, "build-other@example.com")
    pid = client.post("/portfolios", headers=owner, json={"name": "Build"}).json()["id"]
    assert client.post(f"/portfolios/{pid}/build-extras", headers=other, json={}).status_code == 404
    response = client.post(f"/portfolios/{pid}/build-extras", headers=owner, json={"target_weights": {"CASH": 1.0}})
    assert response.status_code == 200
    body = response.json()
    assert body["sector_weights"]["proposed"] == {"Cash": 1.0}
    assert "max_drawdown" in body
