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
    MarketFreshnessResponse,
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
    from app.models.workstation import DataSource, MarketObservation, SourceArtifact
    statement = (
        select(func.max(MarketObservation.effective_at))
        .join(SourceArtifact, SourceArtifact.id == MarketObservation.artifact_id)
        .join(DataSource, DataSource.id == SourceArtifact.data_source_id)
        .where(MarketObservation.is_selected.is_(True), MarketObservation.frequency == "daily")
    )
    if not settings.is_synthetic_environment:
        statement = statement.where(func.lower(DataSource.name) != "mock")
    observed = db.scalar(statement)
    legacy = select(func.max(MarketPrice.trade_date))
    if not settings.is_synthetic_environment:
        legacy = legacy.where(func.lower(MarketPrice.source) != "mock")
    return observed.date() if observed else db.scalar(legacy)


def resolve_market_date(db: Session, requested_date: date | None) -> date:
    if requested_date:
        fallback = select(MarketPrice.id).where(MarketPrice.trade_date == requested_date)
        if not settings.is_synthetic_environment:
            fallback = fallback.where(func.lower(MarketPrice.source) != "mock")
        if canonical_prices_for_date(db, requested_date) or db.scalar(fallback.limit(1)):
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
    statement = select(MarketSnapshot).where(MarketSnapshot.snapshot_date == trade_date)
    if not settings.is_synthetic_environment:
        statement = statement.where(func.lower(MarketSnapshot.source) != "mock")
    snapshot = db.scalar(
        statement
        .order_by(MarketSnapshot.index_name)
        .limit(1)
    )
    return serialize_snapshot(snapshot) if snapshot else None


def _price_query(trade_date: date) -> Select[tuple[MarketPrice]]:
    statement = select(MarketPrice).where(MarketPrice.trade_date == trade_date)
    if not settings.is_synthetic_environment:
        statement = statement.where(func.lower(MarketPrice.source) != "mock")
    return statement


def _prices_for_date(db: Session, trade_date: date) -> list[MarketPrice | CanonicalPrice]:
    canonical = canonical_prices_for_date(db, trade_date)
    if canonical:
        return canonical
    return list(db.scalars(_price_query(trade_date)))


def get_top_gainers(db: Session, requested_date: date | None = None, limit: int = 10) -> list[MarketPriceResponse]:
    trade_date = resolve_market_date(db, requested_date)
    rows = sorted(_prices_for_date(db, trade_date), key=lambda row: (row.change_percent, row.volume), reverse=True)[:limit]
    return [serialize_price(row) for row in rows]


def get_top_losers(db: Session, requested_date: date | None = None, limit: int = 10) -> list[MarketPriceResponse]:
    trade_date = resolve_market_date(db, requested_date)
    rows = sorted(_prices_for_date(db, trade_date), key=lambda row: (row.change_percent, -row.volume))[:limit]
    return [serialize_price(row) for row in rows]


def get_top_volume(db: Session, requested_date: date | None = None, limit: int = 10) -> list[MarketPriceResponse]:
    trade_date = resolve_market_date(db, requested_date)
    rows = sorted(_prices_for_date(db, trade_date), key=lambda row: row.volume, reverse=True)[:limit]
    return [serialize_price(row) for row in rows]


def get_sectors(db: Session, requested_date: date | None = None) -> list[SectorDailyStatsResponse]:
    trade_date = resolve_market_date(db, requested_date)
    canonical = canonical_prices_for_date(db, trade_date)
    if canonical:
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
                unchanged=sum(row.change == 0 for row in prices), source="canonical_selected_observations",
            ) for sector, prices in grouped.items()
        ], key=lambda row: row.average_change_percent, reverse=True)
    statement = select(SectorDailyStats).where(SectorDailyStats.trade_date == trade_date)
    if not settings.is_synthetic_environment:
        statement = statement.where(func.lower(SectorDailyStats.source) != "mock")
    rows = db.scalars(
        statement
        .order_by(SectorDailyStats.average_change_percent.desc())
    ).all()
    return [serialize_sector_stats(row) for row in rows]


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
    return CompanyDetailResponse(
        company=serialize_company(company),
        latest_price=serialize_price(latest_observation) if latest_observation else None,
    )


def get_company_history(
    db: Session,
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 365,
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
            provider_mode_warning="Current market data mode is mock. Use psxdata, yahoo, or auto mode for live/current ingestion." if settings.market_data_mode == "mock" else None,
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
    fallback_provider_active = bool(latest_run and latest_run.attempted_provider in {"auto", "psxdata"} and latest_run.used_provider == "yahoo")
    if fallback_provider_active:
        backup_warning = "Primary PSX source was unavailable. Yahoo Finance fallback data is currently in use."

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
