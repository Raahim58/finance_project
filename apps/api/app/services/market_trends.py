"""Batch recent database closes without one history request per table row."""
import json
from sqlalchemy import func, select
from app.models.market import MarketPrice
from app.models.workstation import DataSource, Instrument, MarketObservation, SourceArtifact
from app.services.canonical_market_service import SYNTHETIC_SOURCE_NAMES, synthetic_market_data_allowed


def recent_closes(db, symbols):
    result = {symbol: [] for symbol in symbols}
    if not symbols:
        return result
    query = select(Instrument.symbol.label('symbol'), MarketObservation.values_json.label('values'),
        MarketObservation.effective_at.label('at'),
        func.row_number().over(partition_by=Instrument.symbol,
            order_by=MarketObservation.effective_at.desc()).label('rank')).join(
        MarketObservation, MarketObservation.instrument_id == Instrument.id).join(
        SourceArtifact, SourceArtifact.id == MarketObservation.artifact_id).join(
        DataSource, DataSource.id == SourceArtifact.data_source_id).where(
        Instrument.symbol.in_(symbols), MarketObservation.is_selected.is_(True), MarketObservation.frequency == 'daily')
    if not synthetic_market_data_allowed():
        query = query.where(~func.lower(DataSource.name).in_(SYNTHETIC_SOURCE_NAMES),
            ~func.lower(SourceArtifact.source_url).like('demo://%'),
            ~func.lower(SourceArtifact.source_url).like('normalized://mock/%'))
    ranked = query.subquery()
    for row in db.execute(select(ranked).where(ranked.c.rank <= 30).order_by(ranked.c.symbol, ranked.c.at)):
        close = json.loads(row._mapping['values']).get('close')
        if close is not None:
            result[row.symbol].append(str(close))
    missing = [symbol for symbol, rows in result.items() if not rows]
    if missing:
        query = select(MarketPrice.symbol, MarketPrice.close, MarketPrice.trade_date,
            func.row_number().over(partition_by=MarketPrice.symbol,
                order_by=MarketPrice.trade_date.desc()).label('rank')).where(MarketPrice.symbol.in_(missing))
        if not synthetic_market_data_allowed():
            query = query.where(func.lower(MarketPrice.source) != 'mock')
        ranked = query.subquery()
        for row in db.execute(select(ranked).where(ranked.c.rank <= 30).order_by(ranked.c.symbol, ranked.c.trade_date)):
            result[row.symbol].append(str(row.close))
    return result
