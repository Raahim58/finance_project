from datetime import date

from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data


def _auth(client, email="assistant@example.com"):
    response = client.post("/auth/signup", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _portfolio_with_holdings(client, headers):
    with SessionLocal() as db:
        generate_mock_market_data(db, days=120, end_date=date(2026, 8, 7))
    portfolio_id = client.post("/portfolios", headers=headers, json={"name": "Assistant test"}).json()["id"]
    assert client.post(f"/portfolios/{portfolio_id}/holdings", headers=headers, json={"symbol": "MEBL", "quantity": "10", "average_cost": "100"}).status_code == 201
    assert client.post(f"/portfolios/{portfolio_id}/holdings", headers=headers, json={"symbol": "SYS", "quantity": "5", "average_cost": "200"}).status_code == 201
    ips = client.post(
        f"/portfolios/{portfolio_id}/ips/confirm",
        headers=headers,
        json={"constraints": {"max_instrument_weight": 0.9, "min_cash_weight": 0.0}, "starting_capital": 100000, "target_value": 150000, "horizon_years": 5},
    )
    assert ips.status_code == 201
    return portfolio_id


def test_risk_concentration_question_identifies_top_contributors_and_skips_narrative_search(client):
    headers = _auth(client)
    portfolio_id = _portfolio_with_holdings(client, headers)

    response = client.post("/assistant/messages", headers=headers, json={"question": "Where is the risk concentrated in my portfolio?", "portfolio_id": portfolio_id})
    assert response.status_code == 201
    body = response.json()

    metrics = {item["metric"] for item in body["calculated_evidence"]}
    assert "percentage_risk_contribution" in metrics
    assert "concentration_hhi" in metrics
    assert "effective_holdings" in metrics
    symbols_with_risk_contribution = {item["symbol"] for item in body["calculated_evidence"] if item["metric"] == "percentage_risk_contribution"}
    assert symbols_with_risk_contribution == {"MEBL", "SYS"}
    capital_weight_entries = [item for item in body["calculated_evidence"] if item["metric"] == "total_capital_weight"]
    assert all(item["portfolio_basis"] == "total_capital" for item in capital_weight_entries)
    risk_entries = [item for item in body["calculated_evidence"] if item["metric"] == "percentage_risk_contribution"]
    assert all(item["portfolio_basis"] == "risky_sleeve" for item in risk_entries)
    assert body["source_citations"] == []
    search_trace = next(step for step in body["tool_trace"] if step["tool"] == "research.search")
    assert search_trace["status"] == "skipped"


def test_compliance_question_reports_status_and_skips_narrative_search(client):
    headers = _auth(client)
    portfolio_id = _portfolio_with_holdings(client, headers)

    response = client.post("/assistant/messages", headers=headers, json={"question": "Does my portfolio meet the confirmed IPS mandate?", "portfolio_id": portfolio_id})
    assert response.status_code == 201
    body = response.json()

    assert any(item["metric"] == "compliance_status" for item in body["calculated_evidence"])
    search_trace = next(step for step in body["tool_trace"] if step["tool"] == "research.search")
    assert search_trace["status"] == "skipped"


def test_market_overview_question_uses_freshness_fields_without_portfolio_scope(client):
    headers = _auth(client)
    response = client.post("/assistant/messages", headers=headers, json={"question": "What is the current market data freshness and provider status?"})
    assert response.status_code == 201
    body = response.json()
    assert any(item["metric"] == "market_data_mode" for item in body["calculated_evidence"])


def test_holding_question_triggers_narrative_search_and_gates_citations_by_symbol(client):
    headers = _auth(client)
    portfolio_id = _portfolio_with_holdings(client, headers)
    long_text = "Meezan Bank management discussed deposit growth and Islamic banking demand. " * 12
    ingest_mebl = client.post("/documents/ingest-text", headers=headers, json={"title": "MEBL note", "document_type": "annual_report", "symbol": "MEBL", "source_name": "Demo", "text": long_text})
    assert ingest_mebl.status_code == 201
    unrelated_text = "Oil and Gas Development Company management discussed exploration and drilling capex. " * 12
    ingest_ogdc = client.post("/documents/ingest-text", headers=headers, json={"title": "OGDC note", "document_type": "annual_report", "symbol": "OGDC", "source_name": "Demo", "text": unrelated_text})
    assert ingest_ogdc.status_code == 201

    response = client.post("/assistant/messages", headers=headers, json={"question": "Why did management discuss deposit growth in the latest filing for my holding?", "portfolio_id": portfolio_id})
    assert response.status_code == 201
    body = response.json()

    search_trace = next(step for step in body["tool_trace"] if step["tool"] == "research.search")
    assert search_trace["status"] == "completed"
    assert search_trace["arguments"]["symbols"] == ["MEBL", "SYS"]
    for citation in body["source_citations"]:
        assert citation["symbol"] in {"MEBL", "SYS"}
