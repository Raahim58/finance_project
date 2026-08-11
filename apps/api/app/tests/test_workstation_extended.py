from datetime import date
from decimal import Decimal

import pytest

from app.db.session import SessionLocal
from app.models.user import User
from app.models.portfolio import Portfolio, PortfolioTransaction
from app.models.workstation import AllocationSet, InvestorFinancialProfileVersion, MonitoringRun, OptimizerRun, PortfolioIPSVersion, Recommendation, ScenarioRun
from app.seed.demo import seed_workstation
from app.services.market_ingestion import generate_mock_market_data
from app.tools import build_tool_registry


def auth(client, email="extended@example.com"):
    token = client.post("/auth/signup", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def portfolio(client, headers):
    with SessionLocal() as db: generate_mock_market_data(db, days=90, end_date=date(2026, 8, 7))
    return client.post("/portfolios", headers=headers, json={"name": "Ledger"}).json()["id"]


def test_cash_ledger_reversal_and_position_projection(client):
    headers = auth(client); portfolio_id = portfolio(client, headers)
    deposit = client.post(f"/portfolios/{portfolio_id}/transactions", headers=headers, json={"transaction_type": "deposit", "amount": "10000", "transaction_date": "2026-08-07"})
    assert deposit.status_code == 201
    buy = client.post(f"/portfolios/{portfolio_id}/transactions", headers=headers, json={"symbol": "MEBL", "transaction_type": "buy", "quantity": "10", "price": "200", "amount": "2000", "fees": "10", "taxes": "5", "transaction_date": "2026-08-07"})
    assert buy.status_code == 201
    assert client.get(f"/portfolios/{portfolio_id}/positions", headers=headers).json()[0]["quantity"] == "10.000000"
    assert Decimal(client.get(f"/portfolios/{portfolio_id}/cash", headers=headers).json()["balance"]) == Decimal("7985.0000")
    assert client.delete(f"/portfolios/transactions/{buy.json()['id']}", headers=headers).status_code == 204
    assert client.get(f"/portfolios/{portfolio_id}/positions", headers=headers).json() == []
    assert Decimal(client.get(f"/portfolios/{portfolio_id}/cash", headers=headers).json()["balance"]) == Decimal("10000.0000")


def test_ips_allocations_lifecycle_and_monitoring_are_owned(client):
    headers = auth(client, "lifecycle@example.com"); portfolio_id = portfolio(client, headers)
    client.post(f"/portfolios/{portfolio_id}/holdings", headers=headers, json={"symbol": "MEBL", "quantity": "10", "average_cost": "100"})
    ips = client.post(f"/portfolios/{portfolio_id}/ips/confirm", headers=headers, json={"constraints": {"max_instrument_weight": 0.5, "min_cash_weight": 0.05}, "starting_capital": 100000, "target_value": 150000, "horizon_years": 5})
    assert ips.status_code == 201
    compliance = client.get(f"/portfolios/{portfolio_id}/ips/compliance", headers=headers).json()
    assert compliance["compliant"] is False
    allocation = client.post(f"/portfolios/{portfolio_id}/allocations", headers=headers, json={"kind": "target", "base_value": 100000, "items": [{"symbol": "MEBL", "target_weight": 0.5}, {"symbol": "CASH", "target_weight": 0.5, "is_cash": True}]})
    assert allocation.status_code == 201
    duplicate = client.post(f"/portfolios/{portfolio_id}/duplicate", headers=headers, json={"name": "Copy", "include_positions": False})
    assert duplicate.status_code == 201 and duplicate.json()["selected_ips_version_id"]
    assert client.post(f"/portfolios/{portfolio_id}/archive", headers=headers).json()["archived_at"]
    assert client.post(f"/portfolios/{portfolio_id}/restore", headers=headers).json()["archived_at"] is None
    rule = client.post(f"/portfolios/{portfolio_id}/monitoring/rules", headers=headers, json={"rule_type": "concentration", "threshold": {"maximum": 0.5}})
    assert rule.status_code == 201
    first = client.post(f"/monitoring/runs/{portfolio_id}", headers=headers).json()
    second = client.post(f"/monitoring/runs/{portfolio_id}", headers=headers).json()
    assert len(first["alerts_created"]) == 1
    assert second["alerts_created"] == []


def test_monitoring_warning_recommendation_and_linked_sandbox_agree(client):
    headers = auth(client, "semantic-consistency@example.com"); portfolio_id = portfolio(client, headers)
    client.post(f"/portfolios/{portfolio_id}/holdings", headers=headers, json={"symbol": "MEBL", "quantity": "10", "average_cost": "100"})
    ips = client.post(f"/portfolios/{portfolio_id}/ips/confirm", headers=headers, json={"constraints": {"max_instrument_weight": 1.0, "min_cash_weight": 0.0}})
    assert ips.status_code == 201
    compliance = client.get(f"/portfolios/{portfolio_id}/ips/compliance", headers=headers).json()
    assert compliance["status"] == "PASS"
    client.post(f"/portfolios/{portfolio_id}/monitoring/rules", headers=headers, json={"rule_type": "concentration", "threshold": {"maximum": 0.5}})
    run = client.post(f"/monitoring/runs/{portfolio_id}", headers=headers).json()
    assert len(run["alerts_created"]) == 1
    alert = client.get(f"/monitoring/alerts?portfolio_id={portfolio_id}", headers=headers).json()[0]
    assert alert["classification"] == "monitoring_warning"
    assert alert["related_ips_limit"] == 1.0
    recommendation = client.get("/recommendations", headers=headers).json()[0]
    assert recommendation["evidence"]["classification"] == "monitoring_warning"
    assert recommendation["linked_allocation"] is None
    sandbox = client.post(f"/portfolios/{portfolio_id}/allocations", headers=headers, json={"kind": "sandbox", "base_value": 1000, "assumptions": {"recommendation_id": recommendation["id"]}, "items": [{"symbol": "MEBL", "target_weight": 1.0}]})
    assert sandbox.status_code == 201
    updated = client.get("/recommendations", headers=headers).json()[0]
    assert updated["status"] == "reviewed"
    assert updated["linked_allocation"]["id"] == sandbox.json()["id"]
    resolved = client.patch(f"/recommendations/{recommendation['id']}?decision=resolved", headers=headers)
    assert resolved.json() == {"id": recommendation["id"], "status": "resolved", "holdings_mutated": False}


def test_assistant_is_grounded_and_tool_registry_is_allowlisted(client):
    headers = auth(client, "assistant@example.com"); portfolio_id = portfolio(client, headers)
    response = client.post("/assistant/messages", headers=headers, json={"question": "What is my portfolio value and should I rebalance?", "portfolio_id": portfolio_id})
    assert response.status_code == 201
    body = response.json()
    assert body["calculated_evidence"]
    assert {row["tool"] for row in body["tool_trace"]} >= {"market.freshness", "portfolio.summary", "research.search"}
    assert "cannot provide a grounded" in body["answer"]
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "assistant@example.com").one()
        with pytest.raises(KeyError, match="not allowlisted"):
            build_tool_registry().invoke("sql.execute", db, user, {})


def test_demo_seed_is_idempotent_and_populates_the_decision_workflow(monkeypatch):
    monkeypatch.setenv("DEMO_USER_PASSWORD", "local-test-password")
    first = seed_workstation()
    second = seed_workstation()
    assert first["portfolio_id"] == second["portfolio_id"]
    assert first["mock_data"] is True
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "portfolio.manager@example.com").one()
        portfolio = db.query(Portfolio).filter(Portfolio.user_id == user.id).one()
        assert db.query(InvestorFinancialProfileVersion).filter_by(user_id=user.id).count() == 1
        assert db.query(PortfolioIPSVersion).filter_by(portfolio_id=portfolio.id, status="confirmed").count() == 1
        assert db.query(PortfolioTransaction).filter_by(portfolio_id=portfolio.id).count() == 4
        assert db.query(AllocationSet).filter_by(portfolio_id=portfolio.id, kind="target").count() == 1
        assert db.query(OptimizerRun).filter_by(portfolio_id=portfolio.id).count() == 1
        assert db.query(ScenarioRun).filter_by(portfolio_id=portfolio.id).count() == 1
        assert db.query(MonitoringRun).filter_by(portfolio_id=portfolio.id, status="completed").count() == 1
        recommendation = db.query(Recommendation).filter_by(portfolio_id=portfolio.id).one()
        assert 80 < len(recommendation.trigger) <= 160
