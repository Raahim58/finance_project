import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from app.ai import token_counting as counting
from app.ai.providers.base import ProviderCallOptions, call_options
from app.ai.providers.http_placeholders import AnthropicProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("estimated,remaining,expected_calls", [
    (10000, 180000, 0), (38400, 180000, 1), (49217, 180000, 1), (10000, 12000, 1)
])
async def test_anthropic_counts_only_near_per_call_or_cumulative_boundary(monkeypatch, estimated, remaining, expected_calls):
    calls = []
    async def provider_count(key, payload):
        calls.append(payload)
        return 32640
    provider = SimpleNamespace(name="anthropic", count_input_tokens=provider_count)
    monkeypatch.setattr(counting, "local_input_count", lambda *_: (estimated, "local"))
    count, metadata = await counting.preflight_count(provider, "not-a-real-key", {"model": "claude-test"},
        input_limit=48000, remaining_input=remaining)
    assert len(calls) == expected_calls
    assert count == (32640 if expected_calls else estimated)
    if expected_calls:
        assert metadata["provider_counted_input_tokens"] == 32640


@pytest.mark.asyncio
async def test_count_failure_never_silently_bypasses_limit(monkeypatch):
    async def failed(*_args):
        raise TimeoutError()
    monkeypatch.setattr(counting, "local_input_count", lambda *_: (49217, "local"))
    count, metadata = await counting.preflight_count(SimpleNamespace(name="anthropic", count_input_tokens=failed),
        "not-a-real-key", {}, input_limit=48000, remaining_input=180000)
    assert count == 49217
    assert metadata["input_count_error"] == "TimeoutError"


@pytest.mark.asyncio
async def test_count_endpoint_preserves_tools_and_thinking_but_excludes_transport(monkeypatch, token_count_transport):
    captured = []
    real_client = httpx.AsyncClient
    def handle(request):
        captured.append(request)
        return httpx.Response(200, json={"input_tokens": 32640})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(**kw, transport=httpx.MockTransport(handle)))
    body = {"model": "claude-test", "system": "instructions", "messages": [{"role": "user", "content": "question"}],
            "tools": [{"name": "tool", "input_schema": {"type": "object"}}],
            "thinking": {"type": "adaptive"}, "stream": True, "max_tokens": 8192}
    assert await AnthropicProvider().count_input_tokens("not-a-real-key", body) == 32640
    assert captured[0].url.path == "/v1/messages/count_tokens"
    transmitted = json.loads(captured[0].content)
    assert transmitted == {k: v for k, v in body.items() if k not in {"stream", "max_tokens"}}


def test_glm_counts_rendered_input_without_transport_or_double_encoded_results(monkeypatch):
    captured = []
    class Template:
        def render(self, **kw):
            captured.append(kw)
            return "rendered input"
    class Tokenizer:
        def encode(self, text, **kw):
            assert text == "rendered input"
            return SimpleNamespace(ids=list(range(100)))
    monkeypatch.setattr(counting, "local_assets", lambda: (Tokenizer(), Template()))
    payload = {"model": "glm-4.5-flash", "max_tokens": 8192, "stream": True,
               "messages": [{"role": "assistant", "content": "", "reasoning_content": "required reasoning",
                             "tool_calls": [{"function": {"name": "tool", "arguments": '{"limit":1}'}}]},
                            {"role": "tool", "content": '{"price":446.61}'}], "tools": []}
    original = copy.deepcopy(payload)
    assert counting.local_input_count("zai", payload) == (105, "glm45_local_template_plus_5pct")
    assert captured[0]["messages"][0]["tool_calls"][0]["function"]["arguments"] == {"limit": 1}
    assert captured[0]["messages"][0]["reasoning_content"] == "required reasoning"
    assert captured[0]["messages"][1]["content"] == '{"price":446.61}'
    assert payload == original


def test_unknown_model_and_missing_assets_are_explicit_estimates(monkeypatch):
    def missing():
        raise FileNotFoundError()
    monkeypatch.setattr(counting, "local_assets", missing)
    assert counting.local_input_count("zai", {"model": "glm-4.5-flash"})[1] == "local_tokenizer_unavailable"
    assert counting.local_input_count("zai", {"model": "glm-4.7-flash"})[1] == "legacy_conservative_estimate"


@pytest.mark.asyncio
async def test_http_provider_awaits_guard_before_generation(monkeypatch):
    seen = []
    provider = AnthropicProvider()
    async def guard(payload):
        seen.append("count")
    async def post(*_args):
        seen.append("generate")
        return {}
    monkeypatch.setattr(provider, "_post", post)
    token = call_options.set(ProviderCallOptions(request_guard=guard))
    try:
        await provider._send(provider.chat_url, "not-a-real-key", {})
    finally:
        call_options.reset(token)
    assert seen == ["count", "generate"]


@pytest.mark.parametrize("provider_count", [32640, 49000])
def test_assistant_uses_provider_count_to_accept_or_block_and_reconciles_usage(client, monkeypatch, provider_count):
    from sqlalchemy import select
    from app.tests.support.assistant import _auth_with_anthropic
    from app.ai import tool_loop
    from app.db.session import SessionLocal
    from app.models.assistant_execution import AssistantExecution, AssistantAttempt
    headers, user_id = _auth_with_anthropic(client, monkeypatch, email="token-count@example.com")
    provider = AnthropicProvider()
    counts, generations = [], []
    async def count(key, payload):
        counts.append(payload)
        return provider_count
    async def post(*args):
        generations.append(args)
        return {"model": "claude-test", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Available evidence is limited."}],
                "usage": {"input_tokens": 32000, "output_tokens": 8}}
    monkeypatch.setattr(counting, "local_input_count", lambda *_: (49217, "local"))
    monkeypatch.setattr(provider, "count_input_tokens", count)
    monkeypatch.setattr(provider, "_post", post)
    monkeypatch.setattr(tool_loop, "get_provider", lambda _: provider)
    response = client.post("/assistant/messages", headers=headers,
        json={"question": "Explain available company evidence", "provider": "anthropic"})
    if provider_count > 48000:
        assert len(counts) == 1
        assert not generations
        assert response.json()["synthesis"]["generation"]["error_code"] == "question_budget_exhausted"
        return
    assert response.status_code == 201, response.text
    assert len(counts) == len(generations) == 1
    with SessionLocal() as db:
        execution = db.scalar(select(AssistantExecution).where(AssistantExecution.user_id == user_id))
        attempt = db.scalar(select(AssistantAttempt).where(AssistantAttempt.execution_id == execution.id))
        metadata = json.loads(attempt.metadata_json)
        assert metadata["local_estimated_input_tokens"] == 49217
        assert metadata["estimated_input_tokens"] == 32640
        assert metadata["accounted_input_tokens"] == execution.reserved_input_tokens == 32000
        assert json.loads(execution.accounting_json)["calls"] == 1
