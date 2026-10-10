"""Offline provider streaming contracts and fixtures."""

import json
import pytest
from app.ai.providers.base import (
    ProviderCallOptions,
    call_options,
    ContentBlock,
    ProviderTurn,
    ProviderTool,
)
from app.ai.providers.streaming import StreamAssembler
from app.ai.providers.zai import ZaiProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["zai", "openai", "openrouter"])
async def test_native_fragmented_openai_stream_never_emits_reasoning(provider):
    visible = []

    async def event(value):
        visible.append(value)

    token = call_options.set(ProviderCallOptions(on_event=event))
    try:
        assembler = StreamAssembler(provider)
        for delta in [
            {"reasoning_content": "private thought"},
            {"content": "Hello "},
            {"content": "world"},
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call1",
                        "function": {"name": "market__prices", "arguments": '{"sym'},
                    }
                ]
            },
            {"tool_calls": [{"index": 0, "function": {"arguments": 'bol":"OGDC"}'}}]},
        ]:
            await assembler.feed({"choices": [{"delta": delta}]})
        await assembler.feed(
            {
                "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            }
        )
        data = assembler.result()
        assert "".join(e.text for e in visible) == "Hello world"
        assert data["choices"][0]["message"]["reasoning_content"] == "private thought"
        assert json.loads(
            data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        ) == {"symbol": "OGDC"}
        assert data["usage"]["completion_tokens"] == 8
    finally:
        call_options.reset(token)


@pytest.mark.asyncio
async def test_invalid_anthropic_tool_json_retains_sanitized_stream_diagnostic(monkeypatch):
    import httpx
    from app.ai.providers.http_placeholders import AnthropicProvider
    from app.ai.providers.base import ProviderRequestError

    original = httpx.AsyncClient
    events = [
        {"type": "message_start", "message": {"id": "m"}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "t", "name": "fixture", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"key":"secret-fixture"'},
        },
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        {"type": "message_stop"},
    ]
    body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text=body,
            headers={"request-id": "invalid-json-fixture", "content-type": "text/event-stream"},
        )
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    with pytest.raises(ProviderRequestError) as failure:
        await AnthropicProvider().tool_chat_with_options(
            "secret-fixture",
            [ProviderTurn("user", [ContentBlock("text", text="fixture")])],
            [],
            options=ProviderCallOptions(stream=True),
        )
    assert failure.value.error_type == "invalid_stream_json"
    assert failure.value.request_id == "invalid-json-fixture"
    assert "secret-fixture" not in failure.value.response_payload["body"]
    assert "invalid_json" in failure.value.response_payload["body"]


@pytest.mark.asyncio
async def test_anthropic_empty_tool_argument_delta_preserves_empty_input():
    assembler = StreamAssembler("anthropic")
    for event in [
        {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 10}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "t",
                "name": "context__current",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": ""},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 9},
        },
        {"type": "message_stop"},
    ]:
        await assembler.feed(event)
    result = assembler.result()
    assert result["content"][0]["input"] == {}
    assert result["content"][0]["id"] == "t"
    assert result["stop_reason"] == "tool_use"


@pytest.mark.asyncio
async def test_anthropic_thinking_signature_and_fragmented_arguments():
    assembler = StreamAssembler("anthropic")
    events = [
        {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 10}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "secret"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "signature"},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "t", "name": "market__prices", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"symbol":'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '"LUCK"}'},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 9},
        },
        {"type": "message_stop"},
    ]
    for event in events:
        await assembler.feed(event)
    data = assembler.result()
    assert data["content"][0]["signature"] == "signature"
    assert data["content"][1]["input"] == {"symbol": "LUCK"}
    assert data["usage"] == {"input_tokens": 10, "output_tokens": 9}


@pytest.mark.asyncio
async def test_gemini_stream_preserves_id_and_arguments():
    assembler = StreamAssembler("gemini")
    for event in [
        {"event_type": "interaction.created", "interaction": {"id": "continuation"}},
        {
            "event_type": "step.start",
            "index": 0,
            "step": {
                "type": "function_call",
                "id": "call",
                "name": "market__freshness",
                "arguments": {},
            },
        },
        {
            "event_type": "step.delta",
            "index": 0,
            "delta": {"type": "arguments_delta", "arguments_delta": '{"limit":'},
        },
        {
            "event_type": "step.delta",
            "index": 0,
            "delta": {"type": "arguments_delta", "arguments_delta": "2}"},
        },
        {
            "event_type": "interaction.completed",
            "interaction": {"status": "requires_action", "usage": {"total_input_tokens": 42}},
        },
    ]:
        await assembler.feed(event)
    result = assembler.result()
    assert result["id"] == "continuation" and result["steps"][0]["arguments"] == {"limit": 2}


@pytest.mark.asyncio
async def test_native_http_sse_stream_and_zai_thinking_continuation(monkeypatch):
    import httpx
    from app.ai.providers import http_placeholders

    original_client = httpx.AsyncClient
    requests = []
    lines = [
        {"choices": [{"delta": {"reasoning_content": "opaque thought"}}]},
        {"choices": [{"delta": {"content": "Live "}}]},
        {"choices": [{"delta": {"content": "text"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": 20}},
    ]

    def handler(request):
        requests.append(json.loads(request.content))
        wire = "".join("data: " + json.dumps(line) + "\n\n" for line in lines) + "data: [DONE]\n\n"
        return httpx.Response(200, text=wire, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(
        http_placeholders.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    provider = ZaiProvider()
    tools = [ProviderTool("market.prices", "Prices", {"type": "object"})]
    previous = ProviderTurn(
        "assistant",
        [ContentBlock("tool_call", id="call", name="market.prices", arguments={})],
        {"reasoning_content": "previous opaque thought"},
    )
    turns = [
        ProviderTurn("user", [ContentBlock("text", text="Price?")]),
        previous,
        ProviderTurn(
            "user",
            [
                ContentBlock(
                    "tool_result", id="call", name="market.prices", result={"status": "missing"}
                )
            ],
        ),
    ]
    events = [
        event
        async for event in provider.stream_tool_chat(
            "offline-fixture-key",
            turns,
            tools,
            options=ProviderCallOptions(thinking=True, max_output_tokens=8192),
        )
    ]
    assert "".join(e.text for e in events if e.kind == "text_delta") == "Live text"
    assert requests[0]["stream"] is True and requests[0]["thinking"] == {
        "type": "enabled",
        "clear_thinking": False,
    }
    assert requests[0]["messages"][1]["reasoning_content"] == "previous opaque thought"
    assert requests[0]["messages"][2]["tool_call_id"] == "call"
    completed = next(e.result for e in events if e.kind == "completion")
    assert completed.turn.opaque["reasoning_content"] == "opaque thought"
    assert completed.input_tokens == 40 and completed.output_tokens == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["zai", "anthropic", "gemini"])
async def test_truncated_tool_arguments_are_incomplete_without_execution(provider):
    assembler = StreamAssembler(provider)
    if provider == "zai":
        await assembler.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "content": "Partial",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "t",
                                    "function": {"name": "read", "arguments": '{"x":'},
                                }
                            ],
                        },
                        "finish_reason": "length",
                    }
                ]
            }
        )
        result = assembler.result()
        assert result["choices"][0]["finish_reason"] == "length"
        assert not result["choices"][0]["message"].get("tool_calls")
    elif provider == "anthropic":
        await assembler.feed(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "t", "name": "read"},
            }
        )
        await assembler.feed(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"x":'},
            }
        )
        await assembler.feed({"type": "message_delta", "delta": {"stop_reason": "max_tokens"}})
        await assembler.feed({"type": "message_stop"})
        result = assembler.result()
        assert result["stop_reason"] == "max_tokens" and result["content"] == []
    else:
        await assembler.feed(
            {"event_type": "step.start", "index": 0, "step": {"type": "function_call", "id": "t"}}
        )
        await assembler.feed(
            {"event_type": "step.delta", "index": 0, "delta": {"arguments_delta": '{"x":'}}
        )
        result = assembler.result()
        assert result["status"] == "incomplete" and not result.get("steps")
