from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from random import Random
from types import SimpleNamespace

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.orm import Session

from app.models.market import (
    Company,
    Exchange,
    MarketIngestionRun,
    MarketPrice,
    MarketSnapshot,
    SectorDailyStats,
)
from app.services.market_numbers import safe_decimal, safe_int
from app.services.market_providers import LatestPriceRow
from app.services.canonical_market_service import (
    persist_normalized_observations,
    validate_observed_price,
)

MOCK_COMPANIES = [
    ("MEBL", "Meezan Bank Limited", "Banking"),
    ("HBL", "Habib Bank Limited", "Banking"),
    ("UBL", "United Bank Limited", "Banking"),
    ("SYS", "Systems Limited", "Technology"),
    ("NETSOL", "NetSol Technologies Limited", "Technology"),
    ("FFC", "Fauji Fertilizer Company Limited", "Fertilizer"),
    ("ENGRO", "Engro Corporation Limited", "Fertilizer"),
    ("LUCK", "Lucky Cement Limited", "Cement"),
    ("DGKC", "D.G. Khan Cement Company Limited", "Cement"),
    ("OGDC", "Oil & Gas Development Company Limited", "Oil & Gas"),
    ("PPL", "Pakistan Petroleum Limited", "Oil & Gas"),
    ("PSO", "Pakistan State Oil Company Limited", "Oil & Gas Marketing"),
    ("HUBC", "The Hub Power Company Limited", "Power"),
    ("KEL", "K-Electric Limited", "Power"),
    ("UNITY", "Unity Foods Limited", "Food & Personal Care"),
    ("ILP", "Interloop Limited", "Textile"),
    ("MCB", "MCB Bank Limited", "Banking"),
    ("BAHL", "Bank AL Habib Limited", "Banking"),
    ("NBP", "National Bank of Pakistan", "Banking"),
    ("TRG", "TRG Pakistan Limited", "Technology"),
    ("AVN", "Avanceon Limited", "Technology"),
    ("EFERT", "Engro Fertilizers Limited", "Fertilizer"),
    ("FATIMA", "Fatima Fertilizer Company Limited", "Fertilizer"),
    ("MLCF", "Maple Leaf Cement Factory Limited", "Cement"),
    ("FCCL", "Fauji Cement Company Limited", "Cement"),
    ("MARI", "Mari Energies Limited", "Oil & Gas"),
    ("SNGP", "Sui Northern Gas Pipelines Limited", "Oil & Gas Marketing"),
    ("EPCL", "Engro Polymer & Chemicals Limited", "Chemical"),
    ("LOTCHEM", "Lotte Chemical Pakistan Limited", "Chemical"),
    ("NESTLE", "Nestle Pakistan Limited", "Food & Personal Care"),
    ("MTL", "Millat Tractors Limited", "Automobile Assembler"),
    ("ATLH", "Atlas Honda Limited", "Automobile Assembler"),
    ("PAKT", "Pakistan Tobacco Company Limited", "Tobacco"),
    ("SEARL", "The Searle Company Limited", "Pharmaceuticals"),
    ("AGP", "AGP Limited", "Pharmaceuticals"),
    ("ABOT", "Abbott Laboratories Pakistan Limited", "Pharmaceuticals"),
]

BASE_PRICES = {
    "MEBL": Decimal("245.00"),
    "HBL": Decimal("128.00"),
    "UBL": Decimal("298.00"),
    "SYS": Decimal("430.00"),
    "NETSOL": Decimal("156.00"),
    "FFC": Decimal("178.00"),
    "ENGRO": Decimal("352.00"),
    "LUCK": Decimal("910.00"),
    "DGKC": Decimal("112.00"),
    "OGDC": Decimal("142.00"),
    "PPL": Decimal("118.00"),
    "PSO": Decimal("184.00"),
    "HUBC": Decimal("151.00"),
    "KEL": Decimal("5.30"),
    "UNITY": Decimal("28.00"),
    "ILP": Decimal("69.00"),
    "MCB": Decimal("232.00"), "BAHL": Decimal("118.00"), "NBP": Decimal("72.00"),
    "TRG": Decimal("63.00"), "AVN": Decimal("58.00"), "EFERT": Decimal("196.00"),
    "FATIMA": Decimal("76.00"), "MLCF": Decimal("54.00"), "FCCL": Decimal("39.00"),
    "MARI": Decimal("690.00"), "SNGP": Decimal("88.00"), "EPCL": Decimal("47.00"),
    "LOTCHEM": Decimal("19.00"), "NESTLE": Decimal("7050.00"), "MTL": Decimal("705.00"),
    "ATLH": Decimal("890.00"), "PAKT": Decimal("1320.00"), "SEARL": Decimal("92.00"),
    "AGP": Decimal("134.00"), "ABOT": Decimal("980.00"),
}


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def percent(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def decimalize(value: Decimal | int | float | str | None, default: Decimal = Decimal("0")) -> Decimal:
    return safe_decimal(value) or default


def sanitize_market_price_values(price: MarketPrice | LatestPriceRow) -> dict[str, Decimal | int | None]:
    close = money(
        decimalize(
            getattr(price, "close", None),
            safe_decimal(getattr(price, "previous_close", None))
            or safe_decimal(getattr(price, "open", None))
            or Decimal("0"),
        )
    )
    previous_close = money(decimalize(getattr(price, "previous_close", None), close))
    open_price = money(decimalize(getattr(price, "open", None), previous_close))
    high = money(decimalize(getattr(price, "high", None), max(open_price, close)))
    low = money(decimalize(getattr(price, "low", None), min(open_price, close)))
    volume = safe_int(getattr(price, "volume", None)) or 0
    change = money(close - previous_close)
    change_percent = percent((change / previous_close) * Decimal("100")) if previous_close != 0 else Decimal("0")
    value = money(decimalize(getattr(price, "value", None), close * Decimal(volume)))
    market_cap = safe_decimal(getattr(price, "market_cap", None))
    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "previous_close": previous_close,
        "change": change,
        "change_percent": change_percent,
        "volume": volume,
        "value": value,
        "market_cap": market_cap,
    }


def trading_days_ending(end_date: date, days: int) -> list[date]:
    dates: list[date] = []
    cursor = end_date
    while len(dates) < days:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(dates))


def ensure_psx_exchange(db: Session) -> Exchange:
    exchange = db.scalar(select(Exchange).where(Exchange.code == "PSX"))
    if not exchange:
        exchange = Exchange(code="PSX", name="Pakistan Stock Exchange", timezone="Asia/Karachi")
        db.add(exchange)
        db.flush()
    return exchange


def ensure_mock_companies(db: Session) -> list[Company]:
    from app.models.workstation import Instrument

    exchange = ensure_psx_exchange(db)

    companies: list[Company] = []
    for symbol, name, sector in MOCK_COMPANIES:
        company = db.scalar(select(Company).where(Company.symbol == symbol))
        if not company:
            company = Company(
                symbol=symbol,
                name=name,
                sector=sector,
                exchange_id=exchange.id,
                psx_url=f"https://dps.psx.com.pk/company/{symbol}",
                description=f"Mock Phase 2 company profile for {name}.",
            )
            db.add(company)
            db.flush()
        else:
            company.name = name
            company.sector = sector
            company.exchange_id = exchange.id
            company.is_active = True
        instrument = db.scalar(select(Instrument).where(Instrument.company_id == company.id))
        if instrument is None:
            db.add(Instrument(company_id=company.id, symbol=company.symbol, name=company.name, instrument_type="equity", currency="PKR", country="PK", sector=company.sector, metadata_json='{"data_classification":"synthetic_demo"}'))
        else:
            instrument.name = company.name
            instrument.sector = company.sector
        companies.append(company)

    return companies


def get_active_company_symbols(db: Session) -> list[str]:
    return list(
        db.scalars(select(Company.symbol).where(Company.is_active.is_(True)).order_by(Company.symbol.asc()))
    )


def upsert_company_from_price_row(db: Session, row: LatestPriceRow) -> Company:
    from app.models.workstation import Instrument

    exchange = ensure_psx_exchange(db)
    company = db.scalar(select(Company).where(Company.symbol == row.symbol))
    if not company:
        company = Company(
            symbol=row.symbol,
            name=row.name or row.symbol,
            sector=row.sector or "Unknown",
            exchange_id=exchange.id,
            psx_url=f"https://dps.psx.com.pk/company/{row.symbol}",
            description=f"Market data company record for {row.symbol}.",
            is_active=True,
        )
        db.add(company)
        db.flush()

    if row.name:
        company.name = row.name
    elif not company.name:
        company.name = row.symbol
    if row.sector:
        company.sector = row.sector
    elif not company.sector:
        company.sector = "Unknown"
    company.exchange_id = exchange.id
    company.is_active = True
    db.flush()
    instrument = db.scalar(select(Instrument).where(Instrument.company_id == company.id))
    if instrument is None:
        db.add(Instrument(company_id=company.id, symbol=company.symbol, name=company.name, instrument_type="equity", currency="PKR", country="PK", sector=company.sector))
    else:
        instrument.name = company.name
        instrument.sector = company.sector
    db.flush()
    return company


def clear_mock_market_data(db: Session) -> None:
    db.execute(delete(SectorDailyStats).where(SectorDailyStats.source == "mock"))
    db.execute(delete(MarketSnapshot).where(MarketSnapshot.source == "mock"))
    db.execute(delete(MarketPrice).where(MarketPrice.source == "mock"))


def generate_mock_market_data(db: Session, days: int = 365, end_date: date | None = None) -> dict[str, int]:
    if days < 1:
        raise ValueError("days must be at least 1")

    end = end_date or date.today()
    companies = ensure_mock_companies(db)
    clear_mock_market_data(db)

    dates = trading_days_ending(end, days)
    previous_closes = {company.symbol: BASE_PRICES[company.symbol] for company in companies}
    random = Random(202602)

    price_rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        # Bounded factor-style demo returns: a modest common drift, a small
        # mean-zero cycle and shared/issuer shocks. The previous ±1.1% daily
        # cycle plus permanent symbol bias annualized into unrealistic return
        # estimates and made optimizer trade-offs look erratic.
        market_cycle = Decimal(str(((index % 31) - 15) / 20000))
        market_drift = Decimal("0.00035")
        common_market_shock = Decimal(str(random.uniform(-0.006, 0.006)))
        for company in companies:
            sector_bias = Decimal(str((sum(ord(char) for char in company.sector) % 9 - 4) / 50000))
            symbol_bias = Decimal(str((sum(ord(char) for char in company.symbol) % 7 - 3) / 75000))
            noise = Decimal(str(random.uniform(-0.008, 0.008)))
            change_ratio = market_drift + market_cycle + common_market_shock + sector_bias + symbol_bias + noise

            previous_close = previous_closes[company.symbol]
            close = max(Decimal("1.0000"), money(previous_close * (Decimal("1") + change_ratio)))
            open_price = money(previous_close * (Decimal("1") + Decimal(str(random.uniform(-0.006, 0.006)))))
            high = money(max(open_price, close) * (Decimal("1") + Decimal(str(random.uniform(0.001, 0.018)))))
            low = money(min(open_price, close) * (Decimal("1") - Decimal(str(random.uniform(0.001, 0.018)))))
            change = money(close - previous_close)
            change_percent = percent((change / previous_close) * Decimal("100"))
            base_volume = 150_000 + (sum(ord(char) for char in company.symbol) * 1_100)
            volume = int(base_volume * (1 + (index % 17) / 10) * random.uniform(0.75, 1.45))
            traded_value = money(close * Decimal(volume))

            price_rows.append(
                {
                    "company_id": company.id,
                    "symbol": company.symbol,
                    "trade_date": trade_date,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "previous_close": previous_close,
                    "change": change,
                    "change_percent": change_percent,
                    "volume": volume,
                    "value": traded_value,
                    "market_cap": money(close * Decimal(80_000_000 + (sum(ord(char) for char in company.symbol) * 1_000_000))),
                    "source": "mock",
                }
            )
            previous_closes[company.symbol] = close

    # Executemany avoids thousands of ORM unit-of-work objects in demo/test seeds.
    # The generator is deterministic and no caller needs the inserted instances.
    db.execute(insert(MarketPrice), price_rows)
    stats_count = compute_market_stats(db, source="mock")
    db.commit()
    return {"companies": len(companies), "prices": len(price_rows), "derived_stats": stats_count}


def cleanup_invalid_market_prices(db: Session) -> int:
    rows = db.execute(
        text(
            """
            SELECT id, open, high, low, close, previous_close, change, change_percent, volume, value, market_cap
            FROM market_prices
            """
        )
    ).mappings().all()
    updates = 0
    for price in rows:
        cleaned = sanitize_market_price_values(SimpleNamespace(**price))
        changed = any(price[field] != cleaned[field] for field in cleaned)
        if changed:
            db.execute(
                text(
                    """
                    UPDATE market_prices
                    SET open = :open,
                        high = :high,
                        low = :low,
                        close = :close,
                        previous_close = :previous_close,
                        change = :change,
                        change_percent = :change_percent,
                        volume = :volume,
                        value = :value,
                        market_cap = :market_cap,
                        ingested_at = :ingested_at
                    WHERE id = :id
                    """
                ),
                {
                    "id": price["id"],
                    "open": str(cleaned["open"]),
                    "high": str(cleaned["high"]),
                    "low": str(cleaned["low"]),
                    "close": str(cleaned["close"]),
                    "previous_close": str(cleaned["previous_close"]),
                    "change": str(cleaned["change"]),
                    "change_percent": str(cleaned["change_percent"]),
                    "volume": cleaned["volume"],
                    "value": str(cleaned["value"]),
                    "market_cap": None if cleaned["market_cap"] is None else str(cleaned["market_cap"]),
                    "ingested_at": datetime.now(UTC),
                },
            )
            updates += 1

    if updates:
        db.commit()
    return updates


def persist_market_data(db: Session, *, latest_prices: list[LatestPriceRow], source: str) -> dict[str, int | date | None]:
    if not latest_prices:
        raise ValueError("latest_prices must not be empty")

    company_count = 0
    price_count = 0
    touched_dates: set[date] = set()

    for row in latest_prices:
        cleaned, issues = validate_observed_price(row)
        if issues or cleaned is None:
            continue
        company = upsert_company_from_price_row(db, row)
        company_count += 1

        price = db.scalar(
            select(MarketPrice).where(
                MarketPrice.symbol == row.symbol,
                MarketPrice.trade_date == row.trade_date,
                MarketPrice.source == source,
            )
        )
        if not price:
            price = MarketPrice(
                company_id=company.id,
                symbol=row.symbol,
                trade_date=row.trade_date,
                open=cleaned["open"],
                high=cleaned["high"],
                low=cleaned["low"],
                close=cleaned["close"],
                previous_close=cleaned["previous_close"],
                change=cleaned["change"],
                change_percent=cleaned["change_percent"],
                volume=cleaned["volume"],
                value=cleaned["value"],
                market_cap=cleaned["market_cap"],
                source=source,
                source_url=row.source_url,
            )
            db.add(price)
        else:
            price.company_id = company.id
            price.open = cleaned["open"]
            price.high = cleaned["high"]
            price.low = cleaned["low"]
            price.close = cleaned["close"]
            price.previous_close = cleaned["previous_close"]
            price.change = cleaned["change"]
            price.change_percent = cleaned["change_percent"]
            price.volume = cleaned["volume"]
            price.value = cleaned["value"]
            price.market_cap = cleaned["market_cap"]
            price.source_url = row.source_url
            price.ingested_at = datetime.now(UTC)

        touched_dates.add(row.trade_date)
        price_count += 1

    canonical_count, rejected_count = persist_normalized_observations(db, latest_prices, source)

    db.flush()

    derived_stats = 0
    for trade_date in sorted(touched_dates):
        derived_stats += compute_market_stats(db, source=source, target_date=trade_date)

    latest_trade_date = max(touched_dates) if touched_dates else None
    db.commit()
    return {
        "companies": company_count,
        "prices": price_count,
        "canonical_observations": canonical_count,
        "rejected": rejected_count,
        "derived_stats": derived_stats,
        "latest_trade_date": latest_trade_date,
    }


def compute_market_stats(
    db: Session,
    source: str = "mock",
    target_date: date | None = None,
) -> int:
    if target_date:
        db.execute(delete(SectorDailyStats).where(SectorDailyStats.source == source, SectorDailyStats.trade_date == target_date))
        db.execute(delete(MarketSnapshot).where(MarketSnapshot.source == source, MarketSnapshot.snapshot_date == target_date))
    else:
        db.execute(delete(SectorDailyStats).where(SectorDailyStats.source == source))
        db.execute(delete(MarketSnapshot).where(MarketSnapshot.source == source))

    query = (
        select(
            MarketPrice.trade_date,
            Company.sector,
            MarketPrice.volume,
            MarketPrice.value,
            MarketPrice.change_percent,
            MarketPrice.change,
        )
        .join(Company, Company.id == MarketPrice.company_id)
        .where(MarketPrice.source == source)
    )
    if target_date:
        query = query.where(MarketPrice.trade_date == target_date)

    prices_by_date: dict[date, list[object]] = {}
    for row in db.execute(query):
        prices_by_date.setdefault(row.trade_date, []).append(row)

    snapshot_rows: list[dict[str, object]] = []
    sector_rows: list[dict[str, object]] = []
    for trade_date, prices in prices_by_date.items():
        total_volume = sum(row.volume for row in prices)
        total_value = sum((row.value for row in prices), Decimal("0"))
        avg_change_percent = sum((row.change_percent for row in prices), Decimal("0")) / Decimal(len(prices))

        # A constituent average is demo data, not an observed index. Never label it
        # as KSE-100 for a live source; real snapshots are inserted only by an
        # index provider carrying its own artifact/provenance.
        if source == "mock":
            index_value = money(45_000 + (avg_change_percent * Decimal("85")) + Decimal(len(prices) * 10))
            index_change = money(avg_change_percent * Decimal("85"))
            snapshot_rows.append(
                {
                    "snapshot_date": trade_date,
                    "index_name": "KSE-100 Mock",
                    "index_value": index_value,
                    "index_change": index_change,
                    "index_change_percent": percent(avg_change_percent),
                    "total_volume": total_volume,
                    "total_value": money(total_value),
                    "source": source,
                }
            )

        sector_prices_by_name: dict[str, list[object]] = {}
        for price in prices:
            sector_prices_by_name.setdefault(price.sector, []).append(price)
        for sector, sector_prices in sector_prices_by_name.items():
            sector_avg = sum((price.change_percent for price in sector_prices), Decimal("0")) / Decimal(
                len(sector_prices)
            )
            sector_rows.append(
                {
                    "sector": sector,
                    "trade_date": trade_date,
                    "total_volume": sum(price.volume for price in sector_prices),
                    "total_value": money(sum((price.value for price in sector_prices), Decimal("0"))),
                    "average_change_percent": percent(sector_avg),
                    "advancers": sum(1 for price in sector_prices if price.change > 0),
                    "decliners": sum(1 for price in sector_prices if price.change < 0),
                    "unchanged": sum(1 for price in sector_prices if price.change == 0),
                    "source": source,
                }
            )

    if snapshot_rows:
        db.execute(insert(MarketSnapshot), snapshot_rows)
    if sector_rows:
        db.execute(insert(SectorDailyStats), sector_rows)
    db.commit()
    return len(snapshot_rows) + len(sector_rows)


def record_market_ingestion_run(
    db: Session,
    *,
    mode: str,
    attempted_provider: str,
    used_provider: str | None,
    status: str,
    started_at: datetime,
    latest_trade_date: date | None = None,
    records_written: int = 0,
    message: str | None = None,
) -> MarketIngestionRun:
    run = MarketIngestionRun(
        mode=mode,
        attempted_provider=attempted_provider,
        used_provider=used_provider,
        status=status,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        latest_trade_date=latest_trade_date,
        records_written=records_written,
        message=message,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_market_data_cycle(db: Session, mode: str) -> MarketIngestionRun:
    from app.services.market_providers import get_market_data_provider

    started_at = datetime.now(UTC)
    provider = get_market_data_provider(mode)
    try:
        result = provider.refresh_latest(db)
        latest_trade_date = result.get("latest_trade_date")
        if latest_trade_date is None and result.get("used_provider"):
            latest_trade_date = db.scalar(
                select(func.max(MarketPrice.trade_date)).where(MarketPrice.source == result["used_provider"])
            )
        return record_market_ingestion_run(
            db,
            mode=provider.mode,
            attempted_provider=str(result.get("attempted_provider", provider.source)),
            used_provider=str(result.get("used_provider", provider.source)),
            status="success",
            started_at=started_at,
            latest_trade_date=latest_trade_date if isinstance(latest_trade_date, date) else None,
            records_written=int(result.get("prices", 0)),
            message=str(result.get("message", f"Refreshed market data via {provider.source}.")),
        )
    except Exception as exc:
        db.rollback()
        return record_market_ingestion_run(
            db,
            mode=provider.mode,
            attempted_provider=provider.source,
            used_provider=None,
            status="failed",
            started_at=started_at,
            records_written=0,
            message=str(exc),
        )
