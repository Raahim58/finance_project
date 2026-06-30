from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from random import Random

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.market import Company, Exchange, MarketPrice, MarketSnapshot, SectorDailyStats

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
}


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def percent(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def trading_days_ending(end_date: date, days: int) -> list[date]:
    dates: list[date] = []
    cursor = end_date
    while len(dates) < days:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(dates))


def ensure_mock_companies(db: Session) -> list[Company]:
    exchange = db.scalar(select(Exchange).where(Exchange.code == "PSX"))
    if not exchange:
        exchange = Exchange(code="PSX", name="Pakistan Stock Exchange", timezone="Asia/Karachi")
        db.add(exchange)
        db.flush()

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
        companies.append(company)

    return companies


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

    price_count = 0
    for index, trade_date in enumerate(dates):
        market_cycle = Decimal(str(((index % 23) - 11) / 1000))
        for company in companies:
            sector_bias = Decimal(str((sum(ord(char) for char in company.sector) % 9 - 4) / 2000))
            symbol_bias = Decimal(str((sum(ord(char) for char in company.symbol) % 7 - 3) / 3000))
            noise = Decimal(str(random.uniform(-0.018, 0.018)))
            change_ratio = market_cycle + sector_bias + symbol_bias + noise

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

            db.add(
                MarketPrice(
                    company_id=company.id,
                    symbol=company.symbol,
                    trade_date=trade_date,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    previous_close=previous_close,
                    change=change,
                    change_percent=change_percent,
                    volume=volume,
                    value=traded_value,
                    source="mock",
                )
            )
            previous_closes[company.symbol] = close
            price_count += 1

    db.flush()
    stats_count = compute_market_stats(db, source="mock")
    db.commit()
    return {"companies": len(companies), "prices": price_count, "derived_stats": stats_count}


def compute_market_stats(
    db: Session,
    source: str = "mock",
    target_date: date | None = None,
) -> int:
    if target_date:
        dates = [target_date]
        db.execute(delete(SectorDailyStats).where(SectorDailyStats.source == source, SectorDailyStats.trade_date == target_date))
        db.execute(delete(MarketSnapshot).where(MarketSnapshot.source == source, MarketSnapshot.snapshot_date == target_date))
    else:
        dates = list(db.scalars(select(MarketPrice.trade_date).where(MarketPrice.source == source).distinct()))
        db.execute(delete(SectorDailyStats).where(SectorDailyStats.source == source))
        db.execute(delete(MarketSnapshot).where(MarketSnapshot.source == source))

    derived_count = 0
    for trade_date in dates:
        prices = list(
            db.scalars(
                select(MarketPrice).where(MarketPrice.source == source, MarketPrice.trade_date == trade_date)
            )
        )
        if not prices:
            continue

        total_volume = sum(price.volume for price in prices)
        total_value = sum((price.value for price in prices), Decimal("0"))
        avg_change_percent = sum((price.change_percent for price in prices), Decimal("0")) / Decimal(len(prices))
        index_value = money(45_000 + (avg_change_percent * Decimal("85")) + Decimal(len(prices) * 10))
        index_change = money(avg_change_percent * Decimal("85"))

        db.add(
            MarketSnapshot(
                snapshot_date=trade_date,
                index_name="KSE-100 Mock",
                index_value=index_value,
                index_change=index_change,
                index_change_percent=percent(avg_change_percent),
                total_volume=total_volume,
                total_value=money(total_value),
                source=source,
            )
        )
        derived_count += 1

        sector_names = {
            row[0]
            for row in db.execute(
                select(Company.sector)
                .join(MarketPrice, MarketPrice.company_id == Company.id)
                .where(MarketPrice.source == source, MarketPrice.trade_date == trade_date)
            )
        }
        for sector in sector_names:
            sector_prices = list(
                db.scalars(
                    select(MarketPrice)
                    .join(Company, Company.id == MarketPrice.company_id)
                    .where(
                        MarketPrice.source == source,
                        MarketPrice.trade_date == trade_date,
                        Company.sector == sector,
                    )
                )
            )
            if not sector_prices:
                continue
            sector_avg = sum((price.change_percent for price in sector_prices), Decimal("0")) / Decimal(
                len(sector_prices)
            )
            db.add(
                SectorDailyStats(
                    sector=sector,
                    trade_date=trade_date,
                    total_volume=sum(price.volume for price in sector_prices),
                    total_value=money(sum((price.value for price in sector_prices), Decimal("0"))),
                    average_change_percent=percent(sector_avg),
                    advancers=sum(1 for price in sector_prices if price.change > 0),
                    decliners=sum(1 for price in sector_prices if price.change < 0),
                    unchanged=sum(1 for price in sector_prices if price.change == 0),
                    source=source,
                )
            )
            derived_count += 1

    db.commit()
    return derived_count
