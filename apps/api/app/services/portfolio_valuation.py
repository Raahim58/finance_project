from datetime import date

from sqlalchemy.orm import Session

from app.services.canonical_market_service import latest_price as canonical_latest_price


def latest_price_for_symbol(db: Session, symbol: str):
    return canonical_latest_price(db, symbol)


def price_for_symbol_on_or_before(db: Session, symbol: str, target_date: date):
    return canonical_latest_price(db, symbol, target_date)
