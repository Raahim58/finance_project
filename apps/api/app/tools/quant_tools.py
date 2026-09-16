from pydantic import BaseModel, Field

from app.reasoning.allocation import AllocationProposal
from app.services.allocation_verification import verify_allocation
from app.services.decision_analytics_service import risk_budget_analysis
from app.services.workstation_service import portfolio_quant, security_quant
from app.tools.portfolio_tools import PortfolioInput, portfolio_source
from app.tools.registry import ToolDefinition, ToolRegistry, tool_result


def _quant(db, user, payload: PortfolioInput):
    data = portfolio_quant(db, user, payload.portfolio_id, persist=False)
    source = portfolio_source(payload.portfolio_id, data, "aligned_price_covariance_and_ledger_performance")
    data = {key: value for key, value in data.items() if key != "price_provenance"}
    return tool_result(
        "ok", data, sources=[source],
        returned=1, remaining=0
    )


class SecurityInput(BaseModel):
    instrument_id: str


def _security(db, _user, payload: SecurityInput):
    data = security_quant(db, payload.instrument_id)
    return tool_result("ok", data, sources=[{
        "source_name": "Canonical security price risk calculation",
        "instrument_id": payload.instrument_id, "symbol": data.get("symbol"),
        "data_cutoff": data.get("data_cutoff"), "price_source": data.get("source"),
        "calculation_method": "daily_price_returns_risk_metrics", "annualization": data.get("annualization"),
    }], returned=1, remaining=0)


def _risk_budget(db, user, payload: PortfolioInput):
    data = risk_budget_analysis(db, user, payload.portfolio_id)
    source = portfolio_source(payload.portfolio_id, data, "covariance_component_risk_contributions")
    data = {key: value for key, value in data.items() if key != "price_provenance"}
    return tool_result(
        "ok", data, sources=[source],
        returned=1, remaining=0
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
    return tool_result("ok", data, sources=[{
        "source_name": "Server allocation verification",
        "portfolio_id": payload.portfolio_id, "verification_id": data.get("verification_id"),
        "ips_version_id": data.get("ips_version_id"),
        "calculation_method": "gross_cash_lot_rounding_and_ips_comparison",
        "price_observations": {
            key: {field: record.get(field) for field in ("symbol", "source", "source_url", "trade_date", "artifact_id", "artifact_sha256")}
            for key, record in data.get("evidence_versions", {}).items()
        },
    }], returned=len(data.get("legs", [])), remaining=0)


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
            "Submit provisional gross buys/funding sales. Calculates quantities, cash, capital weights, before/after metrics and IPS compliance without executing trades",
            AllocationVerificationInput,
            "portfolio:read",
            True,
            False,
            20,
            "medium",
            _verify_allocation,
        )
    )
