from datetime import date

import pytest

from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data


def signup(client, email="workstation@example.com"):
    token = client.post("/auth/signup", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def seeded_portfolio(client, headers):
    with SessionLocal() as db:
        generate_mock_market_data(db, days=90, end_date=date(2026, 8, 7))
    portfolio_id = client.post("/portfolios", headers=headers, json={"name": "Quant"}).json()["id"]
    for symbol, quantity in [("MEBL", "10"), ("SYS", "5")]:
        response = client.post(f"/portfolios/{portfolio_id}/holdings", headers=headers, json={"symbol": symbol, "quantity": quantity, "average_cost": "100"})
        assert response.status_code == 201
    return portfolio_id


def test_profile_ips_minimum_variance_and_scenario_are_owned_and_auditable(client):
    headers = signup(client)
    portfolio_id = seeded_portfolio(client, headers)
    profile = client.post("/profiles/financial/confirm", headers=headers, json={"data": {"liquid_assets": 1000000, "risk_willingness": "moderate"}})
    assert profile.status_code == 201
    assert profile.json()["status"] == "confirmed"
    ips = client.post(f"/portfolios/{portfolio_id}/ips/confirm", headers=headers, json={"constraints": {"long_only": True, "max_instrument_weight": 0.70}, "starting_capital": 1000000, "target_value": 1500000, "horizon_years": 5})
    assert ips.status_code == 201
    assert 0 < ips.json()["required_return"] < 1
    optimizer = client.post(f"/portfolios/{portfolio_id}/optimizer-runs", headers=headers, json={"objective": "minimum_variance", "maximum_weight": 0.70})
    assert optimizer.status_code == 201, optimizer.text
    body = optimizer.json()
    assert body["expected_return_method"] is None
    assert abs(sum(body["weights"].values()) - 1) < 1e-6
    scenario = client.post(f"/portfolios/{portfolio_id}/scenario-runs", headers=headers, json={"name": "Equity selloff", "shocks": {"MEBL": -0.10, "SYS": -0.15}})
    assert scenario.status_code == 201
    assert scenario.json()["pnl"] < 0


def test_return_targeted_optimizer_requires_explicit_methodology(client):
    headers = signup(client, "method@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    response = client.post(f"/portfolios/{portfolio_id}/optimizer-runs", headers=headers, json={"objective": "target_return_minimum_variance", "target_return": 0.1})
    assert response.status_code == 422


def test_optimizer_compiles_ips_cash_as_explicit_asset(client):
    headers = signup(client, "cash-optimizer@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    ips = client.post(
        f"/portfolios/{portfolio_id}/ips/confirm",
        headers=headers,
        json={"constraints": {"min_cash_weight": 0.10, "max_instrument_weight": 0.70}},
    )
    assert ips.status_code == 201
    response = client.post(
        f"/portfolios/{portfolio_id}/optimizer-runs",
        headers=headers,
        json={"objective": "minimum_variance", "maximum_weight": 0.70},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "CASH" in body["symbols"]
    assert body["weights"]["CASH"] >= 0.10 - 1e-6
    assert sum(body["weights"].values()) == pytest.approx(1)


def test_ips_required_return_supports_dated_and_real_cash_flows(client):
    headers = signup(client, "dated-ips@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    response = client.post(
        f"/portfolios/{portfolio_id}/ips/confirm",
        headers=headers,
        json={
            "starting_capital": 100000,
            "target_value": 160000,
            "valuation_date": "2026-01-01",
            "target_date": "2029-01-01",
            "dated_contributions": [{"contribution_date": "2027-01-01", "amount": 10000}],
            "target_value_is_real": True,
            "inflation_rate": 0.05,
            "risk_capacity": "moderate",
            "risk_willingness": "low",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["required_return"] is not None
    assert body["constraints"]["required_return_method"]["method"] == "dated_cash_flow_future_value_bisection"


def test_workstation_routes_enforce_portfolio_ownership(client):
    owner = signup(client, "owner-workstation@example.com")
    other = signup(client, "other-workstation@example.com")
    portfolio_id = seeded_portfolio(client, owner)
    response = client.post(f"/portfolios/{portfolio_id}/scenario-runs", headers=other, json={"name": "No access", "shocks": {"MEBL": -0.1}})
    assert response.status_code == 404
