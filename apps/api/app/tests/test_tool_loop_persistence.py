"""Offline tool loop persistence contracts and fixtures."""

import json
import asyncio
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.ai.providers.base import ContentBlock, ProviderTurn
from app.ai.providers.http_placeholders import AnthropicProvider
from app.ai.tool_loop import (
    AssistantTerminalError,
    ToolExecution,
    _initial_checkpoint,
    run_tool_loop,
)
from app.core.security import decrypt_secret, encrypt_secret
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantAttempt, AssistantExecution
from app.models.user import User
from app.models.workstation import AssistantMessage
from app.schemas.assistant import AssistantMessageCreate
from app.services import assistant_diagnostics as diagnostics
from app.services.assistant_execution import accept
from app.tools.registry import tool_result
from app.tests.support.assistant import _mock_market, _auth_with_anthropic
from app.tests.support.assistant import anthropic_text


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
                [
                    ContentBlock(
                        "tool_call", id="restart-tool", name="market.freshness", arguments={}
                    )
                ],
            ).to_dict()
        )
        db.get(AssistantExecution, execution_id).transcript_encrypted = encrypt_secret(
            json.dumps(checkpoint, separators=(",", ":"))
        )

    provider = AnthropicProvider()
    captured = []

    async def final_after_resume(_url, _key, request):
        captured.append(request)
        return anthropic_text("Freshness checked after restart.", identifier="resumed-final")

    monkeypatch.setattr(provider, "_post", final_after_resume)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    token = diagnostics.execution_id.set(execution_id)
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            result = asyncio.run(run_tool_loop(db, user, payload, conversation_id, accepted=True))
    finally:
        diagnostics.execution_id.reset(token)

    assert result["synthesis"]["generation"]["error_code"] == "citation_missing"
    assert "investment conclusion was rejected" in result["answer"]
    assert len(captured) == 1
    result_blocks = captured[0]["messages"][-1]["content"]
    assert result_blocks[0]["type"] == "tool_result"
    assert result_blocks[0]["tool_use_id"] == "restart-tool"
    with SessionLocal() as db:
        checkpoint = json.loads(
            decrypt_secret(db.get(AssistantExecution, execution_id).transcript_encrypted)
        )
    assert checkpoint["completed_tool_call_ids"] == ["restart-tool"]


def test_final_message_persistence_retries_once_without_duplicate(client, monkeypatch):
    headers, user_id = _auth_with_anthropic(client, monkeypatch, email="response-retry@example.com")
    provider = AnthropicProvider()

    async def final_response(_url, _key, _request):
        return anthropic_text("Persisted after retry.", identifier="response-persistence-retry")

    original_add = Session.add
    failures = 0

    def fail_first_message(self, instance, *args, **kwargs):
        nonlocal failures
        if (
            isinstance(instance, AssistantMessage)
            and instance.role == "assistant"
            and failures == 0
        ):
            failures += 1
            raise RuntimeError("simulated transient message persistence failure")
        return original_add(self, instance, *args, **kwargs)

    monkeypatch.setattr(provider, "_post", final_response)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    monkeypatch.setattr(Session, "add", fail_first_message)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Persist the final answer", "provider": "anthropic"},
    )

    assert response.status_code == 201
    assert failures == 1
    with SessionLocal() as db:
        execution = db.scalar(
            select(AssistantExecution).where(AssistantExecution.user_id == user_id)
        )
        messages = list(
            db.scalars(
                select(AssistantMessage).where(
                    AssistantMessage.conversation_id == execution.conversation_id,
                    AssistantMessage.role == "assistant",
                )
            )
        )
        assert execution.status == "synthesis_unavailable"
    assert len(messages) == 1


def test_compact_allocation_recovery_and_latest_failed_attempt():
    from app.ai.providers.base import ContentBlock
    from app.ai.tool_loop import _render_allocation, _result_blocks

    checkpoint = {"evidence": {}, "next_evidence": 1, "tool_trace": []}
    accepted = tool_result(
        "ok",
        {
            "accepted": True,
            "verification_id": "check-1",
            "legs": [
                {
                    "instrument_id": "m",
                    "symbol": "MEBL",
                    "quantity": "2",
                    "gross_amount": "200",
                    "side": "buy",
                    "required_statement": "Buy 2 shares.",
                }
            ],
            "current_weights": {"m": 0.4, "h": 0.5, "CASH": 0.1},
            "proposed_weights": {"m": 0.45, "h": 0.5, "CASH": 0.05},
            "evidence_versions": {"m": {"symbol": "MEBL"}, "h": {"symbol": "HBL"}},
        },
    )
    # Historical compact checkpoints must also recover locally.
    checkpoint["allocation_check"] = accepted["data"]
    text, result = _render_allocation(checkpoint)
    assert "Buy 2 shares" in text
    assert [row["symbol"] for row in result["rows"]] == ["MEBL", "HBL", "CASH"]
    call = ContentBlock("tool_call", id="verify-2", name="allocation.verify", arguments={})
    blocks = _result_blocks(
        checkpoint,
        ToolExecution(call, tool_result("unavailable", error={"code": "tool_timeout"}), 1),
    )
    assert blocks[0].result["status"] == "unavailable"
    _, result = _render_allocation(checkpoint)
    assert result["status"] == "unavailable"
    assert result["verification_id"] is None
    assert result["rows"] == []


def test_safe_internal_error_location_excludes_exception_payload():
    from app.services.assistant_diagnostics import safe_error_metadata

    try:
        try:
            raise TypeError("secret private financial payload")
        except TypeError as exc:
            raise AssistantTerminalError("response_serialization_failed") from exc
    except AssistantTerminalError as exc:
        metadata = safe_error_metadata(exc)
    assert metadata["error_code"] == "response_serialization_failed"
    assert metadata["exception_type"] == "TypeError"
    assert (
        metadata["exception_location"]["function"]
        == "test_safe_internal_error_location_excludes_exception_payload"
    )
    assert "secret" not in json.dumps(metadata)


def test_accepted_allocation_delivery_and_local_recovery_do_not_repeat_provider(
    client, monkeypatch
):
    import app.ai.tool_loop as loop
    from app.services.assistant_execution import execute, queue_finalization_recovery

    headers, user_id = _auth_with_anthropic(
        client, monkeypatch, email="accepted-recovery@example.com"
    )
    instrument = next(row for row in _mock_market(monkeypatch) if row.symbol == "MEBL")
    portfolio_id = client.post("/portfolios", headers=headers, json={"name": "Allocation"}).json()[
        "id"
    ]
    assert (
        client.post(
            f"/portfolios/{portfolio_id}/holdings",
            headers=headers,
            json={"symbol": "MEBL", "quantity": "1", "average_cost": "100"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/portfolios/{portfolio_id}/transactions",
            headers=headers,
            json={
                "symbol": "CASH",
                "transaction_type": "deposit",
                "amount": "10000",
                "transaction_date": "2026-08-07",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/portfolios/{portfolio_id}/ips/confirm",
            headers=headers,
            json={"constraints": {}, "horizon_years": 5},
        ).status_code
        == 201
    )
    provider = AnthropicProvider()
    captured = []
    responses = [
        {
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "summary",
                    "name": "portfolio__summary",
                    "input": {"portfolio_id": portfolio_id},
                },
                {
                    "type": "tool_use",
                    "id": "ips",
                    "name": "ips__compliance",
                    "input": {"portfolio_id": portfolio_id},
                },
            ],
            "usage": {},
        },
        {
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "verify",
                    "name": "allocation__verify",
                    "input": {
                        "portfolio_id": portfolio_id,
                        "allowed_instrument_ids": [instrument.id],
                        "proposal": {
                            "legs": [
                                {
                                    "instrument_id": instrument.id,
                                    "side": "buy",
                                    "gross_amount": "1000",
                                }
                            ]
                        },
                    },
                },
            ],
            "usage": {},
        },
        {
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Calculation [[E3]]."}],
            "usage": {},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr(loop, "get_provider", lambda _name: provider)
    persist = loop._persist_final_message

    def failed_persist(*_args):
        raise AssistantTerminalError("response_persistence_failed")

    monkeypatch.setattr(loop, "_persist_final_message", failed_persist)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Recommend and verify allocation",
            "portfolio_id": portfolio_id,
            "provider": "anthropic",
        },
    )
    assert response.status_code == 503
    assert len(captured) == 3
    with SessionLocal() as db:
        row = db.scalar(select(AssistantExecution).where(AssistantExecution.user_id == user_id))
        identifier = row.id
        checkpoint = json.loads(decrypt_secret(row.transcript_encrypted))
        assert (
            checkpoint["reserved_tool_calls"] == 8
        )  # portfolio-wide first pass (summary, ips, quant, per-holding risk) plus three model tools
        assert "cost units" not in json.dumps(captured)
        assert checkpoint["allocation_check"]["accepted"] is True
        assert "Execution allowance (not evidence)" in json.dumps(captured[1])
        from datetime import timedelta
        from app.models.assistant_execution import now

        row.started_at = now() - timedelta(seconds=1000)
        db.commit()
        queue_finalization_recovery(db, user_id, identifier)
    monkeypatch.setattr(loop, "_persist_final_message", persist)
    asyncio.run(execute(identifier))
    with SessionLocal() as db:
        row = db.get(AssistantExecution, identifier)
        assert row.status == "completed", row.error_code
        result = json.loads(row.response_json)
        assert result["synthesis"]["allocation_check"]["status"] == "accepted"
        assert {item["symbol"] for item in result["synthesis"]["allocation_check"]["rows"]} == {
            "MEBL",
            "CASH",
        }
        assert result["synthesis"]["token_usage"]["model_calls"] == 3
    assert len(captured) == 3


@pytest.mark.parametrize(
    "failure_point,question",
    [
        ("checkpoint", "Persist this"),
        ("response", "Persist the final answer"),
        ("attempt", "Record the attempt"),
    ],
)
def test_persistence_failures_keep_distinct_stage_and_attempt_state(
    client, monkeypatch, failure_point, question
):
    from app.ai import tool_loop

    codes = {
        "checkpoint": "checkpoint_persistence_failed",
        "response": "response_persistence_failed",
        "attempt": "attempt_persistence_failed",
    }
    headers, user_id = _auth_with_anthropic(
        client, monkeypatch, email=f"{failure_point}-failure@example.com"
    )
    provider = AnthropicProvider()

    async def final_response(_url, _key, _request):
        return anthropic_text(
            "Provider completed.", identifier=f"{failure_point}-persistence-final"
        )

    if failure_point == "checkpoint":
        original_save = tool_loop._save_checkpoint

        def fail_after_attempt(identifier, checkpoint):
            if checkpoint.get("provider_turn_complete"):
                raise AssistantTerminalError(codes[failure_point])
            return original_save(identifier, checkpoint)

        monkeypatch.setattr(tool_loop, "_save_checkpoint", fail_after_attempt)
    elif failure_point == "response":
        original_add = Session.add

        def fail_message(self, instance, *args, **kwargs):
            if isinstance(instance, AssistantMessage) and instance.role == "assistant":
                raise RuntimeError("simulated message persistence failure")
            return original_add(self, instance, *args, **kwargs)

        monkeypatch.setattr(Session, "add", fail_message)
    else:

        def fail_attempt_outcome(*_args, **_kwargs):
            raise RuntimeError("simulated attempt outcome persistence failure")

        monkeypatch.setattr(diagnostics, "finish_attempt", fail_attempt_outcome)

    monkeypatch.setattr(provider, "_post", final_response)
    monkeypatch.setattr(tool_loop, "get_provider", lambda _name: provider)
    response = client.post(
        "/assistant/messages", headers=headers, json={"question": question, "provider": "anthropic"}
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
    assert execution.error_code == codes[failure_point]
    assert len(attempts) == 1
    assert attempts[0].status == ("sent" if failure_point == "attempt" else "completed")
