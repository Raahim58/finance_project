"""Offline context ingestion contracts and fixtures."""

from __future__ import annotations
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.pipeline import IngestionStageRun
from app.models.intelligence_context import (
    ContextDeficiencyRecord,
    ContextIngestionWork,
    ContextRefreshNotification,
)
from app.models.market import MarketPrice
from app.models.user import User
from app.models.workstation import (
    CompanyScreeningSnapshot,
    IngestionCoverage,
    IngestionRun,
    MacroObservation,
    StandardizedFinancialFact,
)
from app.schemas.intelligence_context import ContextSectionName
from app.services.context_builder import ContextBuilder
from app.services.context_deficiency_bridge import ContextDeficiencyBridge
from app.services.context_ingestion_coordinator import DatabaseIngestionCoordinator
from app.services.context_refresh_service import reconcile_pending_contexts
from app.tests.support.context import _seed_user_and_market, _company_request
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_production_bridge_queues_company_fact_stage_runs_and_tracks_coverage():
    user_id, instrument_id = _seed_user_and_market()
    request = _company_request(ContextSectionName.COMPANY_FACTS)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = ContextBuilder().build(db, user, request)
        bridge = ContextDeficiencyBridge.production(db, user)
        refreshing, refresh = bridge.record_and_schedule(db, user, request, context)
        assert refresh is not None
        assert refreshing.status == "refreshing"
        stage_runs = list(db.scalars(select(IngestionStageRun)))
        assert {run.stage for run in stage_runs} == {"broad_fundamentals", "reports"}
        work = db.scalar(select(ContextIngestionWork))
        links = json.loads(work.linked_work_json)
        assert work.family == "company_reports"
        assert {item["kind"] for item in links} == {"coverage", "pipeline_run"}
        coverage_rows = list(
            db.scalars(
                select(IngestionCoverage).where(
                    IngestionCoverage.id.in_(
                        [item["id"] for item in links if item["kind"] == "coverage"]
                    )
                )
            )
        )
        assert {row.dataset_type for row in coverage_rows} == {"standardized_fundamentals"}
        for run in stage_runs:
            run.status = "completed"

        for row in coverage_rows:
            row.status = "complete"
            row.item_count = 1
        db.add(
            StandardizedFinancialFact(
                instrument_id=instrument_id,
                metric="revenue",
                period_type="annual",
                period_key="2025",
                period_end=date(2025, 12, 31),
                value=Decimal("100"),
                unit="PKR",
                currency="PKR",
                source="dps",
                source_url="https://dps.psx.com.pk/company/MEBL",
                quality_status="observed",
            )
        )
        db.commit()
        coordinator = DatabaseIngestionCoordinator(db, user_id=user.id)
        assert coordinator.status(work.id).state == "succeeded"
        notifications: list[str] = []
        sweep = reconcile_pending_contexts(
            db, notify=lambda _user_id, value: notifications.append(value.context_id)
        )
        db.refresh(refresh)
        assert sweep.rebuilt == 1
        assert refresh.status == "rebuilt"
        assert refresh.rebuild_count == 1
        assert notifications == [context.context_id]
        # Completing capture does not certify the secondary fiscal period,
        # units or reporting basis. The verified financial gap remains open.
        assert db.scalar(select(ContextDeficiencyRecord)).status == "refreshing"
        rebuilt = ContextBuilder().build(db, user, request)
        financial = rebuilt.sections[ContextSectionName.COMPANY_FACTS]
        assert financial.data["fundamentals"] == []
        assert (
            financial.data["financial_evidence_gaps"][0]["code"]
            == "unverified_secondary_financials"
        )
        notification = db.scalar(select(ContextRefreshNotification))
        assert notification.context_id == context.context_id
        assert notification.status == "delivered"
        assert notification.delivered_at is not None


def test_production_bridge_links_current_market_gap_to_next_live_scheduler_run():
    user_id, _ = _seed_user_and_market()
    request = _company_request(ContextSectionName.MARKET_RISK)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        db.query(MarketPrice).filter(MarketPrice.symbol == "MEBL").delete()
        db.commit()
        context = ContextBuilder().build(db, user, request)
        assert any(item.category == "market_price" for item in context.deficiencies)
        _, refresh = ContextDeficiencyBridge.production(db, user).record_and_schedule(
            db, user, request, context
        )
        assert refresh is not None
        work = db.scalar(
            select(ContextIngestionWork)
            .join(
                ContextDeficiencyRecord,
                ContextDeficiencyRecord.id == ContextIngestionWork.deficiency_id,
            )
            .where(ContextDeficiencyRecord.category == "market_price")
        )
        links = json.loads(work.linked_work_json)
        assert links[0]["kind"] == "scheduled_run"
        db.add(
            IngestionRun(
                job_key=links[0]["job_key"],
                run_key="phase7a-live-test",
                provider="mock",
                status="completed",
                started_at=datetime.fromisoformat(links[0]["requested_after"])
                + timedelta(seconds=1),
                finished_at=datetime.now(UTC),
            )
        )
        db.commit()
        assert (
            DatabaseIngestionCoordinator(db, user_id=user.id).status(work.id).state == "succeeded"
        )


def test_production_bridge_queues_issuer_reports_stage_for_evidence_gap():
    user_id, _ = _seed_user_and_market()
    request = _company_request(ContextSectionName.EVENTS)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = ContextBuilder().build(db, user, request)
        _, refresh = ContextDeficiencyBridge.production(db, user).record_and_schedule(
            db, user, request, context
        )
        assert refresh is not None
        stage_run = db.scalar(select(IngestionStageRun))
        assert stage_run.stage == "reports"
        assert stage_run.input["symbol"] == "MEBL"
        assert stage_run.status == "queued"
        work = db.scalar(select(ContextIngestionWork))
        assert (
            DatabaseIngestionCoordinator(db, user_id=user.id).status(work.id).state == "queued"
        )
        stage_run.status = "completed"
        db.commit()
        assert (
            DatabaseIngestionCoordinator(db, user_id=user.id).status(work.id).state == "succeeded"
        )


def test_production_bridge_queues_history_stage_runs_and_waits_for_screening():
    user_id, instrument_id = _seed_user_and_market()
    request = _company_request(ContextSectionName.MARKET_RISK)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = ContextBuilder().build(db, user, request)
        assert any(item.category == "company_risk_metrics" for item in context.deficiencies)
        _, refresh = ContextDeficiencyBridge.production(db, user).record_and_schedule(
            db, user, request, context
        )
        assert refresh is not None
        assert len(list(db.scalars(select(IngestionStageRun).where(IngestionStageRun.stage == "history_prices")))) >= 12
        work = db.scalar(
            select(ContextIngestionWork)
            .join(
                ContextDeficiencyRecord,
                ContextDeficiencyRecord.id == ContextIngestionWork.deficiency_id,
            )
            .where(ContextDeficiencyRecord.category == "company_risk_metrics")
        )
        links = json.loads(work.linked_work_json)
        assert {item["kind"] for item in links} == {"coverage", "screening_snapshot"}
        for link in links:
            if link["kind"] == "coverage":
                row = db.get(IngestionCoverage, link["id"])
                row.status = "complete"
                row.item_count = 20
                row.completed_at = datetime.now(UTC)
        db.commit()
        coordinator = DatabaseIngestionCoordinator(db, user_id=user.id)
        assert coordinator.status(work.id).state == "queued"
        requested_after = max(
            row.completed_at
            for row in db.scalars(
                select(IngestionCoverage).where(
                    IngestionCoverage.id.in_(
                        [item["id"] for item in links if item["kind"] == "coverage"]
                    )
                )
            )
        )
        db.add(
            CompanyScreeningSnapshot(
                instrument_id=instrument_id,
                as_of_date=date.today(),
                sector="Banking",
                completeness=Decimal("1"),
                metrics_json='{"annual_volatility": 0.2}',
                computed_at=requested_after + timedelta(seconds=1),
            )
        )
        db.commit()
        assert coordinator.status(work.id).state == "succeeded"


def test_production_bridge_queues_existing_macro_workers(monkeypatch):
    from app.core.config import settings
    from app.services import macro_schedule_service

    user_id, _ = _seed_user_and_market()
    published: list[tuple[str, str]] = []
    monkeypatch.setattr(settings, "macro_ingestion_enabled", True)
    monkeypatch.setattr(
        macro_schedule_service.refresh_series,
        "apply_async",
        lambda *, args, queue, priority: published.append((args[0], args[1])),
    )
    request = _company_request(ContextSectionName.MACRO)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        db.query(MacroObservation).delete()
        db.commit()
        context = ContextBuilder().build(db, user, request)
        assert any(item.category == "macro_regime" for item in context.deficiencies), (
            context.sections["macro"].data,
            context.sections["macro"].errors,
            context.deficiencies,
        )
        _, refresh = ContextDeficiencyBridge.production(db, user).record_and_schedule(
            db, user, request, context
        )
        assert refresh is not None
        assert published
        work = db.scalar(select(ContextIngestionWork))
        links = json.loads(work.linked_work_json)
        assert links and all(item["kind"] == "ingestion_run" for item in links)
        for link in links:
            run = db.get(IngestionRun, link["id"])
            run.status = "completed"
            run.finished_at = datetime.now(UTC)
        db.commit()
        assert (
            DatabaseIngestionCoordinator(db, user_id=user.id).status(work.id).state == "succeeded"
        )
