"""Offline allocation verification tools contracts and fixtures."""

from datetime import UTC, datetime
from decimal import Decimal
from sqlalchemy import func, select
from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.models.user import User
from app.models.workstation import AllocationSet, Instrument
from app.tools import build_tool_registry
from app.tools.registry import expand_model_data
from app.tests.support.tools import _seed, _counts
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_allocation_verification_uses_stored_values_without_financial_writes(monkeypatch):
    seeded, user_id = _seed(monkeypatch)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        before = _counts(db)
        result = build_tool_registry().invoke(
            "allocation.verify",
            db,
            user,
            {
                "portfolio_id": seeded["portfolio_id"],
                "allowed_instrument_ids": [instrument.id],
                "proposal": {
                    "legs": [
                        {
                            "instrument_id": instrument.id,
                            "side": "buy",
                            "gross_amount": "1000",
                        }
                    ],
                    "rationale": "Test-only candidate",
                },
            },
        )
        assert result["status"] == "ok"
        data = expand_model_data(result["data"])
        assert data["financial_state_mutated"] is False
        assert data["legs"][0]["price"] == str(
            db.execute(
                select(MarketPrice.close)
                .where(MarketPrice.symbol == "MEBL")
                .order_by(MarketPrice.trade_date.desc())
                .limit(1)
            ).scalar_one()
        )
        assert _counts(db) == before


def test_verifier_separates_acceptance_freshness_and_modeled_goal(monkeypatch):
    from app.models.workstation import AnalysisRun, PortfolioIPSVersion, ScenarioRun
    from app.models.portfolio import Portfolio
    from app.reasoning.allocation import AllocationProposal
    from app.services import allocation_verification as service
    from app.services.canonical_market_service import latest_price

    seeded, user_id = _seed(monkeypatch)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        portfolio = db.get(Portfolio, seeded["portfolio_id"])
        version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id)
        version.constraints_json = "{}"
        version.required_return = Decimal(
            "100"
        )  # deliberately infeasible test hurdle, not a forecast
        db.commit()
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        price = latest_price(db, instrument.symbol)

        class Clock:
            @staticmethod
            def now(_tz):
                return datetime.combine(price.trade_date, datetime.min.time(), tzinfo=UTC)

        monkeypatch.setattr(service, "datetime", Clock)
        proposal = AllocationProposal.model_validate(
            {
                "legs": [
                    {
                        "instrument_id": instrument.id,
                        "side": "buy",
                        "gross_amount": str(price.close * 2),
                    }
                ]
            }
        )
        before = {
            model: db.scalar(select(func.count()).select_from(model))
            for model in (AnalysisRun, AllocationSet, ScenarioRun)
        }
        result = service.verify_allocation(db, user, portfolio.id, proposal, [instrument.id])
        assert result["accepted"] is True, result["errors"]
        assert result["checks"]["arithmetic_funding"]["status"] == "accepted"
        assert result["checks"]["modeled_goal"]["status"] == "below"
        assert result["checks"]["modeled_goal"]["shortfall"] > 0
        assert result["checks"]["price_freshness"]["status"] == "current"
        assert result["evidence_readiness"]["optimality"] == "not_established"
        assert result["legs"][0]["quantity"] == "2"

        # Advance using the same session policy, not an arbitrary stale-day cutoff.
        class LaterClock:
            @staticmethod
            def now(_tz):
                from datetime import timedelta

                return datetime.combine(
                    price.trade_date, datetime.min.time(), tzinfo=UTC
                ) + timedelta(days=7)

        monkeypatch.setattr(service, "datetime", LaterClock)
        stale = service.verify_allocation(db, user, portfolio.id, proposal, [instrument.id])
        assert stale["accepted"] is True
        assert stale["checks"]["price_freshness"]["status"] == "stale"
        assert stale["evidence_readiness"]["actionable_recommendation_eligible"] is False
        with monkeypatch.context() as scoped:
            original_summary = service.get_portfolio_summary
            scoped.setattr(
                service,
                "get_portfolio_summary",
                lambda *args: original_summary(*args).model_copy(
                    update={"valuation_complete": False, "unpriced_symbols": ["MEBL"]}
                ),
            )
            incomplete = service.verify_allocation(
                db, user, portfolio.id, proposal, [instrument.id]
            )
            assert incomplete["accepted"] is False
            assert "incomplete_portfolio_valuation" in incomplete["errors"]
            assert incomplete["evidence_readiness"]["actionable_recommendation_eligible"] is False
        with monkeypatch.context() as scoped:
            original_price = service.latest_price
            scoped.setattr(
                service,
                "latest_price",
                lambda session, symbol: None
                if symbol == "MEBL"
                else original_price(session, symbol),
            )
            unavailable = service.verify_allocation(
                db, user, portfolio.id, proposal, [instrument.id]
            )
            assert unavailable["accepted"] is False
            assert unavailable["checks"]["price_freshness"]["status"] == "unavailable"
            assert "missing_instrument_or_price" in unavailable["errors"]
        portfolio.selected_ips_version_id = None
        db.commit()
        missing = service.verify_allocation(db, user, portfolio.id, proposal, [instrument.id])
        assert missing["accepted"] is False
        assert "confirmed_ips_missing" in missing["errors"]
        assert missing["checks"]["modeled_goal"]["status"] == "unavailable"
        for model, count in before.items():
            assert db.scalar(select(func.count()).select_from(model)) == count
