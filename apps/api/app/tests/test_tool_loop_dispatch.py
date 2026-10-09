"""Offline tool loop dispatch contracts and fixtures."""

import asyncio
import pytest
from app.ai.providers.base import ContentBlock
from app.ai.providers.http_placeholders import AnthropicProvider
from app.ai.tool_loop import AssistantTerminalError, ToolExecution
from app.tools.registry import tool_result
from app.tests.support.assistant import _anthropic_tool_results, _mock_market, _auth_with_anthropic
from app.tests.support.assistant import anthropic_text, anthropic_turn


def test_parallel_tool_workers_are_bounded_to_four_and_keep_call_order(client, monkeypatch):
    headers, _ = _auth_with_anthropic(client, monkeypatch, email="bounded-tools@example.com")
    provider = AnthropicProvider()
    responses = [
        anthropic_turn(
            [
                {
                    "type": "tool_use",
                    "id": f"bounded-{index}",
                    "name": "market__freshness",
                    "input": {},
                }
                for index in range(5)
            ],
            identifier="five-tools",
            stop_reason="tool_use",
        ),
        anthropic_text("Bounded work complete.", identifier="bounded-final"),
    ]
    active = 0
    peak = 0

    async def fake_post(_url, _key, _payload):
        return responses.pop(0)

    async def measured_tool(_user_id, call):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return ToolExecution(call, tool_result("ok", returned=1, remaining=0), 10.0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    monkeypatch.setattr("app.ai.tool_loop._execute_tool", measured_tool)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Run five independent checks", "provider": "anthropic"},
    )

    assert response.status_code == 201, response.text
    assert peak == 4
    assert [row["tool_call_id"] for row in response.json()["tool_trace"]] == [
        f"bounded-{index}" for index in range(5)
    ]


def test_request_categories_use_real_registry_services_and_pagination(client, monkeypatch):
    # This fixture verifies registry/service coverage; budget exhaustion has separate
    # Phase 11 fixtures. Its full mock universe is intentionally verbose.
    from app.services import assistant_policy

    fixture_policy = assistant_policy.selected_policy() | {
        "input": 200000,
        "cumulative_input": 1000000,
    }
    monkeypatch.setattr(assistant_policy, "execution_policy", lambda: fixture_policy)
    monkeypatch.setattr(assistant_policy, "selected_policy", lambda: fixture_policy)
    headers, _ = _auth_with_anthropic(client, monkeypatch, email="categories@example.com")
    instruments = _mock_market(monkeypatch)
    first, second = instruments[:2]
    portfolio_id = client.post(
        "/portfolios", headers=headers, json={"name": "Comparison portfolio"}
    ).json()["id"]
    provider = AnthropicProvider()
    captured = []
    calls = [
        ("ambiguous-company", "research__instruments", {"query": "Bank", "limit": 20}),
        ("universe-page-1", "market__universe", {"limit": 1}),
        (
            "company-a",
            "research__company_sections",
            {"instrument_id": first.id, "sections": ["company_facts"]},
        ),
        ("portfolio", "portfolio__summary", {"portfolio_id": portfolio_id}),
        ("universe-page-2", "market__universe", {"cursor": "1", "limit": 1}),
        (
            "company-b",
            "research__company_sections",
            {"instrument_id": second.id, "sections": ["company_facts"]},
        ),
    ]
    responses = [
        anthropic_turn(
            [{"type": "tool_use", "id": identifier, "name": name, "input": arguments}],
            identifier=f"category-tool-{index}",
            stop_reason="tool_use",
        )
        for index, (identifier, name, arguments) in enumerate(calls)
    ] + [
        anthropic_text(
            "Comparison complete; missing data noted.", identifier="category-final"
        ),
    ]

    # Keep six provider calls including the final answer: batch the final two reads.
    responses[4]["content"].extend(responses.pop(5)["content"])

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Compare two companies with my portfolio and inspect the PSX universe.",
            "portfolio_id": portfolio_id,
            "provider": "anthropic",
        },
    )

    assert response.status_code == 201, response.text
    results = [result for payload in captured[1:] for result in _anthropic_tool_results(payload)]
    assert len(results) == 6, response.json()["synthesis"]
    assert results[0]["coverage"]["returned"] >= 2
    assert results[1]["coverage"]["returned"] == 1
    assert results[1]["coverage"]["remaining"] == len(instruments) - 1
    assert results[1]["coverage"]["continuation"] == "1"
    assert [row["status"] for row in results[2:4]] == ["ok", "ok"]
    assert results[4]["coverage"]["returned"] == 1
    assert results[5]["status"] == "ok"
    assert [row["tool"] for row in response.json()["tool_trace"]][-2:] == [
        "market.universe",
        "research.company_sections",
    ]


def test_malformed_and_forbidden_calls_return_stable_associated_results(client, monkeypatch):
    headers, _ = _auth_with_anthropic(client, monkeypatch, email="invalid-tools@example.com")
    provider = AnthropicProvider()
    captured = []
    responses = [
        anthropic_turn(
            [
                {
                    "type": "tool_use",
                    "id": "malformed",
                    "name": "market__series",
                    "input": {},
                },
                {
                    "type": "tool_use",
                    "id": "forbidden",
                    "name": "broker__place_trade",
                    "input": {"symbol": "MEBL"},
                },
                {
                    "type": "tool_use",
                    "id": "missing-data",
                    "name": "market__series",
                    "input": {"instrument_id": "missing-instrument"},
                },
            ],
            identifier="invalid-tools",
            stop_reason="tool_use",
        ),
        anthropic_text(
            "The requested tools were unavailable.", identifier="invalid-final"
        ),
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Try invalid operations", "provider": "anthropic"},
    )

    assert response.status_code == 201, response.text
    blocks = [
        block for block in captured[1]["messages"][-1]["content"] if block["type"] == "tool_result"
    ]
    assert [block["tool_use_id"] for block in blocks] == [
        "malformed",
        "forbidden",
        "missing-data",
    ]
    results = _anthropic_tool_results(captured[1])
    assert results[0]["data"]["error"]["code"] == "invalid_arguments"
    assert results[1]["data"]["error"]["code"] == "forbidden_tool"
    assert results[2]["status"] == "missing"


def test_allocation_tools_reject_overselling_and_ips_breaches(client, monkeypatch):
    headers, _ = _auth_with_anthropic(client, monkeypatch, email="allocation-loop@example.com")
    instruments = _mock_market(monkeypatch)
    mebl = next(row for row in instruments if row.symbol == "MEBL")
    portfolio_id = client.post(
        "/portfolios", headers=headers, json={"name": "Allocation portfolio"}
    ).json()["id"]
    holding = client.post(
        f"/portfolios/{portfolio_id}/holdings",
        headers=headers,
        json={"symbol": "MEBL", "quantity": "1", "average_cost": "100"},
    )
    assert holding.status_code == 201, holding.text
    deposit = client.post(
        f"/portfolios/{portfolio_id}/transactions",
        headers=headers,
        json={
            "symbol": "CASH",
            "transaction_type": "deposit",
            "amount": "10000",
            "transaction_date": "2026-08-07",
        },
    )
    assert deposit.status_code == 201, deposit.text
    ips = client.post(
        f"/portfolios/{portfolio_id}/ips/confirm",
        headers=headers,
        json={
            "constraints": {
                "max_instrument_weight": 0.05,
                "max_sector_weight": 1.0,
                "min_cash_weight": 0.0,
            },
            "horizon_years": 5,
        },
    )
    assert ips.status_code == 201, ips.text

    provider = AnthropicProvider()
    captured = []
    responses = [
        anthropic_turn(
            [
                {
                    "type": "tool_use",
                    "id": "oversell",
                    "name": "allocation__verify",
                    "input": {
                        "portfolio_id": portfolio_id,
                        "allowed_instrument_ids": [mebl.id],
                        "proposal": {
                            "legs": [
                                {
                                    "instrument_id": mebl.id,
                                    "side": "sell",
                                    "gross_amount": "999999",
                                }
                            ]
                        },
                    },
                }
            ],
            identifier="allocation-tools",
            stop_reason="tool_use",
        ),
        anthropic_turn(
            [
                {
                    "type": "tool_use",
                    "id": "ips-breach",
                    "name": "allocation__verify",
                    "input": {
                        "portfolio_id": portfolio_id,
                        "allowed_instrument_ids": [mebl.id],
                        "proposal": {
                            "legs": [
                                {
                                    "instrument_id": mebl.id,
                                    "side": "buy",
                                    "gross_amount": "5000",
                                }
                            ]
                        },
                    },
                }
            ],
            identifier="allocation-ips-tool",
            stop_reason="tool_use",
        ),
        anthropic_text("Both proposals were rejected.", identifier="allocation-final"),
        anthropic_text(
            "Both proposals were rejected [[E1]].", identifier="allocation-repair"
        ),
    ]

    async def fake_post(_url, _key, payload):
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={
            "question": "Size these alternatives without changing my portfolio.",
            "portfolio_id": portfolio_id,
            "provider": "anthropic",
        },
    )

    assert response.status_code == 201, response.text
    oversell = _anthropic_tool_results(captured[1])[0]
    ips_breach = _anthropic_tool_results(captured[2])[0]
    assert "overselling" in oversell["data"]["errors"]
    assert "binding_constraint_breach_remains" in ips_breach["data"]["errors"]
    body = response.json()
    assert body["synthesis"]["allocation_check"]["status"] == "rejected"
    assert body["synthesis"]["allocation_check"]["financial_state_mutated"] is False
    assert "Allocation check: rejected" in body["answer"]


def test_tool_call_limit_applies_without_cost_units_and_accepts_old_checkpoints():
    from app.ai.tool_loop import _reserve_calls

    checkpoint = {"reserved_tool_calls": 0, "reserved_tool_cost_units": 0}
    names = ["research.company_sections"] * 10
    _reserve_calls(
        checkpoint,
        [
            ContentBlock("tool_call", id=str(index), name=name, arguments={})
            for index, name in enumerate(names)
        ],
    )
    assert checkpoint["reserved_tool_calls"] == 10
    _reserve_calls(
        checkpoint, [ContentBlock("tool_call", id="verify", name="allocation.verify", arguments={})]
    )
    assert checkpoint == {"reserved_tool_calls": 11, "reserved_tool_cost_units": 0}
    _reserve_calls(
        checkpoint, [ContentBlock("tool_call", id="last", name="quant.security", arguments={})]
    )
    with pytest.raises(AssistantTerminalError, match="tool_call_limit_exhausted"):
        _reserve_calls(
            checkpoint,
            [ContentBlock("tool_call", id="overflow", name="quant.security", arguments={})],
        )
    assert checkpoint["reserved_tool_calls"] == 12
