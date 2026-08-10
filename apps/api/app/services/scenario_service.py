import json
from datetime import date

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.quant import drawdown_series
from app.models.market import MarketPrice
from app.models.user import User
from app.models.workstation import Instrument, ScenarioDefinition, ScenarioShock
from app.schemas.research import HistoricalReplayRequest, ScenarioDefinitionCreate, ScenarioDefinitionResponse
from app.services.ledger_service import cash_balance, replay_positions
from app.services.portfolio_service import get_portfolio_or_404


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
    for symbol, position in positions.items():
        start = db.scalar(select(MarketPrice).where(MarketPrice.symbol == symbol, MarketPrice.trade_date >= payload.start_date).order_by(MarketPrice.trade_date))
        end = db.scalar(select(MarketPrice).where(MarketPrice.symbol == symbol, MarketPrice.trade_date <= payload.end_date).order_by(MarketPrice.trade_date.desc()))
        if not start or not end or end.trade_date <= start.trade_date:
            series.append({"symbol": symbol, "available": False, "reason": "Missing aligned boundary prices"}); continue
        start_value = float(position.quantity * start.close); end_value = float(position.quantity * end.close)
        series.append({"symbol": symbol, "available": True, "quantity": float(position.quantity), "start_date": start.trade_date, "end_date": end.trade_date, "start_value": start_value, "end_value": end_value, "pnl": end_value - start_value, "return": end_value / start_value - 1})
    valid = [item for item in series if item.get("available")]
    start_total = sum(item["start_value"] for item in valid); end_total = sum(item["end_value"] for item in valid)
    return {"portfolio_id": portfolio.id, "start_date": payload.start_date, "end_date": payload.end_date, "counterfactual": payload.use_current_holdings, "assumption": "Current holdings replayed over a past interval" if payload.use_current_holdings else "Ledger positions as of replay start", "start_value": start_total, "end_value": end_total, "pnl": end_total - start_total, "return": end_total / start_total - 1 if start_total else None, "positions": series}


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
