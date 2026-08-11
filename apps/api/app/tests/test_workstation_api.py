from datetime import date

import pytest

from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data
from app.services import workstation_service


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


def test_aligned_market_inputs_are_reused_across_analytics_endpoints(client, monkeypatch):
    headers = signup(client, "aligned-cache@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    workstation_service._aligned_price_cache.clear()
    original = workstation_service.price_series
    calls = 0

    def counted_price_series(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(workstation_service, "price_series", counted_price_series)
    quant = client.get(f"/portfolios/{portfolio_id}/quant", headers=headers)
    assert quant.status_code == 200, quant.text
    first_request_calls = calls
    assert first_request_calls == 2

    frontier = client.get(f"/portfolios/{portfolio_id}/frontier?points=8", headers=headers)
    assert frontier.status_code == 200, frontier.text
    assert calls == first_request_calls


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


def test_profile_reconciles_capacity_and_willingness_conservatively(client):
    headers = signup(client, "profile-reconciliation@example.com")
    response = client.post(
        "/profiles/financial/confirm",
        headers=headers,
        json={"data": {
            "risk_capacity": "high",
            "willingness_answers": [1, 2, 2],
            "confirmed_overall_risk_tolerance": "low",
            "horizon_years": 12,
        }},
    )
    assert response.status_code == 201
    assessment = response.json()["data"]["risk_assessment"]
    assert assessment["capacity"] == "high"
    assert assessment["willingness"] == "low"
    assert assessment["reconciled_tolerance"] == "low"
    assert assessment["confirmed_tolerance"] == "low"


def test_chart_ready_analytics_comparison_and_risk_budget_are_owned(client):
    headers = signup(client, "decision-analytics@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    ips = client.post(
        f"/portfolios/{portfolio_id}/ips/confirm",
        headers=headers,
        json={"constraints": {"max_instrument_weight": 0.8, "min_cash_weight": 0.0}},
    )
    assert ips.status_code == 201

    assumptions = client.get(f"/portfolios/{portfolio_id}/assumptions", headers=headers)
    assert assumptions.status_code == 200, assumptions.text
    assert assumptions.json()["estimator"]["expected_return_method"] == "historical_shrunk"
    assert len(assumptions.json()["securities"]) == 2

    frontier = client.get(f"/portfolios/{portfolio_id}/frontier?points=8", headers=headers)
    assert frontier.status_code == 200, frontier.text
    assert frontier.json()["markers"]["current"]
    assert frontier.json()["markers"]["global_minimum_variance"]

    risk_budget = client.get(f"/portfolios/{portfolio_id}/risk-budget", headers=headers)
    assert risk_budget.status_code == 200, risk_budget.text
    assert sum(item["percentage_risk"] for item in risk_budget.json()["items"]) == pytest.approx(1)

    summary = client.get(f"/portfolios/{portfolio_id}/summary", headers=headers).json()
    total = float(summary["total_value"])
    weights = {item["symbol"]: float(item["market_value"]) / total for item in summary["holdings"]}
    weights["CASH"] = float(summary["cash_balance"]) / total
    comparison = client.post(
        f"/portfolios/{portfolio_id}/comparison",
        headers=headers,
        json={"target_weights": weights, "label": "No-change proposal"},
    )
    assert comparison.status_code == 200, comparison.text
    assert all(abs(item["delta"] or 0) < 1e-8 for item in comparison.json()["metrics"])
    assert comparison.json()["current_weights"] == pytest.approx(comparison.json()["proposed_weights"])

    other = signup(client, "decision-analytics-other@example.com")
    assert client.get(f"/portfolios/{portfolio_id}/assumptions", headers=other).status_code == 404


def test_scenario_returns_stressed_value_sector_contribution_and_compliance(client):
    headers = signup(client, "scenario-impact@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    client.post(
        f"/portfolios/{portfolio_id}/ips/confirm",
        headers=headers,
        json={"constraints": {"max_instrument_weight": 0.8}},
    )
    response = client.post(
        f"/portfolios/{portfolio_id}/scenario-runs",
        headers=headers,
        json={"name": "Combined stress", "scenario_type": "hypothetical", "shocks": {"MEBL": -0.1}, "sector_shocks": {"Technology & Communication": -0.2}},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["stressed_portfolio_value"] == pytest.approx(body["portfolio_value"] + body["pnl"])
    assert sum(body["sector_contributions"].values()) == pytest.approx(body["pnl"])
    assert "violations" in body["compliance"]
    history = client.get(f"/portfolios/{portfolio_id}/scenario-runs", headers=headers)
    assert history.status_code == 200
    assert history.json()[0]["positions"] == body["positions"]
    assert "result" not in history.json()[0]
