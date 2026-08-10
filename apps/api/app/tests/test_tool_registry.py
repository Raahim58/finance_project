import json

import pytest
from pydantic import BaseModel

from app.ai.orchestrator import _planned_tool_calls
from app.ai.providers.base import LLMProviderResult
from app.tools import build_tool_registry
from app.tools.registry import ToolDefinition, ToolRegistry


class EmptyInput(BaseModel):
    pass


def _definition(*, name: str = "test.tool", timeout: int = 5, cost: str = "low", confirmation: bool = False):
    return ToolDefinition(
        name=name,
        version="1.0",
        description="test",
        input_model=EmptyInput,
        permission_scope="test:read",
        read_only=True,
        requires_confirmation=confirmation,
        timeout_seconds=timeout,
        cost_class=cost,
        handler=lambda _db, _user, _payload: {"ok": True},
    )


def test_tool_registry_enforces_cost_and_confirmation_budgets():
    registry = ToolRegistry()
    registry.register(_definition(name="test.low"))
    registry.register(_definition(name="test.confirm", confirmation=True))

    assert registry.invoke("test.low", None, None, {}, max_cost_units=1) == {"ok": True}
    with pytest.raises(PermissionError, match="cost budget"):
        registry.invoke("test.low", None, None, {}, max_cost_units=1)
    with pytest.raises(PermissionError, match="explicit confirmation"):
        registry.invoke("test.confirm", None, None, {}, confirmed=False)


def test_tool_registry_enforces_elapsed_timeout(monkeypatch):
    ticks = iter([10.0, 12.0])
    monkeypatch.setattr("app.tools.registry.monotonic", lambda: next(ticks))
    registry = ToolRegistry()
    registry.register(_definition(timeout=1))

    with pytest.raises(TimeoutError, match="execution limit"):
        registry.invoke("test.tool", None, None, {})


@pytest.mark.asyncio
async def test_assistant_planner_can_select_bounded_research_refresh():
    class PlannerProvider:
        messages = None

        async def chat(self, _api_key, messages, _model):
            self.messages = messages
            return LLMProviderResult(
                content=json.dumps({"tool_calls": [{"name": "research.refresh_company", "arguments": {"instrument_id": "instrument-1"}}]}),
                model="planner",
                provider="test",
            )

    provider = PlannerProvider()
    calls = await _planned_tool_calls(
        provider,
        "test-key",
        None,
        build_tool_registry(),
        [{"role": "user", "content": "Get the newest company report"}],
        None,
        [{"tool": "research.instruments", "result": {"instruments": []}}],
        2,
    )

    prompt = json.loads(provider.messages[-1]["content"])
    assert "research.refresh_company" in {item["name"] for item in prompt["tools"]}
    assert prompt["maximum_calls"] == 2
    assert calls[0]["name"] == "research.refresh_company"
