"""Offline market contracts and fixtures."""

from datetime import date
from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data

import json
from decimal import Decimal
from sqlalchemy import select
from app.models.workstation import Instrument, CorporateAction, SourceArtifact
from app.services.market_ingestion import persist_market_data
from app.services.market_providers import LatestPriceRow


def seed_split(db):
    for day, close in [
        (date(2026, 1, 1), "500"),
        (date(2026, 1, 2), "102"),
        (date(2026, 1, 5), "104"),
    ]:
        persist_market_data(
            db,
            latest_prices=[
                LatestPriceRow(
                    symbol="TEST",
                    trade_date=day,
                    close=Decimal(close),
                    previous_close=Decimal(close),
                    open=Decimal(close),
                    high=Decimal(close),
                    low=Decimal(close),
                    volume=10,
                    name="Synthetic split test",
                    sector="Test",
                    source_url="https://example.com/fixture",
                )
            ],
            source="dps",
        )
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == "TEST"))
    artifact = db.scalar(select(SourceArtifact))
    action = CorporateAction(
        instrument_id=instrument.id,
        action_type="stock_split",
        effective_date=date(2026, 1, 2),
        artifact_id=artifact.id,
        details_json=json.dumps(
            {"old_shares": "1", "new_shares": "5", "verification": "source_reviewed"}
        ),
    )
    db.add(action)
    db.flush()
    return action


def _seed_companies():
    with SessionLocal() as db:
        generate_mock_market_data(db, days=2, end_date=date(2026, 6, 30))
