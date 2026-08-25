import json
from datetime import date

from sqlalchemy import select

from app.ai.providers.base import LLMProviderResult
from app.ai.orchestrator import _validated_claim_answer
from app.db.session import SessionLocal
from app.models.intelligence_context import (
    ContextIngestionWork,
    ContextRefreshRequest,
    IntelligenceContextReceiptRecord,
)
from app.models.user import User, UserPreferences
from app.models.workstation import AssistantMessage, Instrument, StandardizedFinancialFact
from app.services.market_ingestion import generate_mock_market_data
from app.services.context_refresh_service import reconcile_pending_contexts


def _auth(client, email: str):
    response = client.post("/auth/signup", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _instrument_and_fact() -> str:
    with SessionLocal() as db:
        generate_mock_market_data(db, days=120, end_date=date(2026, 8, 7))
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        db.add(
            StandardizedFinancialFact(
                instrument_id=instrument.id,
                metric="revenue",
                period_type="annual",
                period_key="2025",
                period_end=date(2025, 12, 31),
                value=100,
                unit="PKR",
                currency="PKR",
                source="dps",
                source_url="https://dps.psx.com.pk/company/MEBL",
                quality_status="observed",
            )
        )
        db.commit()
        return instrument.id


def _portfolio(client, headers, name: str, *, confirm_ips: bool = True) -> str:
    portfolio_id = client.post("/portfolios", headers=headers, json={"name": name}).json()["id"]
    assert (
        client.post(
            f"/portfolios/{portfolio_id}/holdings",
            headers=headers,
            json={"symbol": "MEBL", "quantity": "10", "average_cost": "100"},
        ).status_code
        == 201
    )
    if confirm_ips:
        response = client.post(
            f"/portfolios/{portfolio_id}/ips/confirm",
            headers=headers,
            json={
                "constraints": {
                    "max_instrument_weight": 0.7,
                    "max_sector_weight": 0.8,
                    "min_cash_weight": 0,
                },
                "horizon_years": 5,
            },
        )
        assert response.status_code == 201
    return portfolio_id


def test_company_research_uses_company_only_canonical_contract_and_persists_receipt(client):
    headers = _auth(client, "phase7b-company@example.com")
    instrument_id = _instrument_and_fact()

    response = client.get(f"/companies/{instrument_id}/overview", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["context_contract_version"] == "7a.v1"
    assert body["context"]["scope"] == "company_intelligence"
    assert "portfolio" not in body["context"]["sections"]
    assert "ips" not in body["context"]["sections"]
    assert body["context_receipt"]["content_hash"]
    with SessionLocal() as db:
        receipt = db.get(IntelligenceContextReceiptRecord, body["context_receipt_id"])
        assert receipt.consumer_type == "company_research"
        assert receipt.consumer_key == f"instrument:{instrument_id}:portfolio:none"


def test_company_view_can_deactivate_refresh_for_lazy_rebuild(client):
    headers = _auth(client, "phase7b-inactive@example.com")
    instrument_id = _instrument_and_fact()
    body = client.get(f"/companies/{instrument_id}/overview", headers=headers).json()
    refresh_id = body["refresh_request_id"]
    assert refresh_id

    response = client.post(
        f"/research/context-refreshes/{refresh_id}/deactivate", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["active"] is False
    with SessionLocal() as db:
        assert db.get(ContextRefreshRequest, refresh_id).active is False


def test_active_company_view_returns_rebuilt_canonical_result(client):
    headers = _auth(client, "phase7b-active-company@example.com")
    instrument_id = _instrument_and_fact()
    initial = client.get(f"/companies/{instrument_id}/overview", headers=headers).json()
    refresh_id = initial["refresh_request_id"]
    assert refresh_id

    with SessionLocal() as db:
        for work in db.scalars(select(ContextIngestionWork)):
            work.status = "succeeded"
        db.commit()
        sweep = reconcile_pending_contexts(db)
        assert sweep.rebuilt == 1

    refreshed = client.get(
        f"/research/context-refreshes/{refresh_id}", headers=headers
    )
    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["status"] == "rebuilt"
    assert body["result"]["context_contract_version"] == "7a.v1"
    assert body["result"]["context_receipt_id"] != initial["context_receipt_id"]
    assert body["result"]["context"]["scope"] == "company_intelligence"


def test_company_research_switches_exactly_one_portfolio_and_reuses_company_evidence(client):
    headers = _auth(client, "phase7b-switch@example.com")
    instrument_id = _instrument_and_fact()
    first = _portfolio(client, headers, "First mandate")
    second = _portfolio(client, headers, "Second mandate")

    one = client.get(
        f"/companies/{instrument_id}/overview?portfolio_id={first}", headers=headers
    ).json()["context"]
    two = client.get(
        f"/companies/{instrument_id}/overview?portfolio_id={second}", headers=headers
    ).json()["context"]

    assert one["scope"] == two["scope"] == "portfolio_relevance"
    assert one["sections"]["portfolio"]["data"]["id"] == first
    assert two["sections"]["portfolio"]["data"]["id"] == second
    assert one["sections"]["ips"]["data"]["portfolio_id"] == first
    assert two["sections"]["ips"]["data"]["portfolio_id"] == second
    assert [row["evidence_id"] for row in one["sections"]["company_facts"]["evidence"]] == [
        row["evidence_id"] for row in two["sections"]["company_facts"]["evidence"]
    ]
    assert two["sections"]["company_facts"]["reused"] is True


def test_company_research_rejects_another_users_portfolio_before_persisting_receipt(client):
    owner = _auth(client, "phase7b-owner@example.com")
    intruder = _auth(client, "phase7b-intruder@example.com")
    instrument_id = _instrument_and_fact()
    portfolio_id = _portfolio(client, owner, "Private mandate")

    response = client.get(
        f"/companies/{instrument_id}/overview?portfolio_id={portfolio_id}",
        headers=intruder,
    )

    assert response.status_code == 404
    with SessionLocal() as db:
        intruder_user = db.scalar(select(User).where(User.email == "phase7b-intruder@example.com"))
        assert (
            db.scalar(
                select(IntelligenceContextReceiptRecord).where(
                    IntelligenceContextReceiptRecord.user_id == intruder_user.id
                )
            )
            is None
        )


def test_security_fit_requires_selected_portfolio_and_confirmed_ips(client):
    headers = _auth(client, "phase7b-fit-scope@example.com")
    instrument_id = _instrument_and_fact()

    missing_portfolio = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Does MEBL fit my portfolio?", "instrument_id": instrument_id},
    )
    assert missing_portfolio.status_code == 422

    portfolio_id = _portfolio(client, headers, "Unconfirmed", confirm_ips=False)
    missing_ips = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Does MEBL fit my portfolio?",
            "instrument_id": instrument_id,
            "portfolio_id": portfolio_id,
        },
    )
    assert missing_ips.status_code == 422


def test_assistant_fit_uses_canonical_evidence_receipt_and_excludes_user_preferences(client):
    headers = _auth(client, "phase7b-assistant@example.com")
    instrument_id = _instrument_and_fact()
    portfolio_id = _portfolio(client, headers, "Selected mandate")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "phase7b-assistant@example.com"))
        preferences = db.scalar(select(UserPreferences).where(UserPreferences.user_id == user.id))
        preferences.preferred_sectors = '["Banking"]'
        preferences.avoided_sectors = '["Technology"]'
        db.commit()

    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Does MEBL fit my portfolio?",
            "instrument_id": instrument_id,
            "portfolio_id": portfolio_id,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["context_contract_version"] == "7a.v1"
    assert body["synthesis"]["mode"] == "deterministic_fallback"
    assert any(row["tool"] == "intelligence.canonical_context" for row in body["tool_trace"])
    assert any(row["tool"] == "research.search" for row in body["tool_trace"])
    serialized = json.dumps(body)
    assert "preferred_sectors" not in serialized
    assert "avoided_sectors" not in serialized
    with SessionLocal() as db:
        message = db.get(AssistantMessage, body["message_id"])
        assert message.context_receipt_id is not None
        receipt = db.get(IntelligenceContextReceiptRecord, message.context_receipt_id)
        assert receipt.consumer_type == "assistant"
        assert receipt.consumer_key == body["conversation_id"]
        assert receipt.output_id == message.id


def test_security_fit_performs_normal_llm_planning_round(client, monkeypatch):
    headers = _auth(client, "phase7b-planner@example.com")
    instrument_id = _instrument_and_fact()
    portfolio_id = _portfolio(client, headers, "Planner mandate")
    assert (
        client.post(
            "/settings/llm-keys",
            headers=headers,
            json={"provider": "mock", "api_key": "mock-secret-1234"},
        ).status_code
        == 201
    )
    calls = []

    async def planned(*_args, **_kwargs):
        calls.append("planned")
        return []

    class Provider:
        async def chat(self, _api_key, _messages, _model):
            return LLMProviderResult(content="{}", provider="test", model="test")

    monkeypatch.setattr("app.ai.orchestrator._planned_tool_calls", planned)
    monkeypatch.setattr("app.ai.orchestrator.get_provider", lambda _name: Provider())

    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Does MEBL fit my portfolio?",
            "instrument_id": instrument_id,
            "portfolio_id": portfolio_id,
            "provider": "mock",
        },
    )

    assert response.status_code == 201, response.text
    assert calls == ["planned"]
    assert response.json()["synthesis"]["mode"] == "deterministic_fallback"


def test_llm_synthesis_and_fallback_share_canonical_evidence_ids(client, monkeypatch):
    headers = _auth(client, "phase7b-grounded@example.com")
    instrument_id = _instrument_and_fact()
    portfolio_id = _portfolio(client, headers, "Grounded mandate")
    assert (
        client.post(
            "/settings/llm-keys",
            headers=headers,
            json={"provider": "mock", "api_key": "mock-secret-1234"},
        ).status_code
        == 201
    )

    async def planned(*_args, **_kwargs):
        return []

    class Provider:
        async def chat(self, _api_key, messages, _model):
            grounded = json.loads(messages[-1]["content"])
            evidence_id = grounded["allowed_evidence_ids"][0]
            return LLMProviderResult(
                content=json.dumps(
                    {
                        "answer": "The evidence supports a conditional fit.",
                        "claims": [
                            {
                                "text": "The evidence supports a conditional fit.",
                                "evidence_ids": [evidence_id],
                            }
                        ],
                    }
                ),
                provider="test",
                model="test",
            )

    monkeypatch.setattr("app.ai.orchestrator._planned_tool_calls", planned)
    monkeypatch.setattr("app.ai.orchestrator.get_provider", lambda _name: Provider())

    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Does MEBL fit my portfolio?",
            "instrument_id": instrument_id,
            "portfolio_id": portfolio_id,
            "provider": "mock",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["synthesis"]["mode"] == "llm_grounded"
    calculated_ids = {row["evidence_id"] for row in body["calculated_evidence"]}
    assert calculated_ids <= set(body["context_receipt"]["evidence_ids"])


def test_assistant_refresh_creates_linked_followup_without_rewriting_original(client):
    headers = _auth(client, "phase7b-refresh@example.com")
    instrument_id = _instrument_and_fact()
    portfolio_id = _portfolio(client, headers, "Refresh mandate")
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Does MEBL fit my portfolio?",
            "instrument_id": instrument_id,
            "portfolio_id": portfolio_id,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["refresh_request_id"]

    with SessionLocal() as db:
        original = db.get(AssistantMessage, body["message_id"])
        original_content = original.content
        for work in db.scalars(select(ContextIngestionWork)):
            work.status = "succeeded"
        db.commit()

        result = reconcile_pending_contexts(db)

        assert result.rebuilt == 1
        db.refresh(original)
        assert original.content == original_content
        followup = db.scalar(
            select(AssistantMessage).where(
                AssistantMessage.parent_message_id == original.id,
                AssistantMessage.message_kind == "context_refresh",
            )
        )
        assert followup is not None
        assert followup.context_receipt_id is not None
        assert "original answer remains unchanged" in followup.content
        receipt = db.get(IntelligenceContextReceiptRecord, followup.context_receipt_id)
        assert receipt.consumer_type == "assistant"
        assert receipt.output_id == followup.id


def test_returning_to_assistant_conversation_lazily_rebuilds_inactive_context(client):
    headers = _auth(client, "phase7b-lazy-assistant@example.com")
    instrument_id = _instrument_and_fact()
    portfolio_id = _portfolio(client, headers, "Lazy refresh mandate")
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Does MEBL fit my portfolio?",
            "instrument_id": instrument_id,
            "portfolio_id": portfolio_id,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()

    deactivated = client.post(
        f"/research/context-refreshes/{body['refresh_request_id']}/deactivate",
        headers=headers,
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["active"] is False

    with SessionLocal() as db:
        for work in db.scalars(select(ContextIngestionWork)):
            work.status = "succeeded"
        db.commit()
        inactive_sweep = reconcile_pending_contexts(db)
        assert inactive_sweep.marked_lazy == 1
        refresh = db.get(ContextRefreshRequest, body["refresh_request_id"])
        assert refresh.needs_rebuild is True
        assert refresh.rebuild_count == 0

    messages = client.get(
        f"/assistant/conversations/{body['conversation_id']}/messages", headers=headers
    )
    assert messages.status_code == 200
    linked_updates = [
        message
        for message in messages.json()
        if message["message_kind"] == "context_refresh"
        and message["parent_message_id"] == body["message_id"]
    ]
    assert len(linked_updates) == 1

    with SessionLocal() as db:
        refresh = db.get(ContextRefreshRequest, body["refresh_request_id"])
        assert refresh.active is True
        assert refresh.needs_rebuild is False
        assert refresh.rebuild_count == 1


def test_llm_claim_validation_rejects_unknown_ids_numbers_and_ungrounded_advice():
    unknown, unknown_reason = _validated_claim_answer(
        json.dumps(
            {
                "answer": "Grounded statement.",
                "claims": [{"text": "Grounded statement.", "evidence_ids": ["ev_unknown"]}],
            }
        ),
        "context",
        {"ev_allowed"},
        set(),
    )
    assert unknown is None
    assert "valid evidence ID" in unknown_reason

    numeric, numeric_reason = _validated_claim_answer(
        json.dumps(
            {
                "answer": "The value is 99.",
                "claims": [{"text": "The value is high.", "evidence_ids": ["ev_allowed"]}],
            }
        ),
        "context without that number",
        {"ev_allowed"},
        set(),
    )
    assert numeric is None
    assert "numeric grounding" in numeric_reason

    advice, advice_reason = _validated_claim_answer(
        json.dumps(
            {
                "answer": "Buy it.",
                "claims": [{"text": "Buy it.", "evidence_ids": []}],
            }
        ),
        "context",
        {"ev_allowed"},
        set(),
    )
    assert advice is None
    assert "valid evidence ID" in advice_reason
