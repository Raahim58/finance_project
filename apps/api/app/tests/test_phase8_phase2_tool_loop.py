"""Offline Phase 2 provider/registry/transcript acceptance cases."""

import json
import asyncio
from datetime import date

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.base import ContentBlock, ProviderRequestError, ProviderTurn
from app.ai.providers.http_placeholders import AnthropicProvider, GeminiProvider
from app.ai.tool_loop import (
    AssistantTerminalError,
    ToolExecution,
    _initial_checkpoint,
    resolve_citations,
    run_tool_loop,
    unwrap_final_text,
)
from app.core.config import settings
from app.core.security import decrypt_secret, encrypt_secret
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantAttempt, AssistantExecution
from app.models.llm_key import LLMApiKey
from app.models.user import User
from app.models.workstation import AssistantMessage, Instrument
from app.schemas.assistant import AssistantMessageCreate
from app.services import assistant_diagnostics as diagnostics
from app.services.assistant_execution import accept
from app.tools.registry import tool_result
from app.services.market_ingestion import generate_mock_market_data


def _anthropic_tool_results(payload):
    return [
        json.loads(block["content"])
        for block in payload["messages"][-1]["content"]
        if block["type"] == "tool_result"
    ]


def _mock_market(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "mock")
    with SessionLocal() as db:
        generate_mock_market_data(db, days=40, end_date=date(2026, 8, 7))
        rows = list(db.scalars(select(Instrument).order_by(Instrument.symbol)))
        return rows


def _auth_with_anthropic(client, monkeypatch, email="phase2@example.com"):
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    response = client.post("/auth/signup", json={"email": email, "password": "password123"})
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == email))
        user.preferences.default_llm_provider = "anthropic"
        db.add(
            LLMApiKey(
                user_id=user.id,
                provider="anthropic",
                encrypted_api_key=encrypt_secret("offline-anthropic-key"),
                masked_api_key="offlin...-key",
                default_model="claude-test",
            )
        )
        return headers, user.id


def _auth_with_gemini(client, monkeypatch, email="phase2-gemini@example.com"):
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    response = client.post("/auth/signup", json={"email": email, "password": "password123"})
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == email))
        user.preferences.default_llm_provider = "gemini"
        db.add(
            LLMApiKey(
                user_id=user.id,
                provider="gemini",
                encrypted_api_key=encrypt_secret("offline-gemini-key"),
                masked_api_key="offlin...-key",
                default_model="gemini-2.5-flash-lite",
            )
        )
        return headers, user.id


def test_legacy_json_unwrap_keeps_readable_text_without_semantic_label():
    assert unwrap_final_text('{"answer":"Readable initial response.","claims":[]}') == (
        "Readable initial response."
    )
    assert unwrap_final_text('```json\n{"answer":"Readable repaired response."}\n```') == (
        "Readable repaired response."
    )


def test_false_sentence_citation_resolves_as_reference_not_proof():
    checkpoint = {
        "evidence": {
            "E7": {
                "identity": "stored",
                "source": {
                    "id": "citation-7",
                    "title": "Annual report",
                    "source_url": "https://example.test/report",
                    "page_number": 7,
                },
            }
        }
    }

    answer, sources, outcome = resolve_citations("MEBL is made of cheese [[E7]].", checkpoint)

    assert "https://example.test/report" in answer
    assert sources[0]["id"] == "citation-7"
    assert outcome["status"] == "resolved"
    assert outcome["semantic_verification"] == "not_performed"


def test_native_anthropic_loop_dispatches_parallel_tools_and_persists_transcript(
    client, monkeypatch
):
    headers, user_id = _auth_with_anthropic(client, monkeypatch)
    monkeypatch.setattr(diagnostics, "sampled", lambda _identifier: True)
    document = client.post(
        "/documents/ingest-text",
        headers=headers,
        json={
            "title": "MEBL annual report note",
            "document_type": "annual_report",
            "symbol": "MEBL",
            "source_name": "Stored filing",
            "source_url": "https://example.test/mebl-report",
            "text": "Meezan Bank deposit growth and funding mix were discussed. " * 20,
        },
    )
    assert document.status_code == 201

    provider = AnthropicProvider()
    captured = []
    responses = [
        {
            "id": "msg-tool-only",
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call-discover",
                    "name": "documents__discover",
                    "input": {"query": "deposit growth", "limit": 5},
                },
                {
                    "type": "tool_use",
                    "id": "call-freshness",
                    "name": "market__freshness",
                    "input": {},
                },
            ],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
        {
            "id": "msg-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": "The filing proves the moon is green [[E1]].",
                }
            ],
            "usage": {"input_tokens": 200, "output_tokens": 15},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)

    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "What does the stored MEBL evidence say?", "provider": "anthropic"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert [row["tool"] for row in body["tool_trace"]] == [
        "documents.discover",
        "market.freshness",
    ]
    assert body["source_citations"][0]["source_url"] == "https://example.test/mebl-report"
    assert body["synthesis"]["citation_resolution"]["semantic_verification"] == "not_performed"
    assert body["synthesis"]["mode"] == "llm_tool_loop"
    assert captured[0]["tools"]
    assert captured[1]["messages"][-1]["role"] == "user"
    assert [block["tool_use_id"] for block in captured[1]["messages"][-1]["content"][:2]] == [
        "call-discover",
        "call-freshness",
    ]

    with SessionLocal() as db:
        execution = db.scalar(
            select(AssistantExecution)
            .where(AssistantExecution.user_id == user_id)
            .order_by(AssistantExecution.created_at.desc())
        )
        checkpoint = json.loads(decrypt_secret(execution.transcript_encrypted))
        attempts = list(
            db.scalars(
                select(AssistantAttempt)
                .where(AssistantAttempt.execution_id == execution.id)
                .order_by(AssistantAttempt.created_at)
            )
        )
    assert [turn["role"] for turn in checkpoint["turns"]][-3:] == [
        "assistant",
        "user",
        "assistant",
    ]
    assert len(attempts) == 2
    assert all(attempt.status == "completed" for attempt in attempts)
    attempt_metadata = [json.loads(attempt.metadata_json) for attempt in attempts]
    assert attempt_metadata[1]["estimated_input_tokens"] > attempt_metadata[0][
        "estimated_input_tokens"
    ]
    retained_request = json.loads(decrypt_secret(attempts[1].payload_encrypted))["messages"]
    assert '"tools"' in retained_request[0]["content"]
    assert "call-discover" in retained_request[0]["content"]
    assert execution.reserved_input_tokens > 0


def test_native_gemini_loop_dispatches_registry_and_preserves_signature(client, monkeypatch):
    headers, _ = _auth_with_gemini(client, monkeypatch)
    provider = GeminiProvider()
    captured = []
    signed_call = {
        "functionCall": {"name": "market__freshness", "args": {}},
        "thoughtSignature": "opaque-loop-signature",
    }
    responses = [
        {
            "responseId": "gemini-loop-tools",
            "modelVersion": "gemini-2.5-flash-lite",
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"role": "model", "parts": [signed_call]},
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
        },
        {
            "responseId": "gemini-loop-final",
            "modelVersion": "gemini-2.5-flash-lite",
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"role": "model", "parts": [{"text": "Freshness inspected."}]},
                }
            ],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 3},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Is market data fresh?", "provider": "gemini"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["tool_trace"][0]["tool"] == "market.freshness"
    assert captured[1]["contents"][-2]["parts"][0] == signed_call
    function_response = captured[1]["contents"][-1]["parts"][0]["functionResponse"]
    assert function_response["name"] == "market__freshness"
    assert "id" not in function_response


def test_parallel_tool_workers_are_bounded_to_four_and_keep_call_order(client, monkeypatch):
    headers, _ = _auth_with_anthropic(client, monkeypatch, email="bounded-tools@example.com")
    provider = AnthropicProvider()
    responses = [
        {
            "id": "five-tools",
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"bounded-{index}",
                    "name": "market__freshness",
                    "input": {},
                }
                for index in range(5)
            ],
            "usage": {},
        },
        {
            "id": "bounded-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Bounded work complete."}],
            "usage": {},
        },
    ]
    active = 0
    peak = 0

    async def fake_post(_url, _key, _payload):
        return responses.pop(0)

    async def measured_tool(_user_id, call):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return ToolExecution(call, tool_result("ok", returned=1, remaining=0), 10.0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    monkeypatch.setattr("app.ai.tool_loop._execute_tool", measured_tool)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Run five independent checks", "provider": "anthropic"},
    )

    assert response.status_code == 201, response.text
    assert peak == 4
    assert [row["tool_call_id"] for row in response.json()["tool_trace"]] == [
        f"bounded-{index}" for index in range(5)
    ]


def test_request_categories_use_real_registry_services_and_pagination(client, monkeypatch):
    headers, _ = _auth_with_anthropic(client, monkeypatch, email="categories@example.com")
    instruments = _mock_market(monkeypatch)
    first, second = instruments[:2]
    portfolio_id = client.post(
        "/portfolios", headers=headers, json={"name": "Comparison portfolio"}
    ).json()["id"]
    provider = AnthropicProvider()
    captured = []
    calls = [
        ("ambiguous-company", "research__instruments", {"query": "Bank", "limit": 20}),
        ("universe-page-1", "market__universe", {"limit": 1}),
        (
            "company-a",
            "research__company_sections",
            {"instrument_id": first.id, "sections": ["company_facts"]},
        ),
        ("portfolio", "portfolio__summary", {"portfolio_id": portfolio_id}),
        ("universe-page-2", "market__universe", {"cursor": "1", "limit": 1}),
        (
            "company-b",
            "research__company_sections",
            {"instrument_id": second.id, "sections": ["company_facts"]},
        ),
    ]
    responses = [
        {
            "id": f"category-tool-{index}",
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": identifier,
                    "name": name,
                    "input": arguments,
                }
            ],
            "usage": {},
        }
        for index, (identifier, name, arguments) in enumerate(calls)
    ] + [
        {
            "id": "category-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Comparison complete; missing data noted."}],
            "usage": {},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Compare two companies with my portfolio and inspect the PSX universe.",
            "portfolio_id": portfolio_id,
            "provider": "anthropic",
        },
    )

    assert response.status_code == 201, response.text
    results = [_anthropic_tool_results(payload)[0] for payload in captured[1:7]]
    assert results[0]["coverage"]["returned"] >= 2
    assert results[1]["coverage"]["returned"] == 1
    assert results[1]["coverage"]["remaining"] == len(instruments) - 1
    assert results[1]["coverage"]["continuation"] == "1"
    assert [row["status"] for row in results[2:4]] == ["ok", "ok"]
    assert results[4]["coverage"]["returned"] == 1
    assert results[5]["status"] == "ok"
    assert [row["tool"] for row in response.json()["tool_trace"]][-2:] == [
        "market.universe",
        "research.company_sections",
    ]


def test_malformed_and_forbidden_calls_return_stable_associated_results(client, monkeypatch):
    headers, _ = _auth_with_anthropic(client, monkeypatch, email="invalid-tools@example.com")
    provider = AnthropicProvider()
    captured = []
    responses = [
        {
            "id": "invalid-tools",
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "malformed",
                    "name": "market__series",
                    "input": {},
                },
                {
                    "type": "tool_use",
                    "id": "forbidden",
                    "name": "broker__place_trade",
                    "input": {"symbol": "MEBL"},
                },
                {
                    "type": "tool_use",
                    "id": "missing-data",
                    "name": "market__series",
                    "input": {"instrument_id": "missing-instrument"},
                },
            ],
            "usage": {},
        },
        {
            "id": "invalid-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "The requested tools were unavailable."}],
            "usage": {},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Try invalid operations", "provider": "anthropic"},
    )

    assert response.status_code == 201, response.text
    blocks = captured[1]["messages"][-1]["content"]
    assert [block["tool_use_id"] for block in blocks] == [
        "malformed",
        "forbidden",
        "missing-data",
    ]
    results = _anthropic_tool_results(captured[1])
    assert results[0]["data"]["error"]["code"] == "invalid_arguments"
    assert results[1]["data"]["error"]["code"] == "forbidden_tool"
    assert results[2]["status"] == "missing"


def test_allocation_tools_reject_overselling_and_ips_breaches(client, monkeypatch):
    headers, _ = _auth_with_anthropic(client, monkeypatch, email="allocation-loop@example.com")
    instruments = _mock_market(monkeypatch)
    mebl = next(row for row in instruments if row.symbol == "MEBL")
    portfolio_id = client.post(
        "/portfolios", headers=headers, json={"name": "Allocation portfolio"}
    ).json()["id"]
    holding = client.post(
        f"/portfolios/{portfolio_id}/holdings",
        headers=headers,
        json={"symbol": "MEBL", "quantity": "1", "average_cost": "100"},
    )
    assert holding.status_code == 201, holding.text
    deposit = client.post(
        f"/portfolios/{portfolio_id}/transactions",
        headers=headers,
        json={
            "symbol": "CASH",
            "transaction_type": "deposit",
            "amount": "10000",
            "transaction_date": "2026-08-07",
        },
    )
    assert deposit.status_code == 201, deposit.text
    ips = client.post(
        f"/portfolios/{portfolio_id}/ips/confirm",
        headers=headers,
        json={
            "constraints": {
                "max_instrument_weight": 0.05,
                "max_sector_weight": 1.0,
                "min_cash_weight": 0.0,
            },
            "horizon_years": 5,
        },
    )
    assert ips.status_code == 201, ips.text

    provider = AnthropicProvider()
    captured = []
    responses = [
        {
            "id": "allocation-tools",
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "oversell",
                    "name": "allocation__verify",
                    "input": {
                        "portfolio_id": portfolio_id,
                        "allowed_instrument_ids": [mebl.id],
                        "proposal": {
                            "legs": [
                                {
                                    "instrument_id": mebl.id,
                                    "side": "sell",
                                    "gross_amount": "999999",
                                }
                            ]
                        },
                    },
                }
            ],
            "usage": {},
        },
        {
            "id": "allocation-ips-tool",
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "ips-breach",
                    "name": "allocation__verify",
                    "input": {
                        "portfolio_id": portfolio_id,
                        "allowed_instrument_ids": [mebl.id],
                        "proposal": {
                            "legs": [
                                {
                                    "instrument_id": mebl.id,
                                    "side": "buy",
                                    "gross_amount": "5000",
                                }
                            ]
                        },
                    },
                }
            ],
            "usage": {},
        },
        {
            "id": "allocation-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Both proposals were rejected."}],
            "usage": {},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Size these alternatives without changing my portfolio.",
            "portfolio_id": portfolio_id,
            "provider": "anthropic",
        },
    )

    assert response.status_code == 201, response.text
    oversell = _anthropic_tool_results(captured[1])[0]
    ips_breach = _anthropic_tool_results(captured[2])[0]
    assert "overselling" in oversell["data"]["errors"]
    assert "binding_constraint_breach_remains" in ips_breach["data"]["errors"]
    body = response.json()
    assert body["synthesis"]["allocation_check"]["status"] == "rejected"
    assert body["synthesis"]["allocation_check"]["financial_state_mutated"] is False
    assert "Allocation check: rejected" in body["answer"]


def test_restart_resumes_persisted_tool_turn_before_another_provider_call(client, monkeypatch):
    _, user_id = _auth_with_anthropic(client, monkeypatch, email="restart-loop@example.com")
    payload = AssistantMessageCreate(question="Check freshness", provider="anthropic")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        execution = accept(db, user, payload, "restart-request")
        execution_id = execution.id
        conversation_id = execution.conversation_id
    with SessionLocal.begin() as db:
        user = db.get(User, user_id)
        checkpoint = _initial_checkpoint(db, user, payload, conversation_id)
        checkpoint.update(provider="anthropic", model="claude-test")
        checkpoint["turns"].append(
            ProviderTurn(
                "assistant",
                [ContentBlock("tool_call", id="restart-tool", name="market.freshness", arguments={})],
            ).to_dict()
        )
        db.get(AssistantExecution, execution_id).transcript_encrypted = encrypt_secret(
            json.dumps(checkpoint, separators=(",", ":"))
        )

    provider = AnthropicProvider()
    captured = []

    async def final_after_resume(_url, _key, request):
        captured.append(request)
        return {
            "id": "resumed-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Freshness checked after restart."}],
            "usage": {},
        }

    monkeypatch.setattr(provider, "_post", final_after_resume)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    token = diagnostics.execution_id.set(execution_id)
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            result = asyncio.run(
                run_tool_loop(db, user, payload, conversation_id, accepted=True)
            )
    finally:
        diagnostics.execution_id.reset(token)

    assert result["answer"] == "Freshness checked after restart."
    assert len(captured) == 1
    result_blocks = captured[0]["messages"][-1]["content"]
    assert result_blocks[0]["type"] == "tool_result"
    assert result_blocks[0]["tool_use_id"] == "restart-tool"
    with SessionLocal() as db:
        checkpoint = json.loads(
            decrypt_secret(db.get(AssistantExecution, execution_id).transcript_encrypted)
        )
    assert checkpoint["completed_tool_call_ids"] == ["restart-tool"]


def test_checkpoint_persistence_failure_has_specific_durable_terminal_code(client, monkeypatch):
    headers, user_id = _auth_with_anthropic(
        client, monkeypatch, email="checkpoint-failure@example.com"
    )
    provider = AnthropicProvider()

    async def final_response(_url, _key, _request):
        return {
            "id": "persistence-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "This turn cannot be checkpointed."}],
            "usage": {},
        }

    from app.ai import tool_loop

    original_save = tool_loop._save_checkpoint
    saves = 0

    def fail_after_attempt(identifier, checkpoint):
        nonlocal saves
        saves += 1
        if saves == 3:
            raise AssistantTerminalError("checkpoint_persistence_failed")
        return original_save(identifier, checkpoint)

    monkeypatch.setattr(provider, "_post", final_response)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    monkeypatch.setattr("app.ai.tool_loop._save_checkpoint", fail_after_attempt)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Persist this", "provider": "anthropic"},
    )

    assert response.status_code == 503
    with SessionLocal() as db:
        execution = db.scalar(
            select(AssistantExecution).where(AssistantExecution.user_id == user_id)
        )
        attempts = list(
            db.scalars(
                select(AssistantAttempt).where(AssistantAttempt.execution_id == execution.id)
            )
        )
    assert execution.error_code == "checkpoint_persistence_failed"
    assert len(attempts) == 1 and attempts[0].status == "completed"


def test_final_message_persistence_failure_is_distinct(client, monkeypatch):
    headers, user_id = _auth_with_anthropic(
        client, monkeypatch, email="response-failure@example.com"
    )
    provider = AnthropicProvider()

    async def final_response(_url, _key, _request):
        return {
            "id": "response-persistence-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Cannot persist this message."}],
            "usage": {},
        }

    original_add = Session.add

    def fail_message(self, instance, *args, **kwargs):
        if isinstance(instance, AssistantMessage) and instance.role == "assistant":
            raise RuntimeError("simulated message persistence failure")
        return original_add(self, instance, *args, **kwargs)

    monkeypatch.setattr(provider, "_post", final_response)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    monkeypatch.setattr(Session, "add", fail_message)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Persist the final answer", "provider": "anthropic"},
    )

    assert response.status_code == 503
    with SessionLocal() as db:
        execution = db.scalar(
            select(AssistantExecution).where(AssistantExecution.user_id == user_id)
        )
        attempt = db.scalar(
            select(AssistantAttempt).where(AssistantAttempt.execution_id == execution.id)
        )
    assert execution.error_code == "response_persistence_failed"
    assert attempt.status == "completed"


def test_attempt_outcome_persistence_failure_keeps_sent_attempt_linkage(client, monkeypatch):
    headers, user_id = _auth_with_anthropic(
        client, monkeypatch, email="attempt-failure@example.com"
    )
    provider = AnthropicProvider()

    async def final_response(_url, _key, _request):
        return {
            "id": "attempt-persistence-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Provider completed."}],
            "usage": {},
        }

    def fail_attempt_outcome(*_args, **_kwargs):
        raise RuntimeError("simulated attempt outcome persistence failure")

    monkeypatch.setattr(provider, "_post", final_response)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    monkeypatch.setattr(diagnostics, "finish_attempt", fail_attempt_outcome)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Record the attempt", "provider": "anthropic"},
    )

    assert response.status_code == 503
    with SessionLocal() as db:
        execution = db.scalar(
            select(AssistantExecution).where(AssistantExecution.user_id == user_id)
        )
        attempt = db.scalar(
            select(AssistantAttempt).where(AssistantAttempt.execution_id == execution.id)
        )
    assert execution.error_code == "attempt_persistence_failed"
    assert attempt.status == "sent"


@pytest.mark.parametrize(
    ("first_response", "expected_code"),
    [
        (
            {
                "id": "duplicate",
                "model": "claude-test",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "tool_use", "id": "same", "name": "market__freshness", "input": {}},
                    {"type": "tool_use", "id": "same", "name": "market__freshness", "input": {}},
                ],
                "usage": {},
            },
            "duplicate_or_missing_tool_call_id",
        ),
    ],
)
def test_terminal_tool_protocol_errors_are_specific_and_durable(
    client, monkeypatch, first_response, expected_code
):
    headers, user_id = _auth_with_anthropic(client, monkeypatch, email="protocol@example.com")
    provider = AnthropicProvider()

    async def fake_post(_url, _key, _payload):
        return first_response

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)

    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Inspect data", "provider": "anthropic"},
    )

    assert response.status_code == 503
    with SessionLocal() as db:
        execution = db.scalar(
            select(AssistantExecution).where(AssistantExecution.user_id == user_id)
        )
        attempts = list(
            db.scalars(
                select(AssistantAttempt).where(AssistantAttempt.execution_id == execution.id)
            )
        )
    assert execution.error_code == expected_code
    assert len(attempts) == 1 and attempts[0].status == "completed"


def test_output_truncation_and_provider_errors_remain_distinct(client, monkeypatch):
    headers, user_id = _auth_with_anthropic(client, monkeypatch, email="terminal@example.com")
    provider = AnthropicProvider()

    async def truncated(_url, _key, _payload):
        return {
            "id": "truncated",
            "model": "claude-test",
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": "Partial answer"}],
            "usage": {"input_tokens": 5, "output_tokens": 4096},
        }

    monkeypatch.setattr(provider, "_post", truncated)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Explain", "provider": "anthropic"},
    )
    assert response.status_code == 201
    assert response.json()["synthesis"]["generation"]["status"] == "truncated"

    with SessionLocal() as db:
        first = db.scalar(
            select(AssistantExecution)
            .where(AssistantExecution.user_id == user_id)
            .order_by(AssistantExecution.created_at.desc())
        )
        assert first.error_code == "output_truncated"

    async def provider_error(_url, _key, _payload):
        raise ProviderRequestError(
            provider="anthropic",
            status_code=429,
            error_type="rate_limit_error",
            provider_message="Rate limit exceeded for this account.",
            request_id="req-safe",
        )

    monkeypatch.setattr(provider, "_post", provider_error)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Explain again", "provider": "anthropic"},
    )
    assert response.status_code == 429
    assert response.json()["detail"]["error_detail"] == "Rate limit exceeded for this account."
    with SessionLocal() as db:
        failed = db.scalar(
            select(AssistantExecution)
            .where(AssistantExecution.user_id == user_id)
            .order_by(AssistantExecution.created_at.desc())
        )
        attempt = db.scalar(
            select(AssistantAttempt).where(AssistantAttempt.execution_id == failed.id)
        )
        metadata = json.loads(attempt.metadata_json)
    assert failed.error_code == "provider_http_429"
    assert metadata["http_status"] == 429
    assert metadata["provider_message"] == "Rate limit exceeded for this account."
    assert metadata["provider_request_id"] == "req-safe"
