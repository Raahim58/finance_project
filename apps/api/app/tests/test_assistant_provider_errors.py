"""Offline assistant provider errors contracts and fixtures."""

import json
import pytest
from sqlalchemy import select
from app.ai.providers.base import ProviderCallOptions, ContentBlock, ProviderTurn
from app.ai.providers.streaming import StreamAssembler
from app.ai.providers.zai import ZaiProvider
from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.models.workstation import AssistantMessage
from app.models.assistant_execution import AssistantExecution
from app.services import assistant_execution, assistant_diagnostics
from app.tests.support.assistant import accepted


@pytest.mark.asyncio
async def test_native_http_error_keeps_business_code_without_key(monkeypatch):
    import httpx
    from app.ai.providers.base import ProviderRequestError

    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            429,
            json={
                "error": {"code": "1305", "message": "Overloaded; key=secret-fixture-credential"}
            },
            headers={"x-request-id": "fixture-request"},
        )
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    provider = ZaiProvider()
    with pytest.raises(ProviderRequestError) as failure:
        await provider.tool_chat_with_options(
            "secret-fixture-credential",
            [ProviderTurn("user", [ContentBlock("text", text="test")])],
            [],
            options=ProviderCallOptions(thinking=True, stream=True),
        )
    assert failure.value.error_type == "1305" and failure.value.status_code == 429
    assert failure.value.request_id == "fixture-request"
    assert "secret-fixture-credential" not in str(failure.value)


@pytest.mark.asyncio
async def test_zai_overload_is_persisted_with_sanitized_cause(client, monkeypatch):
    from app.ai.tool_loop import _provider_turn, AssistantTerminalError
    from app.ai.providers.base import ProviderRequestError

    _, _, identifier, _ = accepted(client)
    provider = ZaiProvider()

    async def rejected(*args, **kwargs):
        raise ProviderRequestError(
            provider="zai",
            status_code=429,
            error_type="1305",
            provider_message="Temporarily overloaded",
        )

    monkeypatch.setattr(provider, "_post", rejected)
    token = assistant_diagnostics.execution_id.set(identifier)
    try:
        with pytest.raises(AssistantTerminalError) as failure:
            await _provider_turn(
                provider,
                "offline-credential-fixture",
                None,
                [ProviderTurn("user", [ContentBlock("text", text="test")])],
                [],
            )
        assert failure.value.code == "provider_overloaded"
    finally:
        assistant_diagnostics.execution_id.reset(token)

    async def fail_execution(*args, **kwargs):
        raise AssistantTerminalError("provider_overloaded")

    monkeypatch.setattr("app.ai.orchestrator.run_assistant", fail_execution)
    await assistant_execution.execute(identifier)
    with SessionLocal() as db:
        message = db.scalar(
            select(AssistantMessage).where(
                AssistantMessage.execution_id == identifier, AssistantMessage.role == "assistant"
            )
        )
        assert (
            message.outcome == "failed"
            and json.loads(message.evidence_json)["error_code"] == "provider_overloaded"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
async def test_entire_provider_error_body_is_encrypted_and_not_exported(
    client, monkeypatch, stream
):
    import httpx
    from app.ai.providers.base import ProviderRequestError
    from app.models.assistant_execution import AssistantAttempt

    _, _, identifier, _ = accepted(client)
    original = httpx.AsyncClient
    body = {
        "error": {
            "code": "1305",
            "message": "Temporarily overloaded",
            "details": {
                "diagnostic": "private provider detail",
                "echoed_key": "secret-fixture-credential",
            },
        }
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            429,
            json=body,
            headers={
                "x-request-id": "full-payload-fixture",
                "retry-after": "5",
                "set-cookie": "exclude-this",
            },
        )
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    provider = ZaiProvider()
    token = assistant_diagnostics.execution_id.set(identifier)
    try:
        attempt = assistant_diagnostics.begin_attempt(
            "tool_loop_turn", "zai", "glm-4.7-flash", [{"role": "user", "content": "fixture"}], 20
        )
        with pytest.raises(ProviderRequestError) as failure:
            await provider.tool_chat_with_options(
                "secret-fixture-credential",
                [ProviderTurn("user", [ContentBlock("text", text="test")])],
                [],
                options=ProviderCallOptions(stream=stream),
            )
        assistant_diagnostics.finish_attempt(attempt, error=failure.value, latency_ms=1)
        with SessionLocal() as db:
            saved = db.get(AssistantAttempt, attempt)
            payload = json.loads(decrypt_secret(saved.payload_encrypted))["error_response"]
            captured = json.loads(payload["body"])
            assert captured["error"]["code"] == "1305"
            assert captured["error"]["details"]["diagnostic"] == "private provider detail"
            assert captured["error"]["details"]["echoed_key"] == "[REDACTED]"
            assert (
                payload["headers"]["retry-after"] == "5" and "set-cookie" not in payload["headers"]
            )
            assert not payload["body_truncated"]
            assert "private provider detail" not in saved.payload_encrypted
            export = json.dumps(
                assistant_diagnostics.inspect_execution(db, db.get(AssistantExecution, identifier)),
                default=str,
            )
            assert (
                "private provider detail" not in export
                and "secret-fixture-credential" not in export
            )
            assert "provider_error_payload_retained" in export
    finally:
        assistant_diagnostics.execution_id.reset(token)


@pytest.mark.asyncio
async def test_inference_stream_error_preserves_body_and_hides_credentials():
    from app.ai.providers.base import ProviderRequestError

    assembler = StreamAssembler("zai", "fixture-api-key")
    with pytest.raises(ProviderRequestError) as failure:
        await assembler.feed(
            {
                "type": "error",
                "error": {
                    "code": "1305",
                    "message": "Overloaded",
                    "opaque_detail": "fixture-api-key",
                },
            }
        )
    assert failure.value.status_code == 200 and failure.value.error_type == "1305"
    assert (
        json.loads(failure.value.response_payload["body"])["error"]["opaque_detail"] == "[REDACTED]"
    )
