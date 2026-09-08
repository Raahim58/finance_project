import json
from datetime import date

from sqlalchemy import select

from app.ai.providers.base import LLMProviderResult, ProviderRequestError
from app.db.session import SessionLocal
from app.models.llm_invocation import LLMInvocation
from app.models.market import Company, Exchange
from app.models.workstation import Instrument
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


def test_question_without_portfolio_uses_the_global_selected_portfolio(client):
    headers = _auth(client, "assistant-global@example.com")
    portfolio_id = _portfolio_with_holdings(client, headers)

    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Where is the risk concentrated in my portfolio?"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert any(
        item.get("metric") == "percentage_risk_contribution"
        for item in body["calculated_evidence"]
    )
    conversations = client.get("/assistant/conversations", headers=headers).json()
    assert conversations[0]["portfolio_id"] == portfolio_id


def test_advice_for_named_holding_builds_portfolio_aware_security_fit_context(client):
    headers = _auth(client, "assistant-security-fit@example.com")
    portfolio_id = _portfolio_with_holdings(client, headers)

    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Analyze my existing MEBL holding. Should I add, hold, or reduce it?"
        },
    )

    assert response.status_code == 201, response.text
    context_step = next(
        step
        for step in response.json()["tool_trace"]
        if step["tool"] == "intelligence.canonical_context"
    )
    assert context_step["arguments"]["scope"] == "security_fit"
    assert context_step["arguments"]["portfolio_id"] == portfolio_id


def test_psx_market_language_routes_to_market_wide_discovery(client, monkeypatch):
    headers = _auth(client, "assistant-market-wide@example.com")
    _portfolio_with_holdings(client, headers)
    with SessionLocal() as db:
        exchange = db.scalar(select(Exchange).where(Exchange.code == "PSX"))
        company = Company(
            symbol="PSX",
            name="Pakistan Stock Exchange Limited",
            sector="Investment Banks / Investment Companies / Securities Companies",
            exchange_id=exchange.id,
        )
        db.add(company)
        db.flush()
        db.add(
            Instrument(
                company_id=company.id,
                symbol="PSX",
                name="Pakistan Stock Exchange Limited",
                sector=company.sector,
            )
        )
        db.commit()
    key_response = client.post(
        "/settings/llm-keys",
        headers=headers,
        json={"provider": "mock", "api_key": "mock-market-wide-key"},
    )
    assert key_response.status_code == 201

    class MarketProvider:
        name = "mock"
        default_model = "market-test"

        async def chat(self, _api_key, messages, _model):
            payload = json.loads(messages[-1]["content"])
            if "records" in payload:
                instrument_ids = [payload["records"][0]["instrument_id"]]
                content = {"instrument_ids": instrument_ids}
            elif "candidate_instrument_ids" in payload:
                instrument_ids = payload["candidate_instrument_ids"][:2]
                content = {"instrument_ids": instrument_ids}
            else:
                content = {
                    "answer": "Market-wide discovery completed.",
                    "recommendation": None,
                    "confidence": None,
                    "horizon": None,
                    "portfolio_id": payload["portfolio_id"],
                    "instrument_ids": payload["selected_instrument_ids"],
                    "evidence_ids": payload["allowed_evidence_ids"],
                    "freshness_acknowledgements": ["Freshness warnings acknowledged."],
                }
            return LLMProviderResult(
                content=json.dumps(content),
                provider=self.name,
                model=self.default_model,
            )

    monkeypatch.setattr(
        "app.ai.orchestrator.get_provider", lambda _name: MarketProvider()
    )

    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "What stocks should I consider investing in across the PSX market?",
            "provider": "mock",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["synthesis"]["mode_scope"] == "market_wide"
    assert any(step.get("node") == "peer_group_analysis" for step in body["tool_trace"])
    assert not any(
        step.get("tool") == "intelligence.canonical_context"
        for step in body["tool_trace"]
    )


def test_provider_error_is_saved_with_diagnostic_id_and_safe_fields(client, monkeypatch):
    headers = _auth(client, "assistant-provider-error@example.com")
    _portfolio_with_holdings(client, headers)
    key_response = client.post(
        "/settings/llm-keys",
        headers=headers,
        json={"provider": "mock", "api_key": "mock-provider-error-key"},
    )
    assert key_response.status_code == 201

    class FailingProvider:
        name = "anthropic"
        default_model = "claude-sonnet-5"

        async def chat(self, _api_key, _messages, _model):
            raise ProviderRequestError(
                provider="anthropic",
                status_code=400,
                error_type="invalid_request_error",
                provider_message="temperature is not supported for this model",
                request_id="req_123",
            )

    monkeypatch.setattr(
        "app.ai.orchestrator.get_provider", lambda _name: FailingProvider()
    )

    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Analyze my existing MEBL holding. Should I add, hold, or reduce it?",
            "provider": "mock",
            "model": "claude-sonnet-5",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    diagnostic_ids = body["synthesis"]["diagnostic_ids"]
    assert len(diagnostic_ids) == 1

    history = client.get(
        f"/assistant/conversations/{body['conversation_id']}/messages", headers=headers
    ).json()
    assistant_message = next(row for row in history if row["id"] == body["message_id"])
    assert assistant_message["evidence"]["synthesis"]["diagnostic_ids"] == diagnostic_ids

    with SessionLocal() as db:
        invocation = db.get(LLMInvocation, diagnostic_ids[0])
        assert invocation is not None
        assert invocation.assistant_message_id == body["message_id"]
        assert invocation.provider == "anthropic"
        assert invocation.model == "claude-sonnet-5"
        assert invocation.operation == "synthesis"
        assert invocation.status == "provider_error"
        assert invocation.http_status == 400
        assert invocation.error_type == "invalid_request_error"
        assert invocation.error_message == "ProviderRequestError"
        assert invocation.provider_request_id == "req_123"
        assert invocation.response_excerpt is None


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
