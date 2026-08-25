from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base, SessionLocal
from app.models.evidence import EvidenceRefreshRequest
from app.models.intelligence_context import (
    ContextDeficiencyRecord,
    ContextIngestionWork,
    ContextRefreshNotification,
)
from app.models.market import MarketPrice
from app.models.portfolio import Portfolio
from app.models.user import User, UserPreferences
from app.models.workstation import (
    DataSource,
    CompanyScreeningSnapshot,
    FinancialFact,
    Instrument,
    IngestionCoverage,
    IngestionRun,
    MacroObservation,
    NormalizedEvent,
    NormalizedEventSubject,
    PortfolioIPSVersion,
    SourceArtifact,
    StandardizedFinancialFact,
)
from app.schemas.intelligence_context import (
    ContextDeficiency,
    ContextScope,
    ContextSectionName,
    ContextState,
    IngestionWorkReference,
    IntelligenceContextRequest,
)
from app.services.context_builder import ContextBuilder, ContextSectionCache
from app.services.context_deficiency_bridge import (
    ContextDeficiencyBridge,
    ContextIngestionRouter,
    RoutedIngestionCoordinator,
    _upsert_deficiency,
)
from app.services.market_ingestion import generate_mock_market_data
from app.services.canonical_market_service import persist_normalized_observations
from app.services.context_ingestion_coordinator import DatabaseIngestionCoordinator
from app.services.context_refresh_service import reconcile_pending_contexts
from app.services.rag_service import ParsedPage, create_document_from_pages


def _seed_user_and_market(email: str = "context@example.com") -> tuple[str, str]:
    with SessionLocal() as db:
        generate_mock_market_data(db, days=5, end_date=date.today())
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
            constraints_json=json.dumps({"risk_tolerance": "conservative", "max_instrument_weight": 0.10}),
            confirmed_at=datetime.now(UTC),
        )
        db.add(ips)
        db.flush()
        portfolio.selected_ips_version_id = ips.id
        db.commit()
        return portfolio.id


def test_company_context_is_unpersonalized_and_only_builds_requested_sections():
    user_id, _ = _seed_user_and_market()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        db.add(UserPreferences(
            user_id=user.id,
            risk_tolerance="aggressive",
            investment_horizon="short-term",
            preferred_sectors='["Banking"]',
        ))
        db.commit()
        context = ContextBuilder().build(
            db,
            user,
            _company_request(ContextSectionName.MARKET_RISK),
        )

    assert set(context.sections) == {"market_risk"}
    assert context.portfolio_id is None
    serialized = context.model_dump_json()
    assert "aggressive" not in serialized
    assert "short-term" not in serialized
    assert "preferred_sectors" not in serialized


def test_scope_contract_rejects_personalization_and_requires_security_fit_inputs():
    with pytest.raises(ValidationError, match="cannot include a portfolio"):
        IntelligenceContextRequest(symbol="MEBL", portfolio_id="portfolio")
    with pytest.raises(ValidationError, match="requires one selected portfolio"):
        IntelligenceContextRequest(symbol="MEBL", scope=ContextScope.SECURITY_FIT)
    with pytest.raises(ValidationError, match="requires portfolio and IPS"):
        IntelligenceContextRequest(
            symbol="MEBL",
            scope=ContextScope.SECURITY_FIT,
            portfolio_id="portfolio",
            sections=(ContextSectionName.COMPANY_FACTS,),
        )


def test_security_fit_uses_only_selected_owned_portfolio_and_confirmed_ips():
    user_id, _ = _seed_user_and_market()
    portfolio_id = _confirmed_portfolio(user_id)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = ContextBuilder().build(
            db,
            user,
            IntelligenceContextRequest(
                symbol="MEBL",
                scope=ContextScope.SECURITY_FIT,
                portfolio_id=portfolio_id,
                sections=(ContextSectionName.PORTFOLIO, ContextSectionName.IPS),
            ),
        )

    assert context.sections["portfolio"].data["id"] == portfolio_id
    assert context.sections["ips"].data["terms"]["risk_tolerance"] == "conservative"
    assert context.sections["ips"].data["terms"]["max_instrument_weight"] == 0.10


def test_portfolio_ownership_is_a_hard_failure_and_missing_ips_is_explicit():
    owner_id, _ = _seed_user_and_market()
    portfolio_id = _confirmed_portfolio(owner_id)
    with SessionLocal() as db:
        stranger = User(email="stranger@example.com", password_hash="unused")
        db.add(stranger)
        db.commit()
        with pytest.raises(HTTPException) as error:
            ContextBuilder().build(
                db,
                stranger,
                IntelligenceContextRequest(
                    symbol="MEBL",
                    scope=ContextScope.PORTFOLIO_RELEVANCE,
                    portfolio_id=portfolio_id,
                    sections=(ContextSectionName.PORTFOLIO, ContextSectionName.IPS),
                ),
            )
        assert error.value.status_code == 404

        own = Portfolio(user_id=stranger.id, name="No IPS")
        db.add(own)
        db.commit()
        context = ContextBuilder().build(
            db,
            stranger,
            IntelligenceContextRequest(
                symbol="MEBL",
                scope=ContextScope.PORTFOLIO_RELEVANCE,
                portfolio_id=own.id,
                sections=(ContextSectionName.IPS,),
            ),
        )
        assert context.sections["ips"].state == "missing"
        assert context.deficiencies[0].category == "confirmed_ips"


def test_exact_facts_are_not_filled_from_rag_and_evidence_ids_are_stable():
    user_id, instrument_id = _seed_user_and_market()
    builder = ContextBuilder(cache=ContextSectionCache())
    provider_calls = 0
    original_provider = builder._company_facts

    def counted_provider(*args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return original_provider(*args, **kwargs)

    builder._company_facts = counted_provider
    request = _company_request(ContextSectionName.COMPANY_FACTS, ContextSectionName.MARKET_RISK)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        first = builder.build(db, user, request)
        second = builder.build(db, user, request)
        assert first.sections["company_facts"].data["fundamentals"] == []
        assert any(item.category == "financial_facts" for item in first.deficiencies)
        assert first.receipt.evidence_ids == second.receipt.evidence_ids
        assert second.sections["market_risk"].reused is True
        assert provider_calls == 1

        fact = FinancialFact(
            instrument_id=instrument_id,
            taxonomy_key="revenue",
            period_type="annual",
            period_end=date.today(),
            filing_date=date.today(),
            value=100,
            unit="currency",
            currency="PKR",
            version=1,
        )
        db.add(fact)
        db.commit()
        changed = builder.build(db, user, request)
        assert changed.sections["company_facts"].data["fundamentals"][0]["value"] == 100
        assert changed.sections["company_facts"].dependency_hash != first.sections["company_facts"].dependency_hash
        assert set(changed.receipt.evidence_ids) != set(first.receipt.evidence_ids)
        assert provider_calls == 2


def test_rag_without_purpose_is_not_requested_and_build_has_no_llm_dependency():
    user_id, _ = _seed_user_and_market()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = ContextBuilder().build(
            db,
            user,
            _company_request(ContextSectionName.RAG_EVIDENCE),
        )
    assert context.sections["rag_evidence"].state == "not_requested"
    assert context.sections["rag_evidence"].data == []
    assert "llm" not in ContextBuilder.__module__


def test_rag_is_bounded_question_specific_and_citation_grounded():
    user_id, _ = _seed_user_and_market()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        create_document_from_pages(
            db,
            [ParsedPage(1, "MEBL management reported deposit growth while warning that margin pressure remains material.")],
            title="MEBL observed research note",
            document_type="research_note",
            symbol="MEBL",
            source_name="Observed Test Research",
            source_url="https://example.test/mebl-note",
            visibility="public",
        )
        context = ContextBuilder().build(
            db,
            user,
            IntelligenceContextRequest(
                symbol="MEBL",
                sections=(ContextSectionName.RAG_EVIDENCE,),
                question="What margin risks were reported?",
                rag_limit=1,
            ),
        )
    section = context.sections["rag_evidence"]
    assert len(section.data) == 1
    assert len(section.evidence) == 1
    assert section.evidence[0].classification == "document_passage"
    assert section.evidence[0].metadata["citation_id"]
    assert section.provenance["exact_values_allowed"] is False


def test_private_rag_evidence_remains_owner_scoped_through_context_builder():
    owner_id, _ = _seed_user_and_market()
    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        stranger = User(email="rag-stranger@example.com", password_hash="unused")
        db.add(stranger)
        db.flush()
        create_document_from_pages(
            db,
            [ParsedPage(1, "Private MEBL covenant warning only the owner may retrieve.")],
            title="Private covenant note",
            document_type="research_note",
            symbol="MEBL",
            source_name="Private Test Research",
            source_url="https://example.test/private-mebl-covenant",
            visibility="private",
            owner_user_id=owner.id,
            source_tier_value=2,
            data_status="observed",
        )
        owner_context = ContextBuilder().build(
            db,
            owner,
            IntelligenceContextRequest(
                symbol="MEBL",
                sections=(ContextSectionName.RAG_EVIDENCE,),
                question="What covenant warning exists?",
            ),
        )
        stranger_context = ContextBuilder().build(
            db,
            stranger,
            IntelligenceContextRequest(
                symbol="MEBL",
                sections=(ContextSectionName.RAG_EVIDENCE,),
                question="What covenant warning exists?",
            ),
        )
    assert owner_context.sections["rag_evidence"].data
    assert stranger_context.sections["rag_evidence"].data == []
    assert stranger_context.sections["rag_evidence"].state == "missing"


def test_event_admission_is_material_bounded_and_uses_event_freshness_policy():
    user_id, _ = _seed_user_and_market()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        for index in range(3):
            event = NormalizedEvent(
                event_type="earnings",
                classification_status="classified",
                title=f"Material event {index}",
                occurred_at=datetime.now(UTC) - timedelta(days=index),
                cluster_key=f"phase7-{index}",
                materiality="high",
                confidence=Decimal("0.9"),
                freshness_score=Decimal("0.8"),
                freshness_status="current",
                detection_version="test-v1",
            )
            db.add(event)
            db.flush()
            db.add(NormalizedEventSubject(
                normalized_event_id=event.id,
                subject_type="instrument",
                subject_key="MEBL",
                link_method="test",
                confidence=Decimal("1"),
                is_direct=True,
            ))
        db.commit()
        context = ContextBuilder().build(
            db,
            user,
            IntelligenceContextRequest(
                symbol="MEBL",
                sections=(ContextSectionName.EVENTS,),
                event_limit=2,
            ),
        )
    assert context.sections["events"].state == "current"
    assert len(context.sections["events"].data) == 2
    assert all(row["materiality"] == "high" for row in context.sections["events"].data)


def test_freshness_uses_source_sla_without_aging_reporting_period_facts():
    user_id, instrument_id = _seed_user_and_market()
    fixed_now = datetime.now(UTC)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        persist_normalized_observations(db, [SimpleNamespace(
            symbol="MEBL",
            trade_date=date.today(),
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            previous_close=Decimal("100"),
            volume=1000,
            market_cap=None,
        )], "dps")
        for source in db.scalars(select(DataSource)):
            source.freshness_sla_minutes = 1
        for artifact in db.scalars(select(SourceArtifact)):
            artifact.retrieved_at = fixed_now - timedelta(days=2)
        db.add(FinancialFact(
            instrument_id=instrument_id,
            taxonomy_key="assets",
            period_type="annual",
            period_end=date.today() - timedelta(days=365),
            value=50,
            unit="currency",
            version=1,
        ))
        db.commit()
        context = ContextBuilder(now=lambda: fixed_now).build(
            db,
            user,
            _company_request(ContextSectionName.MARKET_RISK, ContextSectionName.COMPANY_FACTS),
        )
    assert context.sections["market_risk"].state in {"stale", "incomplete"}
    assert any(row.category == "market_price" and row.observed_state == "stale" for row in context.deficiencies)
    assert context.sections["company_facts"].state == "current"


def test_soft_provider_failure_is_isolated_and_build_is_instrumented(monkeypatch):
    user_id, _ = _seed_user_and_market()
    builder = ContextBuilder()

    def fail_macro(*_args, **_kwargs):
        raise RuntimeError("macro unavailable")

    monkeypatch.setattr(builder, "_macro", fail_macro)
    with SessionLocal() as db:
        context = builder.build(
            db,
            db.get(User, user_id),
            _company_request(ContextSectionName.MARKET_RISK, ContextSectionName.MACRO),
        )
    assert context.sections["market_risk"].data is not None
    assert context.sections["macro"].state == "not_evaluated"
    assert context.sections["macro"].provenance["failure_isolated"] is True
    assert context.receipt.build_duration_ms >= 0
    assert set(context.receipt.section_duration_ms) == {"market_risk", "macro"}


def test_representative_company_build_records_measured_duration():
    user_id, _ = _seed_user_and_market()
    with SessionLocal() as db:
        context = ContextBuilder().build(
            db,
            db.get(User, user_id),
            IntelligenceContextRequest(symbol="MEBL", research_purpose="risks"),
        )
    assert context.receipt.build_duration_ms >= 0
    assert len(context.sections) == 6
    assert len(context.receipt.section_duration_ms) == len(context.sections)


def test_every_context_scope_performs_zero_llm_provider_calls(monkeypatch):
    from app.ai.providers import registry

    user_id, _ = _seed_user_and_market()
    portfolio_id = _confirmed_portfolio(user_id)

    def forbidden_provider(*_args, **_kwargs):
        raise AssertionError("Context construction attempted an LLM provider call")

    monkeypatch.setattr(registry, "get_provider", forbidden_provider)
    requests = [
        IntelligenceContextRequest(symbol="MEBL"),
        IntelligenceContextRequest(
            symbol="MEBL",
            scope=ContextScope.PORTFOLIO_RELEVANCE,
            portfolio_id=portfolio_id,
        ),
        IntelligenceContextRequest(
            symbol="MEBL",
            scope=ContextScope.SECURITY_FIT,
            portfolio_id=portfolio_id,
        ),
    ]
    with SessionLocal() as db:
        user = db.get(User, user_id)
        for request in requests:
            ContextBuilder().build(db, user, request)


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
        return IngestionWorkReference(work_id=work_id, state=self.states[work_id], coordinator="test")


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
            notify=lambda notified_user_id, value: notifications.append((notified_user_id, value.context_id)),
        )
        assert rebuilt is not None
        assert rebuilds == ["MEBL"]
        assert notifications == [(user.id, rebuilt.context_id)]
        assert any(row.category == "financial_facts" for row in rebuilt.deficiencies)
        assert bridge.reconcile(db, first.id, rebuild=lambda value: builder.build(db, user, value)) is None


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


def test_ingestion_router_selects_family_and_declines_non_ingestible_ips():
    user_id, _ = _seed_user_and_market()
    dispatched: list[tuple[str, str]] = []

    def dispatch(deficiency, route):
        dispatched.append((deficiency.category, route.family))
        return IngestionWorkReference(work_id="facts-1", state="queued", coordinator="existing")

    coordinator = RoutedIngestionCoordinator(
        {"company_reports": dispatch},
        lambda work_id: IngestionWorkReference(work_id=work_id, state="succeeded", coordinator="existing"),
    )
    with SessionLocal() as db:
        fact_gap = ContextBuilder().build(
            db,
            db.get(User, user_id),
            _company_request(ContextSectionName.COMPANY_FACTS),
        ).deficiencies[0]
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


def test_production_bridge_queues_existing_company_fact_workers_and_tracks_coverage(monkeypatch):
    from app.services import context_ingestion_coordinator as production

    user_id, instrument_id = _seed_user_and_market()
    published: list[tuple[str, tuple]] = []
    monkeypatch.setattr(
        production.broad_fundamentals,
        "delay",
        lambda *args: published.append(("broad_fundamentals", args)),
    )
    monkeypatch.setattr(
        production.financial_download_catalog,
        "delay",
        lambda *args: published.append(("financial_download_catalog", args)),
    )
    request = _company_request(ContextSectionName.COMPANY_FACTS)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = ContextBuilder().build(db, user, request)
        bridge = ContextDeficiencyBridge.production(db, user)
        refreshing, refresh = bridge.record_and_schedule(
            db, user, request, context
        )
        assert refresh is not None
        assert refreshing.status == "refreshing"
        assert {name for name, _args in published} == {
            "broad_fundamentals",
            "financial_download_catalog",
        }
        work = db.scalar(select(ContextIngestionWork))
        links = json.loads(work.linked_work_json)
        assert work.family == "company_reports"
        assert {item["kind"] for item in links} == {"coverage"}
        coverage_rows = list(db.scalars(select(IngestionCoverage).where(
            IngestionCoverage.id.in_([item["id"] for item in links])
        )))
        assert {row.dataset_type for row in coverage_rows} == {
            "standardized_fundamentals",
            "report_catalog_dispatch",
        }

        for row in coverage_rows:
            row.status = "complete"
            row.item_count = 1
        db.add(StandardizedFinancialFact(
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
        ))
        db.commit()
        coordinator = DatabaseIngestionCoordinator(db, user_id=user.id)
        assert coordinator.status(work.id).state == "succeeded"
        notifications: list[str] = []
        sweep = reconcile_pending_contexts(
            db,
            notify=lambda _user_id, value: notifications.append(value.context_id)
        )
        db.refresh(refresh)
        assert sweep.rebuilt == 1
        assert refresh.status == "rebuilt"
        assert refresh.rebuild_count == 1
        assert notifications == [context.context_id]
        assert db.scalar(select(ContextDeficiencyRecord)).status == "resolved"
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
        work = db.scalar(select(ContextIngestionWork).join(
            ContextDeficiencyRecord,
            ContextDeficiencyRecord.id == ContextIngestionWork.deficiency_id,
        ).where(ContextDeficiencyRecord.category == "market_price"))
        links = json.loads(work.linked_work_json)
        assert links[0]["kind"] == "scheduled_run"
        db.add(IngestionRun(
            job_key=links[0]["job_key"],
            run_key="phase7a-live-test",
            provider="mock",
            status="completed",
            started_at=datetime.fromisoformat(links[0]["requested_after"]) + timedelta(seconds=1),
            finished_at=datetime.now(UTC),
        ))
        db.commit()
        assert DatabaseIngestionCoordinator(db, user_id=user.id).status(work.id).state == "succeeded"


def test_production_bridge_creates_existing_targeted_evidence_request(monkeypatch):
    from app.services import context_ingestion_coordinator as production

    user_id, _ = _seed_user_and_market()
    published: list[str] = []
    monkeypatch.setattr(
        production.targeted_refresh,
        "apply_async",
        lambda *, args, queue, priority: published.append(args[0]),
    )
    request = _company_request(ContextSectionName.EVENTS)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = ContextBuilder().build(db, user, request)
        _, refresh = ContextDeficiencyBridge.production(db, user).record_and_schedule(
            db, user, request, context
        )
        assert refresh is not None
        evidence_request = db.scalar(select(EvidenceRefreshRequest))
        assert evidence_request.scope_key == "symbol:MEBL"
        assert evidence_request.status == "running"
        assert published == [evidence_request.id]
        work = db.scalar(select(ContextIngestionWork))
        evidence_request.status = "complete"
        evidence_request.completed_at = datetime.now(UTC)
        db.commit()
        assert DatabaseIngestionCoordinator(db, user_id=user.id).status(work.id).state == "succeeded"


def test_production_bridge_queues_existing_history_workers_and_waits_for_screening(monkeypatch):
    from app.services import context_ingestion_coordinator as production

    user_id, instrument_id = _seed_user_and_market()
    published: list[tuple] = []
    monkeypatch.setattr(
        production.dps_history,
        "delay",
        lambda *args: published.append(args),
    )
    request = _company_request(ContextSectionName.MARKET_RISK)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        context = ContextBuilder().build(db, user, request)
        assert any(item.category == "company_risk_metrics" for item in context.deficiencies)
        _, refresh = ContextDeficiencyBridge.production(db, user).record_and_schedule(
            db, user, request, context
        )
        assert refresh is not None
        assert len(published) >= 12
        work = db.scalar(select(ContextIngestionWork).join(
            ContextDeficiencyRecord,
            ContextDeficiencyRecord.id == ContextIngestionWork.deficiency_id,
        ).where(ContextDeficiencyRecord.category == "company_risk_metrics"))
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
            for row in db.scalars(select(IngestionCoverage).where(
                IngestionCoverage.id.in_([
                    item["id"] for item in links if item["kind"] == "coverage"
                ])
            ))
        )
        db.add(CompanyScreeningSnapshot(
            instrument_id=instrument_id,
            as_of_date=date.today(),
            sector="Banking",
            completeness=Decimal("1"),
            metrics_json='{"annual_volatility": 0.2}',
            computed_at=requested_after + timedelta(seconds=1),
        ))
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
        assert DatabaseIngestionCoordinator(db, user_id=user.id).status(work.id).state == "succeeded"


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
        assert bridge.reconcile(db, refresh.id, rebuild=lambda value: builder.build(db, user, value)) is None
        db.refresh(refresh)
        assert refresh.needs_rebuild is True
        assert refresh.rebuild_count == 0
        assert bridge.rebuild_if_needed(db, refresh.id, rebuild=lambda value: builder.build(db, user, value)) is not None
        db.refresh(refresh)
        assert refresh.rebuild_count == 1
