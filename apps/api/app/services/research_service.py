import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.market import MarketPrice
from app.models.user import User
from app.models.workstation import (
    Event,
    EventEntityLink,
    EventSource,
    FinancialFact,
    Instrument,
    InstrumentAlias,
    MacroObservation,
    MacroSeries,
)
from app.schemas.research import InstrumentResponse
from app.services.portfolio_service import get_portfolio_summary


def serialize_instrument(row: Instrument) -> InstrumentResponse:
    return InstrumentResponse(id=row.id, symbol=row.symbol, name=row.name, instrument_type=row.instrument_type, currency=row.currency, country=row.country, sector=row.sector, active_from=row.active_from, active_to=row.active_to, metadata=json.loads(row.metadata_json))


def search_instruments(db: Session, query: str | None = None, instrument_type: str | None = None, sector: str | None = None, limit: int = 50):
    statement = select(Instrument)
    if query:
        term = f"%{query.strip()}%"
        statement = statement.where(or_(Instrument.symbol.ilike(term), Instrument.name.ilike(term)))
    if instrument_type: statement = statement.where(Instrument.instrument_type == instrument_type)
    if sector: statement = statement.where(Instrument.sector == sector)
    return [serialize_instrument(row) for row in db.scalars(statement.order_by(Instrument.symbol).limit(limit))]


def instrument_detail(db: Session, instrument_id: str):
    row = db.get(Instrument, instrument_id)
    if row is None: raise HTTPException(status_code=404, detail="Instrument not found")
    aliases = [{"provider": alias.provider, "alias": alias.alias, "valid_from": alias.valid_from, "valid_to": alias.valid_to} for alias in db.scalars(select(InstrumentAlias).where(InstrumentAlias.instrument_id == row.id))]
    return {**serialize_instrument(row).model_dump(), "aliases": aliases}


def market_series(db: Session, instrument_id: str, start=None, end=None):
    instrument = db.get(Instrument, instrument_id)
    if instrument is None: raise HTTPException(status_code=404, detail="Instrument not found")
    statement = select(MarketPrice).where(MarketPrice.symbol == instrument.symbol)
    if start: statement = statement.where(MarketPrice.trade_date >= start)
    if end: statement = statement.where(MarketPrice.trade_date <= end)
    rows = list(db.scalars(statement.order_by(MarketPrice.trade_date)))
    return {"instrument_id": instrument.id, "symbol": instrument.symbol, "series": [{"date": row.trade_date, "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume, "source": row.source, "source_url": row.source_url, "ingested_at": row.ingested_at} for row in rows]}


def list_macro_series(db: Session):
    return [{"id": row.id, "key": row.key, "name": row.name, "unit": row.unit, "frequency": row.frequency, "metadata": json.loads(row.metadata_json)} for row in db.scalars(select(MacroSeries).order_by(MacroSeries.key))]


def macro_releases(db: Session, series_id: str | None = None):
    statement = select(MacroObservation, MacroSeries).join(MacroSeries, MacroSeries.id == MacroObservation.series_id).where(MacroObservation.is_selected.is_(True))
    if series_id: statement = statement.where(MacroObservation.series_id == series_id)
    return [{"series_id": series.id, "series_key": series.key, "effective_date": observation.effective_date, "release_at": observation.release_at, "value": observation.value, "unit": series.unit, "revision": observation.revision, "artifact_id": observation.artifact_id} for observation, series in db.execute(statement.order_by(MacroObservation.effective_date.desc()).limit(500))]


def company_overview(db: Session, user: User, instrument_id: str):
    instrument = db.get(Instrument, instrument_id)
    if instrument is None: raise HTTPException(status_code=404, detail="Instrument not found")
    latest = db.scalar(select(MarketPrice).where(MarketPrice.symbol == instrument.symbol).order_by(MarketPrice.trade_date.desc()))
    facts = list(db.scalars(select(FinancialFact).where(FinancialFact.instrument_id == instrument.id).order_by(FinancialFact.period_end.desc()).limit(100)))
    documents = list(db.scalars(select(Document).where(Document.symbol == instrument.symbol, or_(Document.visibility == "public", Document.owner_user_id == user.id)).order_by(Document.published_date.desc()).limit(20)))
    event_links = list(db.scalars(select(EventEntityLink).where(EventEntityLink.entity_key == instrument.symbol)))
    events = [db.get(Event, link.event_id) for link in event_links]
    relevance = []
    from app.models.portfolio import Portfolio, PortfolioHolding
    for portfolio, holding in db.execute(select(Portfolio, PortfolioHolding).join(PortfolioHolding, PortfolioHolding.portfolio_id == Portfolio.id).where(Portfolio.user_id == user.id, PortfolioHolding.symbol == instrument.symbol)):
        summary = get_portfolio_summary(db, user, portfolio.id)
        item = next((value for value in summary.holdings if value.symbol == instrument.symbol), None)
        relevance.append({"portfolio_id": portfolio.id, "portfolio_name": portfolio.name, "quantity": holding.quantity, "market_value": item.market_value if item else 0, "weight": float(item.market_value / summary.total_value) if item and summary.total_value else 0})
    return {
        "instrument": serialize_instrument(instrument).model_dump(),
        "market": None if latest is None else {"date": latest.trade_date, "close": latest.close, "volume": latest.volume, "change_percent": latest.change_percent, "source": latest.source, "source_url": latest.source_url},
        "fundamentals": [{"taxonomy_key": fact.taxonomy_key, "period_type": fact.period_type, "period_end": fact.period_end, "filing_date": fact.filing_date, "value": fact.value, "unit": fact.unit, "currency": fact.currency, "document_id": fact.document_id, "page_number": fact.page_number} for fact in facts],
        "documents": [{"id": document.id, "title": document.title, "document_type": document.document_type, "published_date": document.published_date, "source_url": document.source_url} for document in documents],
        "events": [{"id": event.id, "title": event.title, "event_type": event.event_type, "occurred_at": event.occurred_at, "direction": event.direction, "confidence": event.confidence} for event in events if event],
        "portfolio_relevance": relevance,
    }


def list_events(db: Session, entity_key: str | None = None, limit: int = 100):
    statement = select(Event)
    if entity_key:
        statement = statement.join(EventEntityLink, EventEntityLink.event_id == Event.id).where(EventEntityLink.entity_key == entity_key.upper())
    rows = list(db.scalars(statement.order_by(Event.occurred_at.desc()).limit(limit)))
    result = []
    for event in rows:
        sources = list(db.scalars(select(EventSource).where(EventSource.event_id == event.id)))
        result.append({"id": event.id, "event_type": event.event_type, "title": event.title, "occurred_at": event.occurred_at, "materiality": event.materiality, "direction": event.direction, "confidence": event.confidence, "details": json.loads(event.details_json), "sources": [{"source_name": source.source_name, "source_url": source.source_url, "document_id": source.document_id} for source in sources]})
    return result
