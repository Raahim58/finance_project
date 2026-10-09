"""Offline portfolios contracts and fixtures."""

from datetime import date
from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data
from app.tests.support.users import signup_user


def signup(client, email="workstation@example.com"):
    return signup_user(client, email)


def seeded_portfolio(client, headers):
    with SessionLocal() as db:
        generate_mock_market_data(db, days=90, end_date=date(2026, 8, 7))
    portfolio_id = client.post("/portfolios", headers=headers, json={"name": "Quant"}).json()["id"]
    for symbol, quantity in [("MEBL", "10"), ("SYS", "5")]:
        response = client.post(
            f"/portfolios/{portfolio_id}/holdings",
            headers=headers,
            json={"symbol": symbol, "quantity": quantity, "average_cost": "100"},
        )
        assert response.status_code == 201
    return portfolio_id
