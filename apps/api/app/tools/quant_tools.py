import json

from pydantic import BaseModel, Field, field_validator
from fastapi import HTTPException

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


class SecuritiesInput(BaseModel):
    instrument_ids: list[str] = Field(min_length=1, max_length=10)


def _securities(db, user, payload: SecuritiesInput):
    rows, sources = [], []
    for identifier in dict.fromkeys(payload.instrument_ids):
        try:
            envelope = _security(db, user, SecurityInput(instrument_id=identifier))
            from app.tools.registry import expand_model_data
            rows.append({'status': 'ok', **expand_model_data(envelope['data'])})
            sources.extend(envelope['sources'])
        except HTTPException as exc:
            if exc.status_code not in (404, 422):
                raise
            rows.append({'instrument_id': identifier, 'status': 'missing', 'reason': exc.detail})
    return tool_result('ok' if any(row['status'] == 'ok' for row in rows) else 'missing',
                       {'securities': rows, 'missing_instruments': [row['instrument_id'] for row in rows if row['status'] == 'missing']},
                       sources=sources, returned=len(rows), remaining=0)


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

    @field_validator("proposal", mode="before")
    @classmethod
    def parse_proposal(cls, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError("proposal must be an object or a valid JSON object string") from None
            if not isinstance(value, dict):
                raise ValueError("proposal must decode to an object with a legs array")
        return value


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
    registry.register(ToolDefinition('quant.securities', '1.0',
        'Batch return/risk metrics for up to ten securities from stored sourced-adjusted prices. Missing history is explicit per security.',
        SecuritiesInput, 'market:read', True, False, 20, _securities))
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
            _risk_budget,
        )
    )
    registry.register(
        ToolDefinition(
            "allocation.verify",
            "1.0",
            "Verify up to 20 provisional gross buy/sell legs over at most 100 held/proposed instruments. Uses all available aligned daily history (sample dates/count returned), with a 20-second tool deadline. Computes quantities, cash, weights and IPS compliance without executing trades.",
            AllocationVerificationInput,
            "portfolio:read",
            True,
            False,
            20,
            _verify_allocation,
        )
    )


def model_verification_result(data):
    """Model projection only; the encrypted checkpoint retains the full calculation."""
    result = {key: data[key] for key in (
        "accepted", "errors", "verification_id", "ips_version_id", "trade_feasibility",
        "IPS_status", "evidence_status", "legs", "current_weights", "proposed_weights",
        "current_cash", "proposed_cash", "cost_note", "financial_state_mutated",
        "evidence_readiness",
    ) if key in data}
    result["metrics"] = data.get("comparison", {}).get("metrics", []) if data.get("comparison") else []
    checks = data.get("checks", {})
    result["checks"] = {key: checks[key] for key in ("arithmetic_funding", "modeled_goal") if key in checks}
    compliance = data.get("proposed_compliance", {})
    result["checks"]["ips_compliance"] = {
        "status": compliance.get("status"),
        "checks": compliance.get("checks", []),
    }
    freshness = checks.get("price_freshness", {})
    result["checks"]["price_freshness"] = {
        "status": freshness.get("status"),
        "coverage": {key: len((record.get("policy") or {}).get("intervening_sessions", []))
                     for key, record in freshness.get("instruments", {}).items()},
        "instruments": {key: {field: value for field, value in record.items()
                            if field in {"status", "trade_date", "latest_price_date", "missing_sessions", "reason"}
                            and not isinstance(value, (dict, list))}
                        for key, record in freshness.get("instruments", {}).items()},
    }
    records = data.get("evidence_versions", {})
    result["symbols"] = {key: record.get("symbol") for key, record in records.items()}
    result["risk_sample"] = data.get("risk_sample")
    return result
