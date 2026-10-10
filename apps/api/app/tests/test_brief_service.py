"""Briefs are served from cache; only a changed input hash schedules (one) generation."""
import json
from datetime import UTC, datetime
from app.db.session import SessionLocal
from app.models.user import User
from app.models.research_intelligence import AIBrief
from app.services import brief_service
import pytest


def make_user(db):
    user = User(email="b@example.com", password_hash="x")
    db.add(user); db.commit(); return user


def patch(monkeypatch, inputs, config=True):
    monkeypatch.setattr(brief_service, "_gather", lambda db, user, scope, key: ([{"id": "f1", "text": "KSE up", "source": "s"}], inputs))
    monkeypatch.setattr(brief_service, "generation_config", lambda db, user: {"provider": "anthropic", "model": "m"} if config else None)


def test_validation_drops_uncited_points_and_unknown_ids():
    raw = json.dumps({"headline": "h", "summary": "s", "sections": [
        {"title": "T", "body": "ok", "question": "Why?", "tickers": ["KML", "FAKE"], "fact_ids": ["f1", "f9"]},
        {"title": "U", "body": "no cite", "fact_ids": ["f9"]}], "events": []})
    out = brief_service._valid(raw, {"f1"}, {"KML"})
    assert out["sections"] == [{"title": "T", "body": "ok", "question": "Why?", "fact_ids": ["f1"], "tickers": ["KML"]}]


@pytest.mark.usefixtures("database")
def test_cached_brief_is_served_without_scheduling_and_new_hash_schedules_once(monkeypatch):
    calls = []
    with SessionLocal() as db:
        user = make_user(db)
        patch(monkeypatch, {"trade_date": "2026-10-09"})
        first = brief_service.read(db, user, "market", schedule=lambda *a: calls.append(a))
        assert first["status"] == "generating" and len(calls) == 1
        again = brief_service.read(db, user, "market", schedule=lambda *a: calls.append(a))
        assert again["status"] == "generating" and len(calls) == 1  # no second generation for the same hash
        row = db.query(AIBrief).one()
        row.status, row.brief_json, row.facts_json, row.generated_at = "ready", json.dumps({"headline": "h", "summary": "s", "sections": [], "events": []}), "[]", datetime.now(UTC)
        db.commit()
        hit = brief_service.read(db, user, "market", schedule=lambda *a: calls.append(a))
        assert hit["status"] == "ready" and hit["current"] and len(calls) == 1
        patch(monkeypatch, {"trade_date": "2026-10-10"})  # new trading day
        stale = brief_service.read(db, user, "market", schedule=lambda *a: calls.append(a))
        assert stale["status"] == "generating" and not stale["current"] and stale["brief"]["headline"] == "h" and len(calls) == 2


@pytest.mark.usefixtures("database")
def test_no_key_means_no_generation(monkeypatch):
    with SessionLocal() as db:
        user = make_user(db)
        patch(monkeypatch, {"d": 1}, config=False)
        out = brief_service.read(db, user, "market", schedule=lambda *a: (_ for _ in ()).throw(AssertionError("scheduled")))
        assert out["status"] == "provider_unavailable"


@pytest.mark.usefixtures("database")
def test_pending_brief_poll_does_not_reassemble_facts(monkeypatch):
    with SessionLocal() as db:
        user = make_user(db)
        patch(monkeypatch, {"day": "fixture"})
        brief_service.read(db, user, "market", schedule=lambda *args: None)
        monkeypatch.setattr(brief_service, "_gather", lambda *args: (_ for _ in ()).throw(AssertionError("expensive poll")))
        result = brief_service.read(db, user, "market", schedule=lambda *args: (_ for _ in ()).throw(AssertionError("duplicate generation")))
        assert result["status"] == "generating" and not result["current"]


@pytest.mark.usefixtures("database")
def test_identical_market_briefs_generate_for_each_owner_without_holding_db_connections(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    with SessionLocal() as db:
        owners = [User(email=f"brief-{i}@example.test", password_hash="fixture") for i in range(2)]
        db.add_all(owners); db.flush()
        ids = [owner.id for owner in owners]
        for owner_id in ids:
            db.add(AIBrief(user_id=owner_id, input_hash="same-public-input", scope="market", scope_key="",
                          provider="anthropic", model="fixture", status="running"))
        db.commit()
    sessions, calls = [], []
    factory = SessionLocal
    def tracked_session():
        session = factory(); sessions.append(session); return session
    monkeypatch.setattr(brief_service, "SessionLocal", tracked_session)
    monkeypatch.setattr(brief_service, "_gather_sync", lambda *args: ([{"id":"f1","text":"Fixture context","source":"fixture"}], {}))
    monkeypatch.setattr("app.services.llm_key_service.get_decrypted_key_for_call", lambda *args: ("test-only-key", None))
    class Provider:
        async def chat_with_options(self, *args, **kwargs):
            assert all(not session.in_transaction() for session in sessions)
            calls.append(1)
            await asyncio.sleep(0)
            return SimpleNamespace(content=json.dumps({"headline":"Stored evidence", "sections":[{"title":"Context", "body":"A fixture reading.", "fact_ids":["f1"]}]}))
    monkeypatch.setattr("app.ai.providers.registry.get_provider", lambda *args: Provider())
    async def run():
        await asyncio.gather(*(brief_service.generate(owner_id, "market", "", "same-public-input") for owner_id in ids))
    asyncio.run(run())
    assert len(calls) == 2
    with SessionLocal() as db:
        assert all(row.status == "ready" for row in db.query(AIBrief).all())


def test_numeric_guard_flags_restated_figures():
    ok = {"headline": "Narrow advance", "sections": [{"title": "Breadth", "body": "One name drove roughly 3% of it."}]}
    bad = {"headline": "Index up 0.09%", "sections": [{"title": "Breadth", "body": "Up 2% and then 3%."}]}
    assert not brief_service._too_numeric(ok) and brief_service._too_numeric(bad)


def test_portfolio_facts_include_derived_analysis_inputs(monkeypatch):
    from decimal import Decimal as D
    from types import SimpleNamespace as NS
    h = lambda sym, sec, mv, dc: NS(symbol=sym, sector=sec, market_value=D(mv), day_change=D(dc), day_change_percent=D("0.5"),
                                    unrealized_gain_loss_percent=D("1"), quantity=D("1"), latest_price_date="2026-10-09")
    summary = NS(portfolio=NS(name="P"), total_value=D("1000"), day_change=D("10"), day_change_percent=D("1.0"), cash_balance=D("100"),
                 data_freshness_date="2026-10-09", data_source="x", unpriced_symbols=[], holdings=[h("AAA", "Banks", "500", "8"), h("BBB", "Cement", "400", "2")])
    monkeypatch.setattr("app.services.portfolio_service.get_portfolio_summary", lambda *a: summary)
    monkeypatch.setattr("app.services.pipeline.event_reads.event_records", lambda *a, **k: [])
    monkeypatch.setattr("app.services.market_service.get_market_overview", lambda db: NS(snapshot=NS(index_name="KSE-100", index_change_percent=D("0.2"), snapshot_date="2026-10-09", source="s")))
    facts, _ = brief_service.portfolio_facts(None, None, "id")
    text = " ".join(f["text"] for f in facts)
    assert "Concentration: cash is 10.0%" in text and "Banks 50.0%" in text and "Largest contributor" in text and "a gap of 0.8 points" in text
