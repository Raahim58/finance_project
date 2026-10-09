"""Offline portfolio intelligence contracts and fixtures."""

import json
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.models.research_intelligence import ResearchJob
from app.models.intelligence_context import IntelligenceContextReceiptRecord, ContextIngestionWork
from app.schemas.research_intelligence import BatchRequest
from app.services.research_intelligence_service import event_views, company_intelligence
from app.services.research_job_service import preview_batch, enqueue_batch, job_status
from app.tests.support.research import seed


@pytest.mark.usefixtures("database")
def test_batch_preview_is_read_only_and_enqueue_is_owner_scoped_idempotent():
    with SessionLocal() as db:
        user, other, a, _ = seed(db)
        body = BatchRequest(client_request_id="request-1", instrument_ids=[a.id])
        preview = preview_batch(db, user, body)
        assert preview["maximum_calls"] == 2
        assert db.scalar(select(func.count()).select_from(ResearchJob)) == 0
        first = enqueue_batch(db, user, body)
        second = enqueue_batch(db, user, body)
        assert first["id"] == second["id"]
        with pytest.raises(HTTPException) as exc:
            job_status(db, other, first["id"])
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            enqueue_batch(db, user, body.model_copy(update={"max_calls": 15}))
        assert exc.value.status_code == 409
        company_intelligence(db, user, "AAA")
        assert db.scalar(select(func.count()).select_from(IntelligenceContextReceiptRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ContextIngestionWork)) == 0


def test_company_only_tool_boundary():
    from app.ai.tool_loop import _company_tool_allowed

    assert _company_tool_allowed("research.event_relevance", {"symbol": "AAA"})
    assert not _company_tool_allowed("portfolio.summary", {})
    assert not _company_tool_allowed("research.search", {"portfolio_id": "private"})
    assert not _company_tool_allowed("research.company_sections", {"sections": ["ips"]})


@pytest.mark.usefixtures("database")
def test_portfolio_weights_deduplicate_companies_and_use_cash_denominator(monkeypatch):
    from types import SimpleNamespace
    from app.models.portfolio import Portfolio
    from app.services import research_intelligence_service as service

    with SessionLocal() as db:
        user, other, a, b = seed(db)
        portfolio = Portfolio(user_id=user.id, name="Selected")
        db.add(portfolio)
        db.commit()
        holdings = [
            SimpleNamespace(symbol="AAA", latest_price=Decimal("10"), market_value=Decimal("100")),
            SimpleNamespace(symbol="BBB", latest_price=Decimal("10"), market_value=Decimal("200")),
        ]
        summary = SimpleNamespace(
            holdings=holdings,
            total_value=Decimal("400"),
            valuation_complete=True,
            model_dump=lambda **_: {
                "holdings": [str(h.latest_price) for h in holdings],
                "cash": "100",
                "total_value": "400",
            },
        )
        monkeypatch.setattr(service, "get_portfolio_summary", lambda *_: summary)
        shared = event_views(db)[0]
        monkeypatch.setattr(
            service,
            "company_events",
            lambda *_args, **_: [{**shared, "relationship_kind": "direct"}],
        )
        monkeypatch.setattr(
            service,
            "attach_briefs",
            lambda _db, _user, _instrument, rows: [{**r, "saved_brief": None} for r in rows],
        )
        result = service.portfolio_intelligence(db, user, portfolio.id)
        assert len(result["events"]) == 1
        assert Decimal(result["events"][0]["potentially_affected_weight"]) == Decimal("0.75")
        service.persist_snapshot(db, user, portfolio.id)
        db.commit()
        original = service.attach_briefs

        def forbid_recompute(*_):
            raise AssertionError("Current snapshot should be reused")

        monkeypatch.setattr(service, "attach_briefs", forbid_recompute)
        assert service.portfolio_intelligence(db, user, portfolio.id)["events"] == json.loads(
            json.dumps(result["events"], default=str)
        )
        monkeypatch.setattr(service, "attach_briefs", original)
        holdings[1].latest_price = None
        assert (
            service.portfolio_intelligence(db, user, portfolio.id)["events"][0][
                "potentially_affected_weight"
            ]
            is None
        )
        with pytest.raises(HTTPException) as exc:
            service.portfolio_intelligence(db, other, portfolio.id)
        assert exc.value.status_code == 404


def test_portfolio_intelligence_is_cached_per_holdings_and_limits_events(monkeypatch):
    from types import SimpleNamespace
    from app.services import research_intelligence_service as service

    service._portfolio_event_cache.clear()
    calls = []
    summary = SimpleNamespace(model_dump=lambda mode="json": {"total_value": "100"})
    monkeypatch.setattr(service, "get_portfolio_or_404", lambda *_: None)
    monkeypatch.setattr(service, "get_portfolio_summary", lambda *_: summary)

    def build(_db, _user, _portfolio_id, _summary):
        calls.append(1)
        return {"events": [{"n": i} for i in range(10)]}

    monkeypatch.setattr(service, "_portfolio_intelligence", build)
    user = SimpleNamespace(id="u1")
    assert len(service.portfolio_intelligence(None, user, "p1", 3)["events"]) == 3
    assert len(service.portfolio_intelligence(None, user, "p1", 7)["events"]) == 7
    assert len(calls) == 1
    summary.model_dump = lambda mode="json": {"total_value": "101"}
    service.portfolio_intelligence(None, user, "p1", 3)
    assert len(calls) == 2
