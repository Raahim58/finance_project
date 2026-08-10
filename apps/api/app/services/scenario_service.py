import json
from datetime import date

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.quant import risk_metrics
from app.models.user import User
from app.models.workstation import Instrument, ScenarioDefinition, ScenarioShock
from app.schemas.research import HistoricalReplayRequest, ScenarioDefinitionCreate, ScenarioDefinitionResponse
from app.services.ledger_service import cash_balance, replay_positions
from app.services.portfolio_service import get_portfolio_or_404
from app.services.canonical_market_service import price_series


def serialize_definition(db: Session, row: ScenarioDefinition) -> ScenarioDefinitionResponse:
    shocks = list(db.scalars(select(ScenarioShock).where(ScenarioShock.scenario_definition_id == row.id)))
    return ScenarioDefinitionResponse(id=row.id, portfolio_id=row.portfolio_id, name=row.name, scenario_type=row.scenario_type, description=row.description, assumptions=json.loads(row.assumptions_json), shocks=[{"id": shock.id, "target_type": shock.target_type, "target_key": shock.target_key, "shock_value": shock.shock_value, "unit": shock.unit} for shock in shocks], created_at=row.created_at)


def create_definition(db: Session, user: User, portfolio_id: str, payload: ScenarioDefinitionCreate):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    row = ScenarioDefinition(portfolio_id=portfolio.id, owner_user_id=user.id, name=payload.name, scenario_type=payload.scenario_type, description=payload.description, assumptions_json=json.dumps(payload.assumptions, sort_keys=True))
    db.add(row); db.flush()
    for shock in payload.shocks:
        db.add(ScenarioShock(scenario_definition_id=row.id, target_type=shock.target_type, target_key=shock.target_key.upper() if shock.target_type in {"instrument", "index"} else shock.target_key, shock_value=shock.shock_value, unit=shock.unit))
    db.commit(); db.refresh(row)
    return serialize_definition(db, row)


def list_definitions(db: Session, user: User, portfolio_id: str):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    return [serialize_definition(db, row) for row in db.scalars(select(ScenarioDefinition).where(ScenarioDefinition.portfolio_id == portfolio.id).order_by(ScenarioDefinition.created_at.desc()))]


def historical_replay(db: Session, user: User, portfolio_id: str, payload: HistoricalReplayRequest):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    if payload.end_date <= payload.start_date:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")
    positions = replay_positions(db, portfolio.id) if payload.use_current_holdings else replay_positions(db, portfolio.id, payload.start_date)
    if not positions:
        raise HTTPException(status_code=422, detail="No positions are available for the requested replay")
    series = []
    by_symbol: dict[str, dict[date, float]] = {}
    for symbol, position in positions.items():
        prices = price_series(db, symbol, payload.start_date, payload.end_date)
        if len(prices) < 2:
            series.append({"symbol": symbol, "available": False, "reason": "Missing aligned boundary prices"}); continue
        by_symbol[symbol] = {row.trade_date: float(row.close) for row in prices}
        start = prices[0]; end = prices[-1]
        start_value = float(position.quantity * start.close); end_value = float(position.quantity * end.close)
        instrument = db.get(Instrument, position.instrument_id)
        series.append({"symbol": symbol, "sector": instrument.sector if instrument else None, "available": True, "quantity": float(position.quantity), "start_date": start.trade_date, "end_date": end.trade_date, "start_value": start_value, "end_value": end_value, "pnl": end_value - start_value, "return": end_value / start_value - 1, "source": start.source, "artifact_ids": [start.artifact_id, end.artifact_id]})
    valid = [item for item in series if item.get("available")]
    start_total = sum(item["start_value"] for item in valid); end_total = sum(item["end_value"] for item in valid)
    common_dates = sorted(set.intersection(*(set(by_symbol[item["symbol"]]) for item in valid))) if valid else []
    starting_cash = float(cash_balance(db, portfolio.id, portfolio.base_currency, payload.start_date))
    path = []
    for day in common_dates:
        value = starting_cash + sum(float(positions[item["symbol"]].quantity) * by_symbol[item["symbol"]][day] for item in valid)
        path.append({"date": day, "value": value})
    returns = np.asarray([path[index]["value"] / path[index - 1]["value"] - 1 for index in range(1, len(path)) if path[index - 1]["value"] > 0])
    risk = risk_metrics(returns).to_dict() if returns.size >= 2 else {"available": False, "reason": "At least two path returns are required."}
    values = np.asarray([item["value"] for item in path], dtype=float)
    drawdowns = values / np.maximum.accumulate(values) - 1 if values.size else np.asarray([])
    recovery_days = None
    if drawdowns.size:
        trough = int(np.argmin(drawdowns)); prior_peak = float(np.max(values[:trough + 1]))
        recovery = next((index for index in range(trough + 1, len(values)) if values[index] >= prior_peak), None)
        recovery_days = (common_dates[recovery] - common_dates[trough]).days if recovery is not None else None
    sector_contribution: dict[str, float] = {}
    for item in valid:
        sector = str(item.get("sector") or "Unknown")
        sector_contribution[sector] = sector_contribution.get(sector, 0) + float(item["pnl"])
    return {
        "portfolio_id": portfolio.id, "start_date": payload.start_date, "end_date": payload.end_date,
        "counterfactual": payload.use_current_holdings,
        "assumption": "Current holdings replayed over a past interval" if payload.use_current_holdings else "Ledger positions as of replay start",
        "start_value": start_total + starting_cash, "end_value": end_total + starting_cash,
        "pnl": end_total - start_total, "return": (end_total + starting_cash) / (start_total + starting_cash) - 1 if start_total + starting_cash else None,
        "path": path, "path_risk": risk, "max_drawdown": float(np.min(drawdowns)) if drawdowns.size else None,
        "recovery_days": recovery_days, "sector_pnl_contribution": sector_contribution,
        "positions": series, "total_return_available": False,
        "total_return_unavailable_reason": "Corporate-action coverage is not certified complete.",
    }


def resolve_shock(instrument: Instrument, direct: dict[str, float], sectors: dict[str, float], factors: dict[str, float]) -> tuple[float, list[str]]:
    if instrument.symbol in direct:
        return direct[instrument.symbol], [f"direct:{instrument.symbol}"]
    shock = sectors.get(instrument.sector or "", 0.0)
    sources = [f"sector:{instrument.sector}"] if instrument.sector in sectors else []
    metadata = json.loads(instrument.metadata_json)
    betas = metadata.get("factor_betas", {}) if isinstance(metadata, dict) else {}
    for factor, factor_shock in factors.items():
        if factor in betas:
            shock += float(betas[factor]) * factor_shock; sources.append(f"factor:{factor}")
    return shock, sources
