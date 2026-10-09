"""Offline provider tool protocol contracts and fixtures."""

from datetime import date
from decimal import Decimal
import pytest
from app.ai.providers.base import ContentBlock, ProviderCallOptions, ProviderTool, ProviderTurn
from app.ai.providers.http_placeholders import AnthropicProvider, GeminiProvider


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
async def test_gemini_interactions_continue_with_only_new_function_results(model, monkeypatch):
    provider = GeminiProvider()
    captured = []
    responses = [
        {
            "id": "gemini-tools",
            "model": model,
            "status": "requires_action",
            "steps": [
                {
                    "type": "function_call",
                    "status": "waiting",
                    "id": "call-1",
                    "name": "market__freshness",
                    "arguments": {},
                }
            ],
            "usage": {
                "total_input_tokens": 10,
                "total_output_tokens": 2,
                "total_cached_tokens": 3,
                "total_thought_tokens": 1,
            },
        },
        {
            "id": "gemini-final",
            "model": model,
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "Final text."}],
                }
            ],
            "usage": {"total_input_tokens": 20, "total_output_tokens": 3},
        },
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    schema = {
        "$defs": {
            "Scope": {
                "type": "object",
                "properties": {"portfolio_id": {"type": "string"}},
            }
        },
        "type": "object",
        "properties": {"scope": {"$ref": "#/$defs/Scope"}},
    }
    tools = [ProviderTool("market.freshness", "Freshness", schema)]
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
                result={
                    "status": "ok",
                    "price": Decimal("123.45"),
                    "as_of": date(2026, 9, 13),
                },
                opaque={"include_id": False},
            )
        ],
    )
    final = await provider.tool_chat_with_options(
        "secret",
        [*turns, first.turn, result],
        tools,
        model,
        options=ProviderCallOptions(continuation_id=first.continuation_id),
    )

    assert first.content == ""
    assert first.continuation_id == "gemini-tools"
    declaration = captured[0]["tools"][0]
    assert declaration["parameters"] == schema
    assert not any(tool["type"] == "google_search" for tool in captured[0]["tools"])
    assert captured[1]["previous_interaction_id"] == "gemini-tools"
    function_response = captured[1]["input"][0]
    assert function_response["type"] == "function_result"
    assert function_response["name"] == "market__freshness"
    assert function_response["call_id"] == "call-1"
    serialized_result = function_response["result"][0]["text"]
    assert '"price":"123.45"' in serialized_result
    assert '"as_of":"2026-09-13"' in serialized_result
    assert "Freshness?" not in str(captured[1])
    assert final.content == "Final text."


@pytest.mark.asyncio
async def test_gemini_3_interactions_do_not_enable_web_tools(monkeypatch):
    provider = GeminiProvider()
    captured = []

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return {
            "id": "web-answer",
            "model": "gemini-3-flash-preview",
            "status": "completed",
            "steps": [
                {"type": "google_search_call", "id": "search-1", "status": "completed"},
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "text",
                            "text": "Verified event.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.com/event",
                                    "title": "Event source",
                                    "start_index": 0,
                                    "end_index": 14,
                                }
                            ],
                        }
                    ],
                },
            ],
            "usage": {"total_input_tokens": 12, "total_output_tokens": 4},
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    result = await provider.tool_chat(
        "secret",
        [ProviderTurn("user", [ContentBlock("text", text="Verify the event")])],
        [ProviderTool("research.events", "Events", {"type": "object"})],
        "gemini-3-flash-preview",
    )

    assert [tool["type"] for tool in captured[0]["tools"]] == ["function"]
    assert result.web_tool_activity[0]["type"] == "google_search_call"
    assert result.web_citations[0]["source_url"] == "https://example.com/event"
    assert result.web_citations[0]["title"] == "Event source"
