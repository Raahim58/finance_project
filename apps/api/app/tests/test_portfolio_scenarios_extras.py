import pytest

from app.tests.test_workstation_api import seeded_portfolio, signup


def test_scenario_run_extras_report_timestamp_shocks_and_volatility(client):
    headers = signup(client, "scenario-extras@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    run = client.post(f"/portfolios/{portfolio_id}/scenario-runs", headers=headers, json={"name": "Tech", "scenario_type": "hypothetical", "shocks": {"MEBL": -0.1}, "sector_shocks": {"Technology & Communication": -0.2}})
    assert run.status_code == 201, run.text
    response = client.get(f"/portfolios/{portfolio_id}/scenario-run-extras", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["volatility_method"]
    extra = body["runs"][0]
    assert extra["id"] == run.json()["id"]
    assert extra["created_at"] and extra["scenario_type"] == "hypothetical"
    assert extra["shocks"]["instruments"] == {"MEBL": -0.1}
    assert extra["shocks"]["sectors"] == {"Technology & Communication": -0.2}
    assert extra["volatility_before"] > 0
    assert extra["volatility_change"] == pytest.approx(extra["volatility_after"] - extra["volatility_before"])


def test_scenario_run_extras_enforce_ownership(client):
    headers = signup(client, "scenario-extras-owner@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    other = signup(client, "scenario-extras-other@example.com")
    assert client.get(f"/portfolios/{portfolio_id}/scenario-run-extras", headers=other).status_code == 404
    assert client.get(f"/portfolios/{portfolio_id}/scenario-run-extras").status_code in {401, 403}
