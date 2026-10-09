"""Resolve a broad observed session; a canary quote is not the whole market.

Coverage is relative to the largest of the five most recent daily datasets,
not a claim that every symbol in PSX's historical directory traded that day.
"""
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Date, JSON, case, cast, func, select

from app.core.config import settings
from app.models.market import MarketPrice
from app.models.workstation import DataSource, Instrument, MarketObservation, SourceArtifact
from app.services.canonical_market_service import SYNTHETIC_SOURCE_NAMES, synthetic_market_data_allowed


@dataclass(frozen=True)
class MarketSession:
    trade_date: date
    basis: str
    securities: int
    observed_at: datetime | None
    source: str | None
    source_sla_minutes: int | None
    latest_quote_date: date | None = None
    latest_quote_count: int = 0


def _eligible(statement):
    if synthetic_market_data_allowed():
        return statement
    return statement.where(
        ~func.lower(DataSource.name).in_(SYNTHETIC_SOURCE_NAMES),
        ~func.lower(SourceArtifact.source_url).like("demo://%"),
        ~func.lower(SourceArtifact.source_url).like("normalized://mock/%"),
    )


def resolve_session(db) -> MarketSession | None:
    if db.bind.dialect.name == "postgresql":
        day = func.coalesce(
            cast(cast(MarketObservation.values_json, JSON)["trade_date"].as_string(), Date),
            cast(func.timezone("Asia/Karachi", MarketObservation.effective_at), Date))
    else:
        day = func.coalesce(func.json_extract(MarketObservation.values_json, "$.trade_date"),
                            func.date(MarketObservation.effective_at))
    query = _eligible(select(
        day.label("day"), MarketObservation.frequency,
        func.count(func.distinct(MarketObservation.instrument_id)).label("count"),
        func.max(case((MarketObservation.frequency == "intraday", MarketObservation.effective_at),
                      else_=SourceArtifact.retrieved_at)).label("retrieved_at"),
    ).join(Instrument, Instrument.id == MarketObservation.instrument_id)
      .join(SourceArtifact, SourceArtifact.id == MarketObservation.artifact_id)
      .join(DataSource, DataSource.id == SourceArtifact.data_source_id)
      .where(MarketObservation.is_selected.is_(True),
             MarketObservation.frequency.in_(("daily", "intraday")),
             Instrument.instrument_type == "equity")
      .group_by(day, MarketObservation.frequency).order_by(day.desc()).limit(10))
    groups = [(date.fromisoformat(str(r.day)), r.frequency, r.count, r.retrieved_at) for r in db.execute(query)]
    daily = [r for r in groups if r[1] == "daily"][:5]
    quotes = next((r for r in groups if r[1] == "intraday"), None)
    baseline = max((r[2] for r in daily), default=0)
    if not baseline:
        baseline = db.scalar(select(func.count()).select_from(Instrument).where(
            Instrument.instrument_type == "equity", Instrument.active_to.is_(None))) or 0
    minimum = baseline * settings.market_broad_coverage_ratio
    chosen = next((r for r in daily if r[2] >= minimum), None)
    published_snapshot = False
    if quotes:
        # A verified full-source snapshot can legitimately contain fewer traded
        # securities shortly after open. A symbol-limited canary cannot opt in.
        published_snapshot = bool(db.scalar(_eligible(select(SourceArtifact.id)
            .join(MarketObservation, MarketObservation.artifact_id == SourceArtifact.id)
            .join(Instrument, Instrument.id == MarketObservation.instrument_id)
            .join(DataSource, DataSource.id == SourceArtifact.data_source_id)
            .where(MarketObservation.frequency == 'intraday', MarketObservation.is_selected.is_(True),
                   day == quotes[0], Instrument.instrument_type == 'equity',
                   func.lower(DataSource.name) == 'psx dps market watch',
                   SourceArtifact.parser_version == 'dps-market-watch-v1',
                   SourceArtifact.response_metadata_json.like('%"quote_scope": "all_regular_equities"%'))).limit(1)))
    broad_quotes = quotes and (quotes[2] >= minimum or published_snapshot)
    if broad_quotes and (chosen is None or quotes[0] > chosen[0]):
        chosen = quotes
    elif broad_quotes and chosen and quotes[0] == chosen[0] and quotes[3] >= chosen[3]:
        chosen = quotes
    if chosen is None:
        legacy = select(MarketPrice.trade_date, func.count(MarketPrice.id).label("count"))
        if not synthetic_market_data_allowed():
            legacy = legacy.where(func.lower(MarketPrice.source) != "mock")
        rows = db.execute(legacy.group_by(MarketPrice.trade_date).order_by(MarketPrice.trade_date.desc()).limit(5)).all()
        ceiling = max((r.count for r in rows), default=0)
        row = next((r for r in rows if r.count >= ceiling * settings.market_broad_coverage_ratio), None)
        if row is None:
            return None
        latest = db.scalar(select(MarketPrice).where(MarketPrice.trade_date == row.trade_date)
                           .order_by(MarketPrice.ingested_at.desc()).limit(1))
        return MarketSession(row.trade_date, "daily", row.count, latest.ingested_at, latest.source, 1440,
                             quotes[0] if quotes else None, quotes[2] if quotes else 0)
    selected_day, basis, count, _retrieved = chosen
    provenance = _eligible(select(SourceArtifact, DataSource)
        .join(MarketObservation, MarketObservation.artifact_id == SourceArtifact.id)
        .join(Instrument, Instrument.id == MarketObservation.instrument_id)
        .join(DataSource, DataSource.id == SourceArtifact.data_source_id)
        .where(MarketObservation.is_selected.is_(True), MarketObservation.frequency == basis,
               Instrument.instrument_type == "equity", day == selected_day)
        .order_by(SourceArtifact.retrieved_at.desc()).limit(1))
    artifact, source = db.execute(provenance).one()
    return MarketSession(selected_day, basis, count, _retrieved, source.name,
                         source.freshness_sla_minutes, quotes[0] if quotes else None,
                         quotes[2] if quotes else 0)
