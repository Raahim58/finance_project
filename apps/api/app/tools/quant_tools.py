from pydantic import BaseModel, Field

from app.reasoning.allocation import AllocationProposal
from app.services.allocation_verification import verify_allocation
from app.services.decision_analytics_service import risk_budget_analysis
from app.services.workstation_service import portfolio_quant, security_quant
from app.tools.portfolio_tools import PortfolioInput
from app.tools.registry import ToolDefinition, ToolRegistry, tool_result


def _quant(db, user, payload: PortfolioInput):
    return tool_result(
        "ok", portfolio_quant(db, user, payload.portfolio_id), returned=1, remaining=0
    )


class SecurityInput(BaseModel):
    instrument_id: str


def _security(db, _user, payload: SecurityInput):
    return tool_result("ok", security_quant(db, payload.instrument_id), returned=1, remaining=0)


def _risk_budget(db, user, payload: PortfolioInput):
    return tool_result(
        "ok", risk_budget_analysis(db, user, payload.portfolio_id), returned=1, remaining=0
    )


class AllocationVerificationInput(BaseModel):
    portfolio_id: str
    proposal: AllocationProposal
    allowed_instrument_ids: list[str] = Field(min_length=1, max_length=100)


def _verify_allocation(db, user, payload: AllocationVerificationInput):
    data = verify_allocation(
        db,
        user,
        payload.portfolio_id,
        payload.proposal,
        payload.allowed_instrument_ids,
    )
    return tool_result("ok", data, returned=len(data.get("legs", [])), remaining=0)


def register_quant_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            "quant.portfolio",
            "1.0",
            "Reproducible portfolio risk and performance metrics",
            PortfolioInput,
            "portfolio:read",
            True,
            False,
            15,
            "medium",
            _quant,
        )
    )
    registry.register(
        ToolDefinition(
            "quant.security",
            "1.0",
            "Security return and risk metrics from canonical observations",
            SecurityInput,
            "market:read",
            True,
            False,
            10,
            "medium",
            _security,
        )
    )
    registry.register(
        ToolDefinition(
            "quant.risk_budget",
            "1.0",
            "Total-capital and risky-sleeve weights with percentage risk contribution per holding",
            PortfolioInput,
            "portfolio:read",
            True,
            False,
            15,
            "medium",
            _risk_budget,
        )
    )
    registry.register(
        ToolDefinition(
            "allocation.verify",
            "1.0",
            "Read-only deterministic verification of a model-proposed allocation",
            AllocationVerificationInput,
            "portfolio:read",
            True,
            False,
            20,
            "medium",
            _verify_allocation,
        )
    )
