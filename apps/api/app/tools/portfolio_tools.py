import hashlib
import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models.workstation import Instrument, PortfolioIPSVersion

from app.services.portfolio_service import get_portfolio_performance, get_portfolio_summary
from app.services.workstation_service import ips_compliance, list_scenario_runs
from app.tools.registry import ToolDefinition, ToolRegistry, tool_result


class PortfolioInput(BaseModel):
    portfolio_id: str


class PortfolioEventExposureInput(PortfolioInput):
    limit: int = Field(default=8, ge=1, le=15)


class PortfolioPerformanceInput(PortfolioInput):
    limit: int = Field(default=365, ge=2, le=5000)
    # 'summary' (default) returns computed statistics plus a bounded sample of the
    # ledger series; 'full' returns every point (can be thousands of tokens).
    view: Literal['summary', 'full'] = 'summary'


SUMMARY_SAMPLE_POINTS = 24


def summarize_performance(points: list[dict]) -> dict:
    """Deterministic statistics and an evenly spaced sample from stored ledger points."""
    def number(value):
        return None if value is None else Decimal(str(value))
    twr = [(row['value_date'], number(row.get('cumulative_twr_percent'))) for row in points
           if row.get('cumulative_twr_percent') is not None]
    def day(item):
        return None if item is None else {'date': item[0], 'percent': str(item[1])}
    peak, drawdown, worst = None, Decimal('0'), None
    for date_, value in twr:   # drawdown on the cash-flow-adjusted index, not raw value
        index = Decimal('1') + value / Decimal('100')
        peak = index if peak is None or index > peak else peak
        if peak:
            change = (index - peak) / peak * Decimal('100')
            if change < drawdown:
                drawdown, worst = change, date_
    daily = [(row['value_date'], number(row.get('day_change_percent'))) for row in points
             if row.get('day_change_percent') is not None]
    step = max(1, -(-len(points) // SUMMARY_SAMPLE_POINTS))
    sample = points[::step]
    if points and sample[-1] is not points[-1]:
        sample.append(points[-1])
    return {
        'point_count': len(points), 'first_date': points[0]['value_date'] if points else None,
        'last_date': points[-1]['value_date'] if points else None,
        'start_value': points[0]['total_value'] if points else None,
        'end_value': points[-1]['total_value'] if points else None,
        'net_external_cash_flow': str(sum((number(row['external_cash_flow']) or Decimal('0') for row in points), Decimal('0'))),
        'cumulative_twr_percent': str(twr[-1][1]) if twr else None,
        'max_drawdown_percent': str(drawdown.quantize(Decimal('0.0001'))) if twr else None,
        'max_drawdown_trough_date': worst,
        'best_day': day(max(daily, key=lambda item: item[1], default=None)),
        'worst_day': day(min(daily, key=lambda item: item[1], default=None)),
        'method': 'computed from stored ledger points; drawdown is on the cumulative TWR index',
        'sampled_points': sample, 'sample_step_days': step,
    }


def portfolio_source(portfolio_id, data, method):
    """Internal references identify delivered private evidence without public URLs."""
    return {
        "source_name": "Stored portfolio analysis",
        "record_type": "portfolio",
        "record_id": portfolio_id,
        "calculation_method": method,
        "data_cutoff": data.get("data_cutoff") or data.get("data_freshness_date"),
        "run_id": data.get("run_id"),
        "price_provenance": data.get("price_provenance") or [
            {key: row.get(key) for key in ("symbol", "data_source", "latest_price_date", "artifact_id", "quality_status")}
            for row in data.get("holdings", [])
        ],
    }


def _summary(db, user, payload: PortfolioInput):
    data = get_portfolio_summary(db, user, payload.portfolio_id).model_dump(mode="json")
    holdings = data.get("holdings", [])
    instruments = {row.symbol: row.id for row in db.scalars(
        select(Instrument).where(Instrument.symbol.in_([row["symbol"] for row in holdings]))
    )}
    for holding in holdings:
        holding["instrument_id"] = instruments.get(holding["symbol"])
    return tool_result("ok", data,
                       sources=[portfolio_source(payload.portfolio_id, data, "stored_holdings_and_database_prices")],
                       returned=len(holdings), remaining=0)


def _performance(db, user, payload: PortfolioPerformanceInput):
    points = get_portfolio_performance(db, user, payload.portfolio_id, payload.limit)
    rows = [point.model_dump(mode="json") for point in points]
    data = {"portfolio_id": payload.portfolio_id}
    if payload.view == 'full':
        data["points"] = rows
    else:
        data["summary"] = summarize_performance(rows)
    data["data_cutoff"] = points[-1].value_date if points else None
    return tool_result("ok" if points else "missing", data,
                       sources=[portfolio_source(payload.portfolio_id, data, "ledger_time_weighted_return")],
                       returned=len(points), remaining=0)


EXCERPT_CHARS = 260


def _event_exposure(db, user, payload: PortfolioEventExposureInput):
    """Recent stored events mapped onto the selected portfolio's holdings, weighted from SQL.

    Compact by design: top events only, at most two short original excerpts each.
    Direction and size of impact are not calculated anywhere, and this says so.
    """
    from app.services.research_intelligence_service import portfolio_intelligence

    result = portfolio_intelligence(db, user, payload.portfolio_id, payload.limit)
    sources, events = {}, []
    for row in result["events"]:
        event = row["event"]
        refs = []
        excerpts = []
        for item in (event.get("evidence") or event.get("sources") or [])[:2]:
            ref = "evt-" + hashlib.sha256(json.dumps([item.get("source_url"), item.get("document_id"), item.get("title") or item.get("source_name")], default=str).encode()).hexdigest()[:20]
            sources[ref] = {"id": ref, "source_name": item.get("source_name") or item.get("title") or "Event source",
                            "source_url": item.get("source_url"), "document_id": item.get("document_id"),
                            "published_at": item.get("published_at")}
            refs.append(ref)
            if item.get("text"):
                excerpts.append({"source_ref": ref, "text": str(item["text"])[:EXCERPT_CHARS]})
        events.append({
            "title": event.get("title"), "occurred_at": event.get("occurred_at"), "event_type": event.get("event_type"),
            "materiality": event.get("materiality"), "freshness": event.get("freshness_status"),
            "affected_holdings": [{"symbol": c["symbol"], "relationship": c["relationship_kind"],
                                   "portfolio_weight": c.get("current_portfolio_weight")} for c in row["companies"]],
            "potentially_affected_weight": row.get("potentially_affected_weight"),
            "impact": "not_calculated", "evidence": excerpts, "source_refs": refs,
        })
    data = {"events": events, "coverage": result.get("coverage"), "valuation_complete": result.get("valuation_complete"),
            "window": "90 days; classified medium/high materiality events with indexed original evidence",
            "note": "Exposure is the share of the portfolio in affected holdings; impact direction and size are not calculated."}
    return tool_result("ok" if events else "missing", data, sources=list(sources.values()), returned=len(events), remaining=0)


def _ips(db, user, payload: PortfolioInput):
    data = ips_compliance(db, user, payload.portfolio_id, persist_analysis=False)
    version = db.get(PortfolioIPSVersion, data["ips_version_id"]) if data.get("ips_version_id") else None
    if version is not None and version.portfolio_id != payload.portfolio_id:
        raise ValueError("Selected IPS does not belong to portfolio")
    constraints = json.loads(version.constraints_json or "{}") if version else {}
    inputs = constraints.get("objective_inputs", {})
    method = constraints.get("required_return_method", {})
    data["mandate"] = {
        "available": version is not None and version.status == "confirmed" and version.confirmed_at is not None,
        "ips_version_id": version.id if version else None,
        "version": version.version if version else None,
        "goal": constraints.get("goal"),
        "horizon_years": inputs.get("horizon_years"),
        "required_return": version.required_return if version else None,
        "required_return_analysis": {
            "available": version is not None and version.required_return is not None,
            "basis": method, "assumptions": inputs,
            "meaning": "required annual return, not a forecast",
        },
        "constraints": constraints,
        "risk_budget_targets": constraints.get("risk_budgets"),
        "risk_budget_tolerance": constraints.get("risk_budget_tolerance"),
        "risk_budget_unit": "fraction_of_portfolio_risk",
    }
    return tool_result(
        "ok", data, sources=[{
            "source_name": "Selected portfolio IPS and compliance",
            "record_type": "ips_version", "record_id": data.get("ips_version_id"),
            "portfolio_id": payload.portfolio_id,
            "version": version.version if version else None,
            "confirmed_at": version.confirmed_at if version else None,
            "calculation_method": "evaluate_ips_constraints",
            "data_cutoff": data.get("data_cutoff"), "price_provenance": data.get("price_provenance", []),
        }], returned=1, remaining=0
    )


def _scenario_history(db, user, payload: PortfolioInput):
    rows = list_scenario_runs(db, user, payload.portfolio_id)
    return tool_result(
        "ok" if rows else "missing", {"history": rows}, returned=len(rows), remaining=0
    )


def register_portfolio_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            "portfolio.summary",
            "1.0",
            "User-owned holdings with resolved instrument IDs, cash, valuation, source metadata and freshness",
            PortfolioInput,
            "portfolio:read",
            True,
            False,
            5,
            _summary,
        )
    )
    registry.register(
        ToolDefinition(
            "portfolio.performance",
            "1.0",
            "Cash-flow-adjusted ledger performance history",
            PortfolioPerformanceInput,
            "portfolio:read",
            True,
            False,
            10,
            _performance,
        )
    )
    registry.register(
        ToolDefinition(
            "portfolio.event_exposure",
            "1.0",
            "Recent stored market and company events mapped to the selected portfolio's holdings with portfolio weights and original evidence excerpts; no impact forecast",
            PortfolioEventExposureInput,
            "portfolio:read",
            True,
            False,
            12,
            _event_exposure,
        )
    )
    registry.register(
        ToolDefinition(
            "ips.compliance",
            "1.0",
            "Selected IPS mandate, goal, horizon, required-return basis, risk-budget targets and current compliance",
            PortfolioInput,
            "portfolio:read",
            True,
            False,
            8,
            _ips,
        )
    )
    registry.register(
        ToolDefinition(
            "scenario.history",
            "1.0",
            "Recorded scenario runs with stressed PnL and compliance for a portfolio",
            PortfolioInput,
            "portfolio:read",
            True,
            False,
            8,
            _scenario_history,
        )
    )
