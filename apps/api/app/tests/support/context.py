"""Offline context contracts and fixtures."""

from __future__ import annotations
import json
from datetime import UTC, date, datetime
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.portfolio import Portfolio
from app.models.user import User
from app.models.workstation import Instrument, PortfolioIPSVersion
from app.schemas.intelligence_context import (
    ContextScope,
    ContextSectionName,
    IntelligenceContextRequest,
)
from app.services.market_ingestion import generate_mock_market_data


def _seed_user_and_market(email: str = "context@example.com", *, end_date: date | None = None) -> tuple[str, str]:
    with SessionLocal() as db:
        generate_mock_market_data(db, days=5, end_date=end_date or date.today())
        user = User(email=email, password_hash="unused")
        db.add(user)
        db.commit()
        instrument_id = db.scalar(select(Instrument.id).where(Instrument.symbol == "MEBL"))
        return user.id, instrument_id


def _company_request(*sections: ContextSectionName) -> IntelligenceContextRequest:
    return IntelligenceContextRequest(
        symbol="MEBL",
        scope=ContextScope.COMPANY_INTELLIGENCE,
        sections=sections,
    )


def _confirmed_portfolio(user_id: str) -> str:
    with SessionLocal() as db:
        portfolio = Portfolio(user_id=user_id, name="Selected mandate")
        db.add(portfolio)
        db.flush()
        ips = PortfolioIPSVersion(
            portfolio_id=portfolio.id,
            version=1,
            status="confirmed",
            constraints_json=json.dumps(
                {"risk_tolerance": "conservative", "max_instrument_weight": 0.10}
            ),
            confirmed_at=datetime.now(UTC),
        )
        db.add(ips)
        db.flush()
        portfolio.selected_ips_version_id = ips.id
        db.commit()
        return portfolio.id
