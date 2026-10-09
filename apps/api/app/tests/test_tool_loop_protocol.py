"""Offline tool loop protocol contracts and fixtures."""

import json
import pytest
from sqlalchemy import select
from app.ai.providers.base import ProviderRequestError
from app.ai.providers.http_placeholders import AnthropicProvider, GeminiProvider
from app.ai.tool_loop import ToolExecution
from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantAttempt, AssistantExecution
from app.services import assistant_diagnostics as diagnostics
from app.tools.registry import tool_result
from app.tests.support.assistant import _auth_with_anthropic, _auth_with_gemini


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
    assert (
        attempt_metadata[1]["estimated_input_tokens"]
        > attempt_metadata[0]["estimated_input_tokens"]
    )
    retained_request = json.loads(decrypt_secret(attempts[1].payload_encrypted))["messages"]
    assert '"tools"' in retained_request[0]["content"]
    assert "call-discover" in retained_request[0]["content"]
    assert execution.reserved_input_tokens > 0


def test_native_gemini_loop_continues_without_resending_prior_results(client, monkeypatch):
    headers, user_id = _auth_with_gemini(client, monkeypatch)
    provider = GeminiProvider()
    captured = []
    responses = [
        {
            "id": "gemini-loop-tools",
            "model": "gemini-3-flash-preview",
            "status": "requires_action",
            "steps": [
                {
                    "type": "function_call",
                    "status": "waiting",
                    "id": "freshness-call",
                    "name": "market__freshness",
                    "arguments": {},
                }
            ],
            "usage": {"total_input_tokens": 10, "total_output_tokens": 2},
        },
        {
            "id": "gemini-loop-final",
            "model": "gemini-3-flash-preview",
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "Freshness inspected."}],
                }
            ],
            "usage": {"total_input_tokens": 20, "total_output_tokens": 3},
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
    assert any(row["tool"] == "market.freshness" for row in response.json()["tool_trace"])
    assert captured[1]["previous_interaction_id"] == "gemini-loop-tools"
    assert len(captured[1]["input"]) == 2
    assert captured[1]["input"][1]["type"] == "user_input"
    function_response = captured[1]["input"][0]
    assert function_response["name"] == "market__freshness"
    assert function_response["call_id"] == "freshness-call"
    assert "Is market data fresh?" not in json.dumps(captured[1])
    assert {tool["type"] for tool in captured[0]["tools"]} == {"function"}
    assert response.json()["synthesis"]["web_grounding"]["status"] == "disabled"
    with SessionLocal() as db:
        execution = db.scalar(
            select(AssistantExecution)
            .where(AssistantExecution.user_id == user_id)
            .order_by(AssistantExecution.created_at.desc())
        )
        checkpoint = json.loads(decrypt_secret(execution.transcript_encrypted))
        diagnostic = diagnostics.inspect_execution(db, execution)
    assert checkpoint["provider_state"] == {
        "transport": "gemini_interactions",
        "continuation_id": "gemini-loop-final",
    }
    assert "freshness-call" in checkpoint["completed_tool_call_ids"]
    assert execution.reserved_input_tokens == 30
    assert diagnostic["usage"]["input_tokens"] == 30
    assert diagnostic["usage"]["model_calls"] == 2
    assert diagnostic["usage"]["transmitted_input_bytes"] > 0


def test_gemini_six_parallel_results_then_dependent_allocation_are_checkpointed(
    client, monkeypatch
):
    headers, user_id = _auth_with_gemini(client, monkeypatch, email="gemini-chain@example.com")
    provider = GeminiProvider()
    captured = []
    responses = [
        {
            "id": "parallel-interaction",
            "model": "gemini-3-flash-preview",
            "status": "requires_action",
            "steps": [
                {
                    "type": "function_call",
                    "id": f"fact-{index}",
                    "name": "market__freshness",
                    "arguments": {},
                }
                for index in range(6)
            ],
            "usage": {"total_input_tokens": 100, "total_output_tokens": 10},
        },
        {
            "id": "allocation-interaction",
            "model": "gemini-3-flash-preview",
            "status": "requires_action",
            "steps": [
                {
                    "type": "function_call",
                    "id": "allocation-call",
                    "name": "allocation__verify",
                    "arguments": {},
                }
            ],
            "usage": {"total_input_tokens": 120, "total_output_tokens": 8},
        },
        {
            "id": "final-interaction",
            "model": "gemini-3-flash-preview",
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "Analysis complete."}],
                }
            ],
            "usage": {"total_input_tokens": 130, "total_output_tokens": 5},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    async def fake_tool(_user_id, call):
        data = (
            {"accepted": False, "errors": ["ips_breach"]}
            if call.name == "allocation.verify"
            else {"sequence": call.id}
        )
        return ToolExecution(call, tool_result("ok", data=data), 1.0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    monkeypatch.setattr("app.ai.tool_loop._execute_tool", fake_tool)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Research then verify allocation", "provider": "gemini"},
    )

    assert response.status_code == 201, response.text
    assert [row["call_id"] for row in captured[1]["input"] if row["type"] == "function_result"] == [
        f"fact-{index}" for index in range(6)
    ]
    assert "Execution allowance (not evidence)" in captured[1]["system_instruction"]
    assert captured[1]["previous_interaction_id"] == "parallel-interaction"
    assert [row["call_id"] for row in captured[2]["input"] if row["type"] == "function_result"] == [
        "allocation-call"
    ]
    assert captured[2]["previous_interaction_id"] == "allocation-interaction"
    assert "fact-0" not in json.dumps(
        [row for row in captured[2]["input"] if row["type"] == "function_result"]
    )
    assert response.json()["synthesis"]["allocation_check"]["status"] == "rejected"
    with SessionLocal() as db:
        execution = db.scalar(
            select(AssistantExecution)
            .where(AssistantExecution.user_id == user_id)
            .order_by(AssistantExecution.created_at.desc())
        )
        checkpoint = json.loads(decrypt_secret(execution.transcript_encrypted))
    assert checkpoint["completed_tool_call_ids"] == [
        *[f"fact-{index}" for index in range(6)],
        "allocation-call",
    ]
    assert checkpoint["provider_state"]["continuation_id"] == "final-interaction"


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
            quota_violations=[
                {
                    "quotaId": "RequestsPerDayPerProjectPerModel",
                    "quotaDimensions": {"model": "claude-test"},
                    "quotaValue": "20",
                }
            ],
            retry_delay="60s",
        )

    monkeypatch.setattr(provider, "_post", provider_error)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Explain again", "provider": "anthropic"},
    )
    assert response.status_code == 429
    assert response.json()["detail"]["error_detail"] == (
        "Rate limit exceeded for this account. "
        "Quota: RequestsPerDayPerProjectPerModel (model=claude-test, limit=20) "
        "Retry after: 60s"
    )
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
    assert metadata["quota_violations"][0]["quotaValue"] == "20"
    assert metadata["retry_delay"] == "60s"
