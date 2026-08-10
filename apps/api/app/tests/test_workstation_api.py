from datetime import date

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


def test_workstation_routes_enforce_portfolio_ownership(client):
    owner = signup(client, "owner-workstation@example.com")
    other = signup(client, "other-workstation@example.com")
    portfolio_id = seeded_portfolio(client, owner)
    response = client.post(f"/portfolios/{portfolio_id}/scenario-runs", headers=other, json={"name": "No access", "shocks": {"MEBL": -0.1}})
    assert response.status_code == 404
