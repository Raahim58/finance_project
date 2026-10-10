"""Offline context deficiencies contracts and fixtures."""

from __future__ import annotations
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base, SessionLocal
from app.models.intelligence_context import ContextDeficiencyRecord
from app.models.portfolio import Portfolio
from app.models.user import User
from app.schemas.intelligence_context import (
    ContextDeficiency,
    ContextScope,
    ContextSectionName,
    ContextState,
    IngestionWorkReference,
    IntelligenceContextRequest,
)
from app.services.context_builder import ContextBuilder
from app.services.context_deficiency_bridge import (
    ContextDeficiencyBridge,
    ContextIngestionRouter,
    RoutedIngestionCoordinator,
    _upsert_deficiency,
)
from app.tests.support.context import _seed_user_and_market, _company_request
import pytest


class _Coordinator:
    def __init__(self) -> None:
        self.scheduled: list[str] = []
        self.states: dict[str, str] = {}

    def schedule(self, deficiency):
        self.scheduled.append(deficiency.fingerprint)
        work_id = f"work-{len(self.scheduled)}"
        self.states[work_id] = "queued"
        return IngestionWorkReference(work_id=work_id, state="queued", coordinator="test")

    def status(self, work_id: str):
        return IngestionWorkReference(
            work_id=work_id, state=self.states[work_id], coordinator="test"
        )


@pytest.mark.usefixtures("database")
def test_deficiency_bridge_deduplicates_schedules_and_rebuilds_once_when_terminal():
    user_id, _ = _seed_user_and_market()
    coordinator = _Coordinator()
    bridge = ContextDeficiencyBridge(coordinator)
    request = _company_request(ContextSectionName.COMPANY_FACTS)
    builder = ContextBuilder()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = builder.build(db, user, request)
        refreshing, first = bridge.record_and_schedule(db, user, request, context)
        _, second = bridge.record_and_schedule(db, user, request, context)

        assert refreshing.status == "refreshing"
        assert "being fetched" in refreshing.message
        assert len(coordinator.scheduled) == 1
        assert db.scalar(select(ContextDeficiencyRecord)).occurrence_count == 2
        assert first is not None and second is not None

        work_id = json.loads(first.work_json)[0]["work_id"]
        coordinator.states[work_id] = "succeeded"
        rebuilds: list[str] = []
        notifications: list[tuple[str, str]] = []
        rebuilt = bridge.reconcile(
            db,
            first.id,
            rebuild=lambda value: rebuilds.append(value.symbol) or builder.build(db, user, value),
            notify=lambda notified_user_id, value: notifications.append(
                (notified_user_id, value.context_id)
            ),
        )
        assert rebuilt is not None
        assert rebuilds == ["MEBL"]
        assert notifications == [(user.id, rebuilt.context_id)]
        assert any(row.category == "financial_facts" for row in rebuilt.deficiencies)
        assert (
            bridge.reconcile(db, first.id, rebuild=lambda value: builder.build(db, user, value))
            is None
        )


def test_deficiency_upsert_is_atomic_under_concurrent_requests(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'context-race.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, future=True)
    barrier = Barrier(2)
    # Use the public contract shape without requiring an unrelated company fixture.
    item = ContextDeficiency(
        deficiency_id="def-race",
        entity_type="instrument",
        entity_key="MEBL",
        category="financial_facts",
        observed_state=ContextState.MISSING,
        expected={"dataset": "financial_facts"},
        reason="missing",
        fingerprint="a" * 64,
    )

    def record_once():
        with sessions() as db:
            barrier.wait()
            _upsert_deficiency(db, item, datetime.now(UTC))
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(record_once) for _ in range(2)]
        for future in futures:
            future.result()
    with sessions() as db:
        rows = list(db.scalars(select(ContextDeficiencyRecord)))
        assert len(rows) == 1
        assert rows[0].occurrence_count == 2
    engine.dispose()


@pytest.mark.usefixtures("database")
def test_ingestion_router_selects_family_and_declines_non_ingestible_ips():
    user_id, _ = _seed_user_and_market()
    dispatched: list[tuple[str, str]] = []

    def dispatch(deficiency, route):
        dispatched.append((deficiency.category, route.family))
        return IngestionWorkReference(work_id="facts-1", state="queued", coordinator="existing")

    coordinator = RoutedIngestionCoordinator(
        {"company_reports": dispatch},
        lambda work_id: IngestionWorkReference(
            work_id=work_id, state="succeeded", coordinator="existing"
        ),
    )
    with SessionLocal() as db:
        fact_gap = (
            ContextBuilder()
            .build(
                db,
                db.get(User, user_id),
                _company_request(ContextSectionName.COMPANY_FACTS),
            )
            .deficiencies[0]
        )
        assert ContextIngestionRouter().decide(fact_gap).family == "company_reports"

    with SessionLocal() as db:
        user = db.get(User, user_id)
        no_ips_portfolio = Portfolio(user_id=user.id, name="User action required")
        db.add(no_ips_portfolio)
        db.commit()
        request = IntelligenceContextRequest(
            symbol="MEBL",
            scope=ContextScope.PORTFOLIO_RELEVANCE,
            portfolio_id=no_ips_portfolio.id,
            sections=(ContextSectionName.IPS,),
        )
        context = ContextBuilder().build(db, user, request)
        returned, refresh = ContextDeficiencyBridge(coordinator).record_and_schedule(
            db, user, request, context
        )
        assert returned.status == "degraded"
        assert refresh is None
        assert dispatched == []

    with SessionLocal() as db:
        user = db.get(User, user_id)
        request = _company_request(ContextSectionName.COMPANY_FACTS)
        context = ContextBuilder().build(db, user, request)
        _, refresh = ContextDeficiencyBridge(coordinator).record_and_schedule(
            db, user, request, context
        )
        assert refresh is not None
        assert dispatched == [("financial_facts", "company_reports")]


@pytest.mark.usefixtures("database")
def test_inactive_refresh_marks_lazy_rebuild_instead_of_rebuilding():
    user_id, _ = _seed_user_and_market()
    coordinator = _Coordinator()
    bridge = ContextDeficiencyBridge(coordinator)
    request = _company_request(ContextSectionName.COMPANY_FACTS)
    builder = ContextBuilder()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = builder.build(db, user, request)
        _, refresh = bridge.record_and_schedule(db, user, request, context, active=False)
        assert refresh is not None
        work_id = json.loads(refresh.work_json)[0]["work_id"]
        coordinator.states[work_id] = "failed"
        assert (
            bridge.reconcile(db, refresh.id, rebuild=lambda value: builder.build(db, user, value))
            is None
        )
        db.refresh(refresh)
        assert refresh.needs_rebuild is True
        assert refresh.rebuild_count == 0
        assert (
            bridge.rebuild_if_needed(
                db, refresh.id, rebuild=lambda value: builder.build(db, user, value)
            )
            is not None
        )
        db.refresh(refresh)
        assert refresh.rebuild_count == 1
