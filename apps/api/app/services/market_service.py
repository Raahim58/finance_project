from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.market import (
    Company,
    Exchange,
    MarketIngestionRun,
    MarketPrice,
    MarketSnapshot,
    SectorDailyStats,
)
from app.schemas.market import (
    CompanyDetailResponse,
    CompanyResponse,
    ExchangeResponse,
    IndexCloseResponse,
    MarketFreshnessResponse,
    MarketOverviewResponse,
    MarketPriceResponse,
    MarketSnapshotResponse,
    SectorDailyStatsResponse,
)
from app.services.canonical_market_service import CanonicalPrice, canonical_prices_for_date, latest_price, price_series


def serialize_exchange(exchange: Exchange) -> ExchangeResponse:
    return ExchangeResponse(code=exchange.code, name=exchange.name, timezone=exchange.timezone)


def serialize_company(company: Company) -> CompanyResponse:
    return CompanyResponse(
        id=company.id,
        symbol=company.symbol,
        name=company.name,
        sector=company.sector,
        exchange=serialize_exchange(company.exchange),
        official_website=company.official_website,
        psx_url=company.psx_url,
        description=company.description,
        is_active=company.is_active,
    )


def serialize_price(price: MarketPrice | CanonicalPrice) -> MarketPriceResponse:
    capitalization = (price.capitalization or {}) if isinstance(price, CanonicalPrice) else {}
    return MarketPriceResponse(
        symbol=price.symbol,
        trade_date=price.trade_date,
        open=price.open,
        high=price.high,
        low=price.low,
        close=price.close,
        previous_close=price.previous_close,
        change=price.change,
        change_percent=price.change_percent,
        volume=price.volume,
        value=price.value,
        market_cap=price.market_cap,
        shares_outstanding=capitalization.get('ordinary_shares'),
        free_float_shares=capitalization.get('free_float_shares'),
        free_float_market_cap=capitalization.get('free_float_market_cap'),
        capitalization_date=capitalization.get('trade_date'),
        capitalization_source_url=capitalization.get('source_url'),
        source=price.source,
        source_url=price.source_url,
        ingested_at=price.observed_at if isinstance(price, CanonicalPrice) else price.ingested_at,
    )


def serialize_snapshot(snapshot: MarketSnapshot) -> MarketSnapshotResponse:
    return MarketSnapshotResponse(
        snapshot_date=snapshot.snapshot_date,
        index_name=snapshot.index_name,
        index_value=snapshot.index_value,
        index_change=snapshot.index_change,
        index_change_percent=snapshot.index_change_percent,
        total_volume=snapshot.total_volume,
        total_value=snapshot.total_value,
        source=snapshot.source,
        ingested_at=snapshot.ingested_at,
    )


def serialize_sector_stats(stats: SectorDailyStats) -> SectorDailyStatsResponse:
    return SectorDailyStatsResponse(
        sector=stats.sector,
        trade_date=stats.trade_date,
        total_volume=stats.total_volume,
        total_value=stats.total_value,
        average_change_percent=stats.average_change_percent,
        advancers=stats.advancers,
        decliners=stats.decliners,
        unchanged=stats.unchanged,
        source=stats.source,
    )


def get_latest_market_date(db: Session) -> date | None:
    from app.services.market_session import resolve_session
    session = resolve_session(db)
    return session.trade_date if session else None


def resolve_market_date(db: Session, requested_date: date | None) -> date:
    if requested_date:
        fallback = select(MarketPrice.id).where(MarketPrice.trade_date == requested_date)
        if not settings.is_synthetic_environment:
            fallback = fallback.where(func.lower(MarketPrice.source) != "mock")
        if canonical_prices_for_date(db, requested_date, include_intraday=True) or db.scalar(fallback.limit(1)):
            return requested_date
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No market prices found for {requested_date.isoformat()}",
        )

    latest = get_latest_market_date(db)
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No market data is available")
    return latest


def get_market_snapshot(db: Session, requested_date: date | None = None) -> MarketSnapshotResponse | None:
    trade_date = resolve_market_date(db, requested_date)
    from app.models.workstation import DataSource, Instrument, MarketObservation, SourceArtifact
    import json
    start = datetime.combine(trade_date, time.min, tzinfo=ZoneInfo('Asia/Karachi'))
    index_query = select(MarketObservation, SourceArtifact, DataSource).join(
        Instrument, Instrument.id == MarketObservation.instrument_id).join(
        SourceArtifact, SourceArtifact.id == MarketObservation.artifact_id).join(
        DataSource, DataSource.id == SourceArtifact.data_source_id).where(
        Instrument.symbol == 'KSE100', MarketObservation.frequency == 'index_intraday',
        MarketObservation.is_selected.is_(True), MarketObservation.effective_at >= start,
        MarketObservation.effective_at < start + timedelta(days=1),
        DataSource.name == 'PSX DPS trading panel')
    live_index = db.execute(index_query.order_by(MarketObservation.effective_at.desc()).limit(1)).first()
    from app.services.market_session import resolve_session
    session = resolve_session(db)
    # Once a newer daily close is available it supersedes earlier intraday levels.
    if live_index and session and session.basis == 'intraday':
        observation, artifact, publisher = live_index
        values = json.loads(observation.values_json)
        return MarketSnapshotResponse(snapshot_date=trade_date, index_name='KSE-100',
            index_value=Decimal(values['close']), index_change=Decimal(values['change']),
            index_change_percent=Decimal(values['change_percent']), total_volume=values['volume'],
            total_value=Decimal(values['value']), source=publisher.name, source_url=artifact.source_url,
            ingested_at=observation.effective_at,
            totals_note='Published index-session volume and value from the PSX trading panel. Chart history uses daily closes.')
    statement = select(MarketSnapshot).where(MarketSnapshot.snapshot_date == trade_date)
    if not settings.is_synthetic_environment:
        statement = statement.where(func.lower(MarketSnapshot.source) != "mock")
    snapshot = db.scalar(
        statement
        .order_by(MarketSnapshot.index_name)
        .limit(1)
    )
    if snapshot:
        return serialize_snapshot(snapshot)
    # Official index closes are already ingested canonically, not into the old
    # snapshot table. Read them; do not write another synthetic snapshot.
    from app.models.workstation import Instrument, MarketObservation, SourceArtifact
    from app.services.canonical_market_service import close_series
    closes = close_series(db, 'KSE100', end=trade_date)
    previous_dates = sorted(day for day in closes if day < trade_date)
    if trade_date not in closes or not previous_dates:
        return None
    start = datetime.combine(trade_date, time.min, tzinfo=ZoneInfo('Asia/Karachi'))
    artifact = db.scalar(select(SourceArtifact).join(MarketObservation, MarketObservation.artifact_id == SourceArtifact.id)
        .join(Instrument, Instrument.id == MarketObservation.instrument_id)
        .where(Instrument.symbol == 'KSE100', MarketObservation.is_selected.is_(True),
            MarketObservation.frequency == 'daily_close', MarketObservation.effective_at >= start,
            MarketObservation.effective_at < start + timedelta(days=1))
        .order_by(SourceArtifact.retrieved_at.desc()).limit(1))
    if artifact is None:
        return None
    prices = _prices_for_date(db, trade_date)
    current, previous = closes[trade_date], closes[previous_dates[-1]]
    return MarketSnapshotResponse(snapshot_date=trade_date,index_name='KSE-100',index_value=current,
        index_change=current-previous,index_change_percent=(current-previous)/previous*100,
        total_volume=sum(row.volume for row in prices),total_value=sum((row.value for row in prices),Decimal('0')),
        source='PSX DPS',source_url=artifact.source_url,ingested_at=artifact.retrieved_at,
        totals_note=f'Totals cover {len(prices)} stored securities, excluding indices; value is close × volume, not reported turnover.')


def get_index_history(db: Session, symbol: str, limit: int = 400) -> list[IndexCloseResponse]:
    from app.services.canonical_market_service import close_series
    closes = close_series(db, symbol.replace("-", "").upper())
    if not closes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Index history not found")
    return [IndexCloseResponse(trade_date=day, close=closes[day]) for day in sorted(closes)[-limit:]]


def _price_query(trade_date: date) -> Select[tuple[MarketPrice]]:
    statement = select(MarketPrice).where(MarketPrice.trade_date == trade_date)
    if not settings.is_synthetic_environment:
        statement = statement.where(func.lower(MarketPrice.source) != "mock")
    return statement


def _prices_for_date(db: Session, trade_date: date) -> list[MarketPrice | CanonicalPrice]:
    from app.services.market_session import resolve_session
    session = resolve_session(db)
    intraday = bool(session and session.trade_date == trade_date and session.basis == "intraday")
    canonical = canonical_prices_for_date(db, trade_date, include_intraday=intraday)
    if canonical:
        return _without_indices(db, canonical)
    return _without_indices(db, list(db.scalars(_price_query(trade_date))))


def _without_indices(db, prices):
    from app.models.workstation import Instrument
    index_symbols = set(db.scalars(select(Instrument.symbol).where(
        Instrument.instrument_type.in_(('index','total_return_index')))))
    return [row for row in prices if row.symbol not in index_symbols]


def get_top_gainers(db: Session, requested_date: date | None = None, limit: int = 10) -> list[MarketPriceResponse]:
    trade_date = resolve_market_date(db, requested_date)
    rows = sorted((row for row in _prices_for_date(db, trade_date) if row.change > 0), key=lambda row: (row.change_percent, row.volume), reverse=True)[:limit]
    return [serialize_price(row) for row in rows]


def get_top_losers(db: Session, requested_date: date | None = None, limit: int = 10) -> list[MarketPriceResponse]:
    trade_date = resolve_market_date(db, requested_date)
    rows = sorted((row for row in _prices_for_date(db, trade_date) if row.change < 0), key=lambda row: (row.change_percent, -row.volume))[:limit]
    return [serialize_price(row) for row in rows]


def get_top_volume(db: Session, requested_date: date | None = None, limit: int = 10) -> list[MarketPriceResponse]:
    trade_date = resolve_market_date(db, requested_date)
    rows = sorted(_prices_for_date(db, trade_date), key=lambda row: row.volume, reverse=True)[:limit]
    return [serialize_price(row) for row in rows]


def get_sectors(db: Session, requested_date: date | None = None) -> list[SectorDailyStatsResponse]:
    trade_date = resolve_market_date(db, requested_date)
    canonical = _prices_for_date(db, trade_date)
    if canonical:
        return _sector_stats(db, trade_date, canonical)
    statement = select(SectorDailyStats).where(SectorDailyStats.trade_date == trade_date)
    if not settings.is_synthetic_environment:
        statement = statement.where(func.lower(SectorDailyStats.source) != "mock")
    return [serialize_sector_stats(row) for row in db.scalars(statement.order_by(SectorDailyStats.average_change_percent.desc()))]


def _sector_stats(db, trade_date, canonical):
    companies = {row.symbol: row for row in db.scalars(select(Company).where(Company.symbol.in_([price.symbol for price in canonical])))}
    grouped: dict[str, list[CanonicalPrice]] = {}
    for price in canonical:
        grouped.setdefault(companies.get(price.symbol).sector if companies.get(price.symbol) else "Unknown", []).append(price)
    return sorted([
        SectorDailyStatsResponse(
            sector=sector, trade_date=trade_date,
            total_volume=sum(row.volume for row in prices),
            total_value=sum((row.value for row in prices), Decimal("0")),
            average_change_percent=sum((row.change_percent for row in prices), Decimal("0")) / len(prices),
            advancers=sum(row.change > 0 for row in prices), decliners=sum(row.change < 0 for row in prices),
            unchanged=sum(row.change == 0 for row in prices),
            source="canonical_selected_observations" if all(isinstance(row, CanonicalPrice) for row in prices) else prices[0].source,
        ) for sector, prices in grouped.items()
    ], key=lambda row: row.average_change_percent, reverse=True)

def get_market_overview(db: Session, requested_date: date | None = None) -> MarketOverviewResponse:
    from app.services.market_session import resolve_session
    session = resolve_session(db)
    trade_date = resolve_market_date(db, requested_date)
    prices = _prices_for_date(db, trade_date)
    return MarketOverviewResponse(
        trade_date=trade_date,
        price_basis=session.basis if session and session.trade_date == trade_date else "daily",
        priced_securities=len(prices),
        observed_at=session.observed_at if session and session.trade_date == trade_date else None,
        latest_quote_date=session.latest_quote_date if session else None,
        latest_quote_count=session.latest_quote_count if session else 0,
        prices=[serialize_price(row) for row in prices],
        snapshot=get_market_snapshot(db, trade_date),
        top_gainers=[serialize_price(row) for row in sorted((row for row in prices if row.change > 0), key=lambda row: (row.change_percent, row.volume), reverse=True)[:5]],
        top_losers=[serialize_price(row) for row in sorted((row for row in prices if row.change < 0), key=lambda row: (row.change_percent, -row.volume))[:5]],
        top_volume=[serialize_price(row) for row in sorted(prices, key=lambda row: row.volume, reverse=True)[:5]],
        sectors=_sector_stats(db, trade_date, prices) if prices else [],
    )


def get_sector_performance(
    db: Session,
    sector: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[SectorDailyStatsResponse]:
    dates = []
    latest = get_latest_market_date(db)
    if latest:
        cursor = start_date or (latest - timedelta(days=365))
        final = end_date or latest
        while cursor <= final:
            if canonical_prices_for_date(db, cursor):
                dates.append(cursor)
            cursor += timedelta(days=1)
    canonical_rows = [next((row for row in get_sectors(db, day) if row.sector.lower() == sector.lower()), None) for day in dates]
    canonical_rows = [row for row in canonical_rows if row is not None]
    if canonical_rows:
        return canonical_rows
    query = select(SectorDailyStats).where(func.lower(SectorDailyStats.sector) == sector.lower())
    if not settings.is_synthetic_environment:
        query = query.where(func.lower(SectorDailyStats.source) != "mock")
    if start_date:
        query = query.where(SectorDailyStats.trade_date >= start_date)
    if end_date:
        query = query.where(SectorDailyStats.trade_date <= end_date)
    rows = db.scalars(query.order_by(SectorDailyStats.trade_date.asc())).all()
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sector performance not found")
    return [serialize_sector_stats(row) for row in rows]


def search_companies(db: Session, query_text: str | None = None, limit: int = 20) -> list[CompanyResponse]:
    query = select(Company).options(joinedload(Company.exchange)).where(Company.is_active.is_(True))
    if query_text:
        normalized = query_text.strip().upper()
        like = f"%{normalized}%"
        query = query.where((func.upper(Company.symbol).like(like)) | (func.upper(Company.name).like(like)))
        query = query.order_by((func.upper(Company.symbol) == normalized).desc(), Company.symbol.asc())
    else:
        query = query.order_by(Company.symbol.asc())
    rows = db.scalars(query.limit(limit)).all()
    return [serialize_company(row) for row in rows]


def get_company_detail(db: Session, symbol: str) -> CompanyDetailResponse:
    company = db.scalar(
        select(Company)
        .options(joinedload(Company.exchange))
        .where(func.upper(Company.symbol) == symbol.upper(), Company.is_active.is_(True))
    )
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    latest_observation = latest_price(db, company.symbol)
    if latest_observation and not latest_observation.capitalization:
        # Share/capitalization workbooks are daily observations. Display the
        # latest stored snapshot with its own date, without repricing it using
        # the current intraday quote or changing analytical price inputs.
        from dataclasses import replace
        from app.services.dps_capitalization import capitalization
        reported = capitalization(db, latest_observation.instrument_id, latest_observation.trade_date)
        if reported:
            latest_observation = replace(latest_observation,
                market_cap=Decimal(reported['market_cap']), capitalization=reported)
    return CompanyDetailResponse(
        company=serialize_company(company),
        latest_price=serialize_price(latest_observation) if latest_observation else None,
    )


def get_company_history(
    db: Session,
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 2000,
) -> list[MarketPriceResponse]:
    company_exists = db.scalar(select(Company.id).where(func.upper(Company.symbol) == symbol.upper()))
    if not company_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    rows = price_series(db, symbol, start_date, end_date)
    return [serialize_price(row) for row in rows[-limit:]]


PSX_TZ = ZoneInfo("Asia/Karachi")
PSX_SESSION_OPEN = time(9, 15)
PSX_SESSION_CLOSE = time(15, 30)
EXCHANGE_SESSION_NOTE = "Approximate PSX Mon-Fri 09:15-15:30 Asia/Karachi session window; does not account for exchange holidays."


def _last_expected_business_day(reference_date: date) -> date:
    cursor = reference_date
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def _exchange_session_status(now_karachi: datetime) -> str:
    if now_karachi.weekday() >= 5:
        return "closed"
    return "open" if PSX_SESSION_OPEN <= now_karachi.time() <= PSX_SESSION_CLOSE else "closed"


def _trade_date_status(latest_trade_date: date | None, now_karachi: datetime) -> str:
    if latest_trade_date is None:
        return "unknown"
    expected = _last_expected_business_day(now_karachi.date())
    if latest_trade_date == expected:
        return "current"
    previous_expected = _last_expected_business_day(expected - timedelta(days=1))
    if latest_trade_date == previous_expected:
        return "prior_session"
    return "stale"


def get_market_freshness(db: Session) -> MarketFreshnessResponse:
    from app.services.market_session import resolve_session
    session = resolve_session(db)
    if session and session.source and session.source.lower() != "mock":
        now = datetime.now(PSX_TZ)
        observed = session.observed_at
        observed_utc = (observed.astimezone(UTC) if observed and observed.tzinfo
                        else observed.replace(tzinfo=UTC) if observed else None)
        age = max(0, (datetime.now(UTC) - observed_utc).total_seconds()) if observed_utc else None
        # Before the opening window, yesterday's close is the latest expected
        # session. Ingestion time alone must never make an old trade date fresh.
        expected = _last_expected_business_day(now.date())
        if now.weekday() < 5 and now.time() < PSX_SESSION_OPEN:
            expected = _last_expected_business_day(expected - timedelta(days=1))
        previous = _last_expected_business_day(expected - timedelta(days=1))
        trade_status = "current" if session.trade_date == expected else "prior_session" if session.trade_date == previous else "stale"
        exchange_status = _exchange_session_status(now)
        stale = trade_status == "stale" or (exchange_status == "open" and (
            session.basis == "daily" or age is None or age > (session.source_sla_minutes or 120) * 60))
        warning = ("Only the previous daily session is available; current quotes are awaiting ingestion."
                   if stale and session.basis == "daily" and exchange_status == "open" else
                   "The displayed market session is out of date."
                   if stale else None)
        return MarketFreshnessResponse(
            market_data_mode=settings.market_data_mode, refresh_seconds=settings.market_data_refresh_seconds,
            last_successful_ingestion_at=observed, latest_trade_date=session.trade_date,
            latest_source=session.source, latest_used_provider=session.source,
            is_stale=stale, stale_warning=warning, ingestion_staleness_warning=warning,
            ingestion_age_seconds=age, trade_date_status=trade_status,
            exchange_session_status=exchange_status, exchange_session_note=EXCHANGE_SESSION_NOTE,
            price_basis=session.basis, priced_securities=session.securities,
            latest_quote_date=session.latest_quote_date, latest_quote_count=session.latest_quote_count,
            source_freshness_sla_minutes=session.source_sla_minutes,
        )
    run_statement = select(MarketIngestionRun)
    snapshot_statement = select(MarketSnapshot)
    if not settings.is_synthetic_environment:
        run_statement = run_statement.where(func.lower(MarketIngestionRun.used_provider) != "mock")
        snapshot_statement = snapshot_statement.where(func.lower(MarketSnapshot.source) != "mock")
    latest_run = db.scalar(
        run_statement
        .where(MarketIngestionRun.status == "success")
        .order_by(MarketIngestionRun.finished_at.desc())
        .limit(1)
    )
    latest_snapshot = db.scalar(snapshot_statement.order_by(MarketSnapshot.ingested_at.desc()).limit(1))

    last_successful = latest_run.finished_at if latest_run else (latest_snapshot.ingested_at if latest_snapshot else None)
    latest_trade_date = latest_run.latest_trade_date if latest_run else (latest_snapshot.snapshot_date if latest_snapshot else None)
    latest_source = latest_run.used_provider if latest_run else (latest_snapshot.source if latest_snapshot else None)
    now_karachi = datetime.now(PSX_TZ)
    if last_successful is None:
        return MarketFreshnessResponse(
            market_data_mode=settings.market_data_mode,
            refresh_seconds=settings.market_data_refresh_seconds,
            last_successful_ingestion_at=None,
            latest_trade_date=None,
            latest_source=None,
            latest_attempted_provider=None,
            latest_used_provider=None,
            is_stale=True,
            stale_warning="No successful market ingestion has completed yet.",
            backup_warning=None,
            ingestion_age_seconds=None,
            provider_mode_warning="Current market data mode is mock. Use dps mode for live/current ingestion." if settings.market_data_mode == "mock" else None,
            ingestion_staleness_warning="No successful market ingestion has completed yet.",
            fallback_provider_active=False,
            trade_date_status="unknown",
            exchange_session_status=_exchange_session_status(now_karachi),
            exchange_session_note=EXCHANGE_SESSION_NOTE,
        )

    last_successful_utc = last_successful.astimezone(UTC) if last_successful.tzinfo else last_successful.replace(tzinfo=UTC)
    age_seconds = (datetime.now(UTC) - last_successful_utc).total_seconds()
    is_stale = age_seconds > settings.market_data_refresh_seconds
    provider_mode_warning: str | None = "Current market data mode is mock. Treat all prices, quotes, and index values as synthetic, not observed market data." if latest_source == "mock" or settings.market_data_mode == "mock" else None
    ingestion_staleness_warning: str | None = "Market data is older than MARKET_DATA_REFRESH_SECONDS. Refresh ingestion before relying on the latest view." if is_stale else None
    # Backward-compatible combined message; prefer the split fields above for new UI.
    warning = provider_mode_warning or ingestion_staleness_warning
    backup_warning: str | None = None
    fallback_provider_active = False

    return MarketFreshnessResponse(
        market_data_mode=settings.market_data_mode,
        refresh_seconds=settings.market_data_refresh_seconds,
        last_successful_ingestion_at=last_successful,
        latest_trade_date=latest_trade_date,
        latest_source=latest_source,
        latest_attempted_provider=latest_run.attempted_provider if latest_run else None,
        latest_used_provider=latest_run.used_provider if latest_run else latest_source,
        is_stale=is_stale,
        stale_warning=warning,
        backup_warning=backup_warning,
        ingestion_age_seconds=age_seconds,
        provider_mode_warning=provider_mode_warning,
        ingestion_staleness_warning=ingestion_staleness_warning,
        fallback_provider_active=fallback_provider_active,
        trade_date_status=_trade_date_status(latest_trade_date, now_karachi),
        exchange_session_status=_exchange_session_status(now_karachi),
        exchange_session_note=EXCHANGE_SESSION_NOTE,
    )
