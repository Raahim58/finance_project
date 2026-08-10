from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.user import User


ToolHandler = Callable[[Session, User, BaseModel], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    permission_scope: str
    read_only: bool
    requires_confirmation: bool
    timeout_seconds: int
    cost_class: str
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._cost_units_spent = 0

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Duplicate tool: {definition.name}")
        self._tools[definition.name] = definition

    def definitions(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def invoke(
        self,
        name: str,
        db: Session,
        user: User,
        arguments: dict[str, Any],
        *,
        confirmed: bool = False,
        max_cost_units: int | None = None,
    ) -> dict[str, Any]:
        if name not in self._tools:
            raise KeyError(f"Tool is not allowlisted: {name}")
        definition = self._tools[name]
        if definition.requires_confirmation and not confirmed:
            raise PermissionError(f"Tool {name} requires explicit confirmation")
        units = {"low": 1, "medium": 3, "high": 6}.get(definition.cost_class, 6)
        if max_cost_units is not None and self._cost_units_spent + units > max_cost_units:
            raise PermissionError(f"Tool {name} exceeds the assistant cost budget")
        payload = definition.input_model.model_validate(arguments)
        started = monotonic()
        result = definition.handler(db, user, payload)
        elapsed = monotonic() - started
        if elapsed > definition.timeout_seconds:
            raise TimeoutError(f"Tool {name} exceeded its {definition.timeout_seconds}s execution limit")
        self._cost_units_spent += units
        return result


def build_tool_registry() -> ToolRegistry:
    from app.tools.market_tools import register_market_tools
    from app.tools.portfolio_tools import register_portfolio_tools
    from app.tools.quant_tools import register_quant_tools
    from app.tools.research_tools import register_research_tools

    registry = ToolRegistry()
    for register in (register_portfolio_tools, register_quant_tools, register_market_tools, register_research_tools):
        register(registry)
    return registry
