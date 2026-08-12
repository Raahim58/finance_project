from datetime import date

import pytest

from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.models.workstation import Instrument
from app.services.market_ingestion import generate_mock_market_data
from app.services import workstation_service
from app.services import decision_analytics_service


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
    assert body["weights"]["CASH"] <= 0.20 + 1e-6
    assert sum(body["weights"].values()) == pytest.approx(1)
    assert body["assumptions"]["cash"] == {
        "instrument": "operational_cash",
        "annual_return": 0.0,
        "basis": "nominal",
        "effective_date": "2026-08-07",
        "minimum_weight": 0.1,
        "maximum_weight": 0.2,
        "maximum_source": "product_default",
    }


def test_risk_parity_optimizes_risky_sleeve_and_attaches_confirmed_cash(client):
    headers = signup(client, "risk-parity-cash@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    client.post(f"/portfolios/{portfolio_id}/ips/confirm", headers=headers, json={"constraints": {"min_cash_weight": 0.15, "max_cash_weight": 0.25, "max_instrument_weight": 0.8}})
    response = client.post(f"/portfolios/{portfolio_id}/optimizer-runs", headers=headers, json={"objective": "risk_parity"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "optimal"
    assert body["weights"]["CASH"] == pytest.approx(0.15)
    assert sum(body["weights"].values()) == pytest.approx(1)
    assert body["diagnostics"]["portfolio_basis"] == "risky_sleeve"


def test_individual_performance_benchmark_cannot_become_capm_market_proxy(client):
    headers = signup(client, "capm-proxy@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    client.post(f"/portfolios/{portfolio_id}/ips/confirm", headers=headers, json={"performance_benchmark_symbol": "HBL", "constraints": {"max_instrument_weight": 0.8}})
    sml = client.get(f"/portfolios/{portfolio_id}/capm-sml", headers=headers)
    assert sml.status_code == 200
    assert sml.json()["available"] is False
    assert sml.json()["performance_benchmark_symbol"] == "HBL"
    assert sml.json()["capm_market_proxy_symbol"] is None
    assert "No CAPM market proxy" in " ".join(sml.json()["diagnostics"])
    optimizer = client.post(f"/portfolios/{portfolio_id}/optimizer-runs", headers=headers, json={"objective": "max_sharpe", "expected_return_method": "capm", "benchmark_symbol": "HBL"})
    assert optimizer.status_code == 422
    assert optimizer.json()["detail"]["code"] in {"invalid_capm_proxy_override", "capm_market_proxy_unavailable"}


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
    assert frontier.json()["unit"] == "decimal"
    assert frontier.json()["portfolio_basis"] == "risky_sleeve"
    assert frontier.json()["feasible_set_label"] == "Unconstrained risky-sleeve comparison"
    assert all(abs(point["expected_return"]) < 5 and 0 <= point["volatility"] < 5 for point in frontier.json()["points"])

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
    assert all(item["classification"] in {"UNCHANGED", "REFERENCE", "NOT_EVALUATED"} for item in comparison.json()["metrics"])
    assert not any(item["direction"] == "WORSENED" for item in comparison.json()["trade_offs"])
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


def test_risk_budget_reconciles_total_capital_and_risky_sleeve_when_only_cash_changes(client):
    headers = signup(client, "risk-basis@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    before = client.get(f"/portfolios/{portfolio_id}/risk-budget", headers=headers).json()
    assert before["portfolio_basis"] == "total_capital"
    assert sum(row["total_capital_weight"] for row in before["items"]) == pytest.approx(1)
    risky_before = {row["symbol"]: row for row in before["items"] if row["symbol"] != "CASH"}
    assert sum(row["risky_sleeve_weight"] for row in risky_before.values()) == pytest.approx(1)

    deposit = client.post(f"/portfolios/{portfolio_id}/transactions", headers=headers, json={"transaction_type": "deposit", "amount": "5000", "transaction_date": "2026-08-07"})
    assert deposit.status_code == 201
    after = client.get(f"/portfolios/{portfolio_id}/risk-budget", headers=headers).json()
    risky_after = {row["symbol"]: row for row in after["items"] if row["symbol"] != "CASH"}
    assert sum(row["total_capital_weight"] for row in after["items"]) == pytest.approx(1)
    assert sum(row["risky_sleeve_weight"] for row in risky_after.values()) == pytest.approx(1)
    for symbol in risky_before:
        assert risky_after[symbol]["risky_sleeve_weight"] == pytest.approx(risky_before[symbol]["risky_sleeve_weight"])
        assert risky_after[symbol]["percentage_risk"] == pytest.approx(risky_before[symbol]["percentage_risk"])


def test_weight_sum_error_reports_submitted_sum_residual_and_shared_tolerance(client):
    headers = signup(client, "weight-contract@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    response = client.post(f"/portfolios/{portfolio_id}/comparison", headers=headers, json={"target_weights": {"MEBL": 0.3333, "SYS": 0.3333, "CASH": 0.3333}})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_weight_sum"
    assert detail["submitted_sum"] == pytest.approx(0.9999)
    assert detail["residual"] == pytest.approx(0.0001)
    assert detail["tolerance"] == pytest.approx(1e-6)


def test_rolling_sharpe_uses_effective_risk_free_and_beta_uses_aligned_benchmark(client, monkeypatch):
    headers = signup(client, "rolling-contract@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    client.post(f"/portfolios/{portfolio_id}/ips/confirm", headers=headers, json={"performance_benchmark_symbol": "HBL", "constraints": {"max_instrument_weight": 0.8}})

    def risk_free(rate):
        return {"series_key": "test.rf", "annual_rate": rate, "effective_date": "2026-08-07", "source": "golden_fixture", "nominal_real_basis": "nominal"}

    monkeypatch.setattr(decision_analytics_service, "_effective_risk_free_rate", lambda *_args, **_kwargs: risk_free(0.0))
    zero_rf = client.get(f"/portfolios/{portfolio_id}/rolling-risk?window=30", headers=headers)
    assert zero_rf.status_code == 200, zero_rf.text
    monkeypatch.setattr(decision_analytics_service, "_effective_risk_free_rate", lambda *_args, **_kwargs: risk_free(0.10))
    positive_rf = client.get(f"/portfolios/{portfolio_id}/rolling-risk?window=30", headers=headers)
    assert positive_rf.status_code == 200, positive_rf.text

    first_zero = zero_rf.json()["points"][0]
    first_positive = positive_rf.json()["points"][0]
    assert first_zero["beta"] is not None
    assert first_positive["beta"] == pytest.approx(first_zero["beta"])
    assert first_positive["sharpe"] == pytest.approx(first_zero["sharpe"] - 0.10 / first_zero["volatility"])
    assert positive_rf.json()["return_basis"] == "modeled_current_allocation"
    assert positive_rf.json()["benchmark_symbol"] == "HBL"


def test_sml_contract_uses_decimal_scale_and_reconciles_to_capm_formula(client, monkeypatch):
    headers = signup(client, "sml-golden@example.com")
    portfolio_id = seeded_portfolio(client, headers)
    with SessionLocal() as db:
        db.add(Instrument(symbol="KSE100TR", name="KSE-100 Total Return Test Index", instrument_type="total_return_index", currency="PKR", country="PK", metadata_json='{"broad_market_proxy":true,"return_basis":"total_return","data_classification":"golden_fixture"}'))
        source_rows = db.query(MarketPrice).filter(MarketPrice.symbol == "HBL").order_by(MarketPrice.trade_date).all()
        for row in source_rows:
            db.add(MarketPrice(company_id=row.company_id, symbol="KSE100TR", trade_date=row.trade_date, open=row.open, high=row.high, low=row.low, close=row.close, previous_close=row.previous_close, change=row.change, change_percent=row.change_percent, volume=row.volume, value=row.value, market_cap=row.market_cap, source="golden_fixture"))
        db.commit()
    client.post(f"/portfolios/{portfolio_id}/ips/confirm", headers=headers, json={"performance_benchmark_symbol": "HBL", "capm_market_proxy_symbol": "KSE100TR", "constraints": {"max_instrument_weight": 0.8}})
    fixture_rf = {"series_key": "test.rf", "annual_rate": 0.08, "effective_date": "2026-08-07", "source": "golden_fixture", "nominal_real_basis": "nominal"}
    monkeypatch.setattr(decision_analytics_service, "_effective_risk_free_rate", lambda *_args, **_kwargs: fixture_rf)
    response = client.get(f"/portfolios/{portfolio_id}/capm-sml", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is True
    assert body["performance_benchmark_symbol"] == "HBL"
    assert body["capm_market_proxy_symbol"] == "KSE100TR"
    assert body["market_risk_premium"] == pytest.approx(body["market_return"] - body["risk_free_rate"])
    for point in body["sml"]:
        assert point["expected_return"] == pytest.approx(body["risk_free_rate"] + point["beta"] * body["market_risk_premium"])
        assert abs(point["expected_return"]) < 5  # decimal annual return, never percentage-point scale
