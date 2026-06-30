from datetime import date
from decimal import Decimal

from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data


def _signup(client, email: str) -> dict[str, str]:
    response = client.post(
        "/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed_market_data() -> None:
    with SessionLocal() as db:
        generate_mock_market_data(db, days=5, end_date=date(2026, 6, 30))


def test_portfolio_crud_summary_exposure_and_risk_flags(client):
    _seed_market_data()
    headers = _signup(client, "portfolio@example.com")

    created = client.post(
        "/portfolios",
        headers=headers,
        json={"name": "Long Term", "base_currency": "PKR"},
    )
    assert created.status_code == 201
    portfolio_id = created.json()["id"]
    assert created.json()["source_mode"] == "manual"
    assert created.json()["provider_name"] == "ManualPortfolioProvider"

    holding = client.post(
        f"/portfolios/{portfolio_id}/holdings",
        headers=headers,
        json={"symbol": "MEBL", "quantity": "10", "average_cost": "200"},
    )
    assert holding.status_code == 201
    holding_id = holding.json()["id"]

    patched_holding = client.patch(
        f"/portfolios/holdings/{holding_id}",
        headers=headers,
        json={"quantity": "12", "average_cost": "210"},
    )
    assert patched_holding.status_code == 200
    assert patched_holding.json()["quantity"] == "12.000000"

    client.post(
        f"/portfolios/{portfolio_id}/holdings",
        headers=headers,
        json={"symbol": "SYS", "quantity": "2", "average_cost": "800"},
    )

    transaction = client.post(
        f"/portfolios/{portfolio_id}/transactions",
        headers=headers,
        json={
            "symbol": "MEBL",
            "transaction_type": "buy",
            "quantity": "12",
            "price": "210",
            "amount": "2520",
            "transaction_date": "2026-06-30",
            "notes": "Initial entry",
        },
    )
    assert transaction.status_code == 201
    transaction_id = transaction.json()["id"]

    transactions = client.get(f"/portfolios/{portfolio_id}/transactions", headers=headers)
    assert transactions.status_code == 200
    assert len(transactions.json()) == 1

    patched_transaction = client.patch(
        f"/portfolios/transactions/{transaction_id}",
        headers=headers,
        json={"notes": "Updated"},
    )
    assert patched_transaction.status_code == 200
    assert patched_transaction.json()["notes"] == "Updated"

    summary = client.get(f"/portfolios/{portfolio_id}/summary", headers=headers)
    assert summary.status_code == 200
    summary_body = summary.json()
    assert Decimal(summary_body["total_value"]) > Decimal("0")
    assert Decimal(summary_body["cost_basis"]) == Decimal("4120.0000")
    assert summary_body["data_freshness_date"] == "2026-06-30"
    assert {holding["symbol"] for holding in summary_body["holdings"]} == {"MEBL", "SYS"}

    exposure = client.get(f"/portfolios/{portfolio_id}/exposure", headers=headers)
    assert exposure.status_code == 200
    exposure_body = exposure.json()
    assert Decimal(exposure_body["total_value"]) == Decimal(summary_body["total_value"])
    assert exposure_body["by_sector"]
    assert exposure_body["by_company"]

    performance = client.get(f"/portfolios/{portfolio_id}/performance?limit=3", headers=headers)
    assert performance.status_code == 200
    assert len(performance.json()) == 3

    risk_flags = client.get(f"/portfolios/{portfolio_id}/risk-flags", headers=headers)
    assert risk_flags.status_code == 200
    assert isinstance(risk_flags.json()["flags"], list)

    deleted_transaction = client.delete(f"/portfolios/transactions/{transaction_id}", headers=headers)
    assert deleted_transaction.status_code == 204

    deleted_holding = client.delete(f"/portfolios/holdings/{holding_id}", headers=headers)
    assert deleted_holding.status_code == 204


def test_portfolio_routes_enforce_user_isolation(client):
    _seed_market_data()
    owner_headers = _signup(client, "owner@example.com")
    other_headers = _signup(client, "other@example.com")

    created = client.post("/portfolios", headers=owner_headers, json={"name": "Owner"})
    portfolio_id = created.json()["id"]

    other_get = client.get(f"/portfolios/{portfolio_id}", headers=other_headers)
    assert other_get.status_code == 404

    other_add = client.post(
        f"/portfolios/{portfolio_id}/holdings",
        headers=other_headers,
        json={"symbol": "MEBL", "quantity": "1", "average_cost": "1"},
    )
    assert other_add.status_code == 404
