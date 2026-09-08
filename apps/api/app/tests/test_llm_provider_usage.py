import pytest
import httpx

from app.ai.providers.base import ProviderCallOptions, ProviderRequestError
from app.ai.providers.http_placeholders import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "response", "expected"),
    [
        (
            OpenAIProvider(),
            {
                "model": "gpt-test",
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 101, "completion_tokens": 29},
            },
            (101, 29),
        ),
        (
            AnthropicProvider(),
            {
                "model": "claude-test",
                "content": [{"type": "text", "text": "answer"}],
                "usage": {"input_tokens": 202, "output_tokens": 41},
            },
            (202, 41),
        ),
        (
            GeminiProvider(),
            {
                "modelVersion": "gemini-test",
                "candidates": [{"content": {"parts": [{"text": "answer"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 303,
                    "candidatesTokenCount": 53,
                },
            },
            (303, 53),
        ),
    ],
)
async def test_provider_usage_is_preserved(provider, response, expected, monkeypatch):
    async def fake_post(*_args, **_kwargs):
        return response

    monkeypatch.setattr(provider, "_post", fake_post)

    result = await provider.chat(
        "secret", [{"role": "user", "content": "question"}], "test-model"
    )

    assert (result.input_tokens, result.output_tokens) == expected


@pytest.mark.asyncio
async def test_anthropic_sonnet_5_request_omits_sampling_parameters(monkeypatch):
    provider = AnthropicProvider()
    captured_payload = None

    async def fake_post(_url, _api_key, payload):
        nonlocal captured_payload
        captured_payload = payload
        return {
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": "answer"}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }

    monkeypatch.setattr(provider, "_post", fake_post)

    await provider.chat(
        "secret",
        [{"role": "user", "content": "question"}],
        "claude-sonnet-5",
    )

    assert captured_payload is not None
    assert "temperature" not in captured_payload
    assert "top_p" not in captured_payload
    assert "top_k" not in captured_payload


@pytest.mark.asyncio
async def test_gemini_uses_native_schema_and_preserves_usage_breakdown(monkeypatch):
    provider = GeminiProvider()
    captured_payload = None

    async def fake_post(_url, _api_key, payload):
        nonlocal captured_payload
        captured_payload = payload
        return {
            "responseId": "gemini-request",
            "modelVersion": "gemini-test",
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [
                    {"thought": True, "text": "private reasoning"},
                    {"text": '{"answer":"ok"}'},
                ]},
            }],
            "usageMetadata": {
                "promptTokenCount": 30,
                "candidatesTokenCount": 5,
                "cachedContentTokenCount": 7,
                "thoughtsTokenCount": 11,
            },
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    result = await provider.chat_with_options(
        "secret",
        [{"role": "user", "content": "question"}],
        "gemini-test",
        options=ProviderCallOptions(
            response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
            max_output_tokens=2048,
        ),
    )

    assert captured_payload["generationConfig"] == {
        "temperature": 0,
        "maxOutputTokens": 2048,
        "responseMimeType": "application/json",
        "responseJsonSchema": {
            "type": "object", "properties": {"answer": {"type": "string"}}
        },
    }
    assert result.content == '{"answer":"ok"}'
    assert (result.cache_read_tokens, result.reasoning_tokens) == (7, 11)
    assert (result.finish_reason, result.request_id) == ("STOP", "gemini-request")


@pytest.mark.asyncio
async def test_anthropic_preserves_cache_and_finish_metadata(monkeypatch):
    provider = AnthropicProvider()

    async def fake_post(_url, _api_key, _payload):
        return {
            "id": "anthropic-request",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "answer"}],
            "usage": {
                "input_tokens": 20,
                "output_tokens": 4,
                "cache_read_input_tokens": 6,
                "cache_creation_input_tokens": 8,
            },
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    result = await provider.chat("secret", [{"role": "user", "content": "question"}])

    assert (result.cache_read_tokens, result.cache_write_tokens) == (6, 8)
    assert (result.finish_reason, result.request_id) == ("end_turn", "anthropic-request")


@pytest.mark.asyncio
async def test_anthropic_error_preserves_safe_provider_diagnostics(monkeypatch):
    provider = AnthropicProvider()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return httpx.Response(
                400,
                headers={"request-id": "req_123"},
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "temperature is not supported for this model",
                    },
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    with pytest.raises(ProviderRequestError) as raised:
        await provider.chat(
            "secret",
            [{"role": "user", "content": "question"}],
            "claude-sonnet-5",
        )

    assert raised.value.status_code == 400
    assert raised.value.error_type == "invalid_request_error"
    assert raised.value.provider_message is None
    assert raised.value.request_id == "req_123"
    assert "secret" not in str(raised.value)
