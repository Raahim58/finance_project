from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import json
import math
from time import monotonic
from typing import Any, Callable, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.models.user import User


ToolHandler = Callable[[Session, User, BaseModel], dict[str, Any]]
ToolStatus = Literal["ok", "missing", "invalid_arguments", "unavailable"]


def normalize_json(value: Any) -> Any:
    """Preserve exact supported evidence values at the JSON boundary."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("Non-finite decimal evidence")
        return str(value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Evidence object keys must be strings")
        return {key: normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("Non-finite floating-point evidence")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Unsupported evidence type: {type(value).__name__}")


def compact_model_data(value: Any) -> Any:
    """Intern repeated record keys as shared columns without changing scalar values."""

    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            columns = list(dict.fromkeys(key for item in value for key in item))
            return {
                "columns": columns,
                "rows": [
                    [compact_model_data(item.get(column)) for column in columns] for item in value
                ],
            }
        return [compact_model_data(item) for item in value]
    if isinstance(value, dict):
        return {key: compact_model_data(item) for key, item in value.items()}
    return value


def expand_model_data(value: Any) -> Any:
    """Restore compact tables for legacy non-model consumers during Phase 1."""

    if isinstance(value, dict):
        if set(value) == {"columns", "rows"} and isinstance(value["columns"], list):
            return [
                {
                    column: expand_model_data(item)
                    for column, item in zip(value["columns"], row, strict=True)
                }
                for row in value["rows"]
            ]
        return {key: expand_model_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_model_data(item) for item in value]
    return value


def tool_result(
    status: ToolStatus,
    data: Any = None,
    *,
    sources: list[dict[str, Any]] | None = None,
    returned: int = 0,
    remaining: int | None = None,
    continuation: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the sole model-visible result envelope."""

    payload = {
        "status": status,
        "data": compact_model_data(normalize_json(data)),
        "sources": normalize_json(sources or []),
        "coverage": {
            "returned": returned,
            "remaining": remaining,
            "continuation": continuation,
        },
    }
    if error is not None:
        payload["data"] = {"error": normalize_json(error)}
    return payload


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

    def model_schema(self) -> dict[str, Any]:
        units = {"low": 1, "medium": 3, "high": 6}.get(self.cost_class, 6)
        return {
            "name": self.name,
            "description": f"{self.description} Cost: {units} units.",
            "input_schema": self.input_model.model_json_schema(),
        }


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

    def model_catalog(self) -> list[dict[str, Any]]:
        """Return schemas generated directly from the registered Pydantic contracts."""

        return [definition.model_schema() for definition in self.definitions()]

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
        try:
            payload = definition.input_model.model_validate(arguments)
        except ValidationError as exc:
            fields = sorted(
                {
                    ".".join(str(part) for part in item["loc"])
                    for item in exc.errors(include_url=False, include_context=False)
                }
            )
            return tool_result(
                "invalid_arguments",
                error={"code": "invalid_arguments", "fields": fields},
            )
        started = monotonic()
        try:
            result = definition.handler(db, user, payload)
        except HTTPException as exc:
            code = "not_found" if exc.status_code == 404 else "request_unavailable"
            return tool_result(
                "missing" if exc.status_code == 404 else "unavailable",
                error={"code": code},
            )
        except Exception as exc:
            from app.services import assistant_diagnostics as diagnostics

            diagnostics.record_tool_failure(name, exc, "handler_unavailable")
            return tool_result("unavailable", error={"code": "handler_unavailable"})
        elapsed = monotonic() - started
        self._cost_units_spent += units
        if isinstance(result, dict) and set(result) == {"status", "data", "sources", "coverage"}:
            encoded = json.dumps(result, allow_nan=False, separators=(",", ":")).encode()
            result["coverage"].update(
                elapsed_ms=round(elapsed * 1000, 3),
                estimated_bytes=len(encoded),
                estimated_tokens=(len(encoded) + 3) // 4,
                size_kind="estimate",
            )
        return result


def build_tool_registry() -> ToolRegistry:
    from app.tools.document_tools import register_document_tools
    from app.tools.market_tools import register_market_tools
    from app.tools.portfolio_tools import register_portfolio_tools
    from app.tools.quant_tools import register_quant_tools
    from app.tools.research_tools import register_research_tools

    registry = ToolRegistry()
    for register in (
        register_portfolio_tools,
        register_quant_tools,
        register_market_tools,
        register_research_tools,
        register_document_tools,
    ):
        register(registry)
    return registry
