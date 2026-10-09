"""Briefs are served from cache; only a changed input hash schedules (one) generation."""
import json
from datetime import UTC, datetime
from app.db.session import SessionLocal
from app.models.user import User
from app.models.research_intelligence import AIBrief
from app.services import brief_service


def make_user(db):
    user = User(email="b@example.com", password_hash="x")
    db.add(user); db.commit(); return user


def patch(monkeypatch, inputs, config=True):
    monkeypatch.setattr(brief_service, "_gather", lambda db, user, scope, key: ([{"id": "f1", "text": "KSE up", "source": "s"}], inputs))
    monkeypatch.setattr(brief_service, "generation_config", lambda db, user: {"provider": "anthropic", "model": "m"} if config else None)


def test_validation_drops_uncited_points_and_unknown_ids():
    raw = json.dumps({"headline": "h", "summary": "s", "points": [
        {"text": "ok", "fact_ids": ["f1", "f9"]}, {"text": "no cite", "fact_ids": ["f9"]}], "watch": []})
    out = brief_service._valid(raw, {"f1"})
    assert out["points"] == [{"text": "ok", "fact_ids": ["f1"]}]


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
        row.status, row.brief_json, row.facts_json, row.generated_at = "ready", json.dumps({"headline": "h", "summary": "s", "points": [], "watch": []}), "[]", datetime.now(UTC)
        db.commit()
        hit = brief_service.read(db, user, "market", schedule=lambda *a: calls.append(a))
        assert hit["status"] == "ready" and hit["current"] and len(calls) == 1
        patch(monkeypatch, {"trade_date": "2026-10-10"})  # new trading day
        stale = brief_service.read(db, user, "market", schedule=lambda *a: calls.append(a))
        assert stale["status"] == "generating" and not stale["current"] and stale["brief"]["headline"] == "h" and len(calls) == 2


def test_no_key_means_no_generation(monkeypatch):
    with SessionLocal() as db:
        user = make_user(db)
        patch(monkeypatch, {"d": 1}, config=False)
        out = brief_service.read(db, user, "market", schedule=lambda *a: (_ for _ in ()).throw(AssertionError("scheduled")))
        assert out["status"] == "provider_unavailable"
