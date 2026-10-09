"""Offline data health contracts and fixtures."""

from datetime import UTC, date, datetime, timedelta
import json
from types import SimpleNamespace
from sqlalchemy import select
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.models.workstation import IngestionRun
from app.services.data_health_service import source_health
from app.services.ingestion_run_service import (
    fail_ingestion_run,
    finish_ingestion_run,
    start_ingestion_run,
)
from app.services.ingestion_service import refresh_provider, run_due_ingestion_jobs
from app.services.market_ingestion import generate_mock_market_data
from app.tests.support.ingestion import _auth
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_run_accounting_supports_success_partial_and_failed():
    with SessionLocal() as db:
        success, _ = start_ingestion_run(db, job_key="test:success", run_key="1", provider="sbp")
        success = finish_ingestion_run(db, success, {"attempted": 2, "accepted": 2})
        partial, _ = start_ingestion_run(db, job_key="test:partial", run_key="1", provider="mettis")
        partial = finish_ingestion_run(
            db,
            partial,
            {
                "attempted": 3,
                "accepted": 2,
                "rejected": 1,
                "diagnostics": {"errors": ["one malformed row"]},
            },
        )
        failed, _ = start_ingestion_run(db, job_key="test:failed", run_key="1", provider="pbs")
        failed = fail_ingestion_run(db, failed.id, RuntimeError("workbook unavailable"))

        assert success.status == "success"
        assert partial.status == "partial" and partial.rejected_count == 1
        assert partial.error_message == "one malformed row"
        assert failed.status == "failed" and failed.error_message == "workbook unavailable"


def test_rejected_rows_are_retained_by_provider_refresh(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion_service._refresh_scstrade",
        lambda db: {
            "attempted": 4,
            "accepted": 3,
            "updated": 0,
            "rejected": 1,
            "diagnostics": {"errors": ["MEBL row 4: invalid close"]},
        },
    )
    with SessionLocal() as db:
        run = refresh_provider(db, "scstrade", "partial-test")
    assert run.status == "partial"
    assert (run.attempted_count, run.accepted_count, run.rejected_count) == (4, 3, 1)
    assert "invalid close" in (run.error_message or "")


def test_one_scheduled_provider_failure_does_not_block_others(monkeypatch):
    attempted: list[str] = []

    def fake_refresh(db, provider, key):
        attempted.append(provider)
        if provider == "mettis":
            raise RuntimeError("listing unavailable")
        return SimpleNamespace(id=f"run-{provider}", status="success")

    monkeypatch.setattr(settings, "scheduled_research_enabled", True)
    monkeypatch.setattr(settings, "market_data_mode", "dps")
    monkeypatch.setattr("app.services.ingestion_service.refresh_provider", fake_refresh)
    with SessionLocal() as db:
        results = run_due_ingestion_jobs(db)

    assert attempted == ["sbp", "scstrade", "pbs", "world_bank"]
    assert all(row["status"] == "success" for row in results)


def test_freshness_derivation_is_honest_about_absence_and_age():
    today = date(2026, 8, 13)
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    with SessionLocal() as db:
        generate_mock_market_data(db, days=2, end_date=today)
        price = db.scalar(select(MarketPrice).where(MarketPrice.trade_date == today))
        price.source = "dps"
        run = IngestionRun(
            job_key="refresh:dps",
            run_key="today",
            provider="dps",
            status="success",
            attempted_count=1,
            accepted_count=1,
            started_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=4),
        )
        db.add(run)
        db.commit()
        health = source_health(db, now=now)

    by_source = {row["source"]: row for row in health["sources"]}
    assert by_source["DPS"]["status"] == "healthy"
    assert by_source["Mettis"]["status"] == "never_run"
    assert by_source["PSX Announcements"]["status"] == "never_run"


def test_yahoo_fallback_does_not_report_dps_as_healthy():
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=now.date())
        for price in db.scalars(select(MarketPrice)):
            price.source = "yahoo"
        db.add(
            IngestionRun(
                job_key="refresh:auto",
                run_key="fallback",
                provider="auto",
                status="success",
                attempted_count=1,
                accepted_count=1,
                diagnostics_json=json.dumps({"used_provider": "yahoo"}),
                started_at=now,
                finished_at=now,
            )
        )
        db.commit()

        health = source_health(db, now=now)

    dps = next(row for row in health["sources"] if row["source"] == "DPS")
    assert dps["status"] == "never_run"
    assert dps["latest_data_at"] is None


def test_health_and_completeness_apis_require_auth_and_return_missing_states(client):
    assert client.get("/ingestion/health").status_code == 401
    headers = _auth(client)
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=date(2026, 8, 13))

    health = client.get("/ingestion/health", headers=headers)
    assert health.status_code == 200
    assert any(
        row["source"] == "PSX Announcements" and row["status"] == "never_run"
        for row in health.json()["sources"]
    )

    completeness = client.get("/ingestion/companies/MEBL/completeness", headers=headers)
    assert completeness.status_code == 200
    body = completeness.json()
    assert body["price"]["available"] is False
    assert body["announcements"]["available"] is False
