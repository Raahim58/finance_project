"""Offline provider error redaction contracts and fixtures."""

import pytest
import httpx
from app.ai.providers.base import ProviderRequestError
from app.ai.providers.http_placeholders import AnthropicProvider, GeminiProvider


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


@pytest.mark.asyncio
async def test_provider_error_message_redacts_active_key(monkeypatch):
    provider = GeminiProvider()
    api_key = "secret-provider-key-123"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": f"Invalid request; x-goog-api-key={api_key}",
                        "status": "INVALID_ARGUMENT",
                    }
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    with pytest.raises(ProviderRequestError) as raised:
        await provider.chat(api_key, [{"role": "user", "content": "question"}])

    assert raised.value.error_type == "INVALID_ARGUMENT"
    assert raised.value.provider_message == "Invalid request; x-goog-api-key=[REDACTED]"
    assert api_key not in str(raised.value)


@pytest.mark.asyncio
async def test_gemini_quota_failure_preserves_safe_metric_and_retry_details(monkeypatch):
    provider = GeminiProvider()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return httpx.Response(
                429,
                json={
                    "error": {
                        "code": 429,
                        "message": "Quota exceeded",
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                "violations": [
                                    {
                                        "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                                        "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                        "quotaDimensions": {
                                            "model": "gemini-3-flash-preview",
                                            "location": "global",
                                        },
                                        "quotaValue": "20",
                                    }
                                ],
                            },
                            {
                                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                "retryDelay": "3600s",
                            },
                        ],
                    }
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    with pytest.raises(ProviderRequestError) as raised:
        await provider.chat("secret-provider-key", [{"role": "user", "content": "q"}])

    assert raised.value.error_type == "RESOURCE_EXHAUSTED"
    assert raised.value.retry_delay == "3600s"
    assert raised.value.quota_violations == [
        {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaValue": "20",
            "quotaDimensions": {
                "model": "gemini-3-flash-preview",
                "location": "global",
            },
        }
    ]
