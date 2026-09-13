import pytest
import httpx

from app.ai.providers.base import (
    ContentBlock,
    ProviderCallOptions,
    ProviderRequestError,
    ProviderTool,
    ProviderTurn,
)
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

    result = await provider.chat("secret", [{"role": "user", "content": "question"}], "test-model")

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
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"thought": True, "text": "private reasoning"},
                            {"text": '{"answer":"ok"}'},
                        ]
                    },
                }
            ],
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
        "responseJsonSchema": {"type": "object", "properties": {"answer": {"type": "string"}}},
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


@pytest.mark.asyncio
async def test_anthropic_native_tools_preserve_parallel_call_ids_and_results(monkeypatch):
    provider = AnthropicProvider()
    captured = []
    responses = [
        {
            "id": "msg-tools",
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": "call-1", "name": "market__freshness", "input": {}},
                {
                    "type": "tool_use",
                    "id": "call-2",
                    "name": "research__instruments",
                    "input": {"query": "Meezan"},
                },
            ],
            "usage": {"input_tokens": 10, "output_tokens": 4},
        },
        {
            "id": "msg-final",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Readable answer."}],
            "usage": {"input_tokens": 20, "output_tokens": 3},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    tools = [
        ProviderTool("market.freshness", "Freshness", {"type": "object", "properties": {}}),
        ProviderTool(
            "research.instruments",
            "Resolve instruments",
            {"type": "object", "properties": {"query": {"type": "string"}}},
        ),
    ]
    turns = [ProviderTurn("user", [ContentBlock("text", text="Inspect MEBL")])]
    first = await provider.tool_chat("secret", turns, tools, "claude-test")

    assert first.content == ""
    assert first.finish_reason == "tool_use"
    assert [(block.id, block.name) for block in first.turn.content] == [
        ("call-1", "market.freshness"),
        ("call-2", "research.instruments"),
    ]
    assert captured[0]["tools"][0]["input_schema"] == tools[0].input_schema

    result_turn = ProviderTurn(
        "user",
        [
            ContentBlock(
                "tool_result", id="call-1", name="market.freshness", result={"status": "ok"}
            ),
            ContentBlock(
                "tool_result",
                id="call-2",
                name="research.instruments",
                result={"status": "missing"},
            ),
        ],
    )
    final = await provider.tool_chat(
        "secret", [*turns, first.turn, result_turn], tools, "claude-test"
    )

    returned = captured[1]["messages"][-1]["content"]
    assert [block["tool_use_id"] for block in returned] == ["call-1", "call-2"]
    assert final.content == "Readable answer."


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-2.5-flash-lite"])
async def test_gemini_native_tools_preserve_signature_and_function_response(model, monkeypatch):
    provider = GeminiProvider()
    captured = []
    signed_part = {
        "functionCall": {"name": "market__freshness", "args": {}},
        "thoughtSignature": "opaque-signature",
    }
    responses = [
        {
            "responseId": "gemini-tools",
            "modelVersion": model,
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"role": "model", "parts": [signed_part]},
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
        },
        {
            "responseId": "gemini-final",
            "modelVersion": model,
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"role": "model", "parts": [{"text": "Final text."}]},
                }
            ],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 3},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    tools = [ProviderTool("market.freshness", "Freshness", {"type": "object"})]
    turns = [ProviderTurn("user", [ContentBlock("text", text="Freshness?")])]
    first = await provider.tool_chat("secret", turns, tools, model)
    call = first.turn.content[0]
    result = ProviderTurn(
        "user",
        [
            ContentBlock(
                "tool_result",
                id=call.id,
                name=call.name,
                result={"status": "ok"},
                opaque={"include_id": False},
            )
        ],
    )
    final = await provider.tool_chat("secret", [*turns, first.turn, result], tools, model)

    assert first.content == ""
    assert captured[1]["contents"][1]["parts"][0] == signed_part
    function_response = captured[1]["contents"][2]["parts"][0]["functionResponse"]
    assert function_response["name"] == "market__freshness"
    assert "id" not in function_response
    assert final.content == "Final text."
