import pytest
import httpx

from app.ai.providers.base import ProviderRequestError
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
    assert raised.value.provider_message == "temperature is not supported for this model"
    assert raised.value.request_id == "req_123"
    assert "secret" not in str(raised.value)
