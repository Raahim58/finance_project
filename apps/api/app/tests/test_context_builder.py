"""Offline context builder contracts and fixtures."""

from __future__ import annotations
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.portfolio import Portfolio
from app.models.user import User, UserPreferences
from app.models.workstation import (
    DataSource,
    FinancialFact,
    NormalizedEvent,
    NormalizedEventSubject,
    SourceArtifact,
)
from app.schemas.intelligence_context import (
    ContextScope,
    ContextSectionName,
    IntelligenceContextRequest,
)
from app.services.context_builder import ContextBuilder, ContextSectionCache
from app.services.canonical_market_service import persist_normalized_observations
from app.services.rag_service import ParsedPage, create_document_from_pages
from app.tests.support.context import _seed_user_and_market, _company_request, _confirmed_portfolio


@pytest.mark.usefixtures("database")
def test_company_context_is_unpersonalized_and_only_builds_requested_sections():
    user_id, _ = _seed_user_and_market()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        db.add(
            UserPreferences(
                user_id=user.id,
                risk_tolerance="aggressive",
                investment_horizon="short-term",
                preferred_sectors='["Banking"]',
            )
        )
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


@pytest.mark.usefixtures("database")
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


@pytest.mark.usefixtures("database")
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


@pytest.mark.usefixtures("database")
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
        assert (
            changed.sections["company_facts"].dependency_hash
            != first.sections["company_facts"].dependency_hash
        )
        assert set(changed.receipt.evidence_ids) != set(first.receipt.evidence_ids)
        assert provider_calls == 2


@pytest.mark.usefixtures("database")
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


@pytest.mark.usefixtures("database")
def test_rag_is_bounded_question_specific_and_citation_grounded():
    user_id, _ = _seed_user_and_market()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        create_document_from_pages(
            db,
            [
                ParsedPage(
                    1,
                    "MEBL management reported deposit growth while warning that margin pressure remains material.",
                )
            ],
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


@pytest.mark.usefixtures("database")
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


@pytest.mark.usefixtures("database")
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
            from app.models.workstation import (
                Event,
                EventSource,
                EventEntityLink,
                NormalizedEventEvidence,
            )
            from app.services.rag_service import create_document_from_pages, ParsedPage

            document = create_document_from_pages(
                db,
                [ParsedPage(1, "Quarterly results and operating outlook.")],
                title=event.title,
                document_type="announcement",
                symbol="MEBL",
                source_name="PSX",
                source_url=f"https://example.test/{index}",
                data_status="observed",
                commit=False,
            )
            raw = Event(event_type="announcement", title=event.title, occurred_at=event.occurred_at)
            db.add(raw)
            db.flush()
            db.add(
                EventSource(
                    event_id=raw.id,
                    document_id=document.id,
                    source_name="PSX",
                    source_url=document.source_url,
                    selection_status="selected",
                )
            )
            db.add(
                EventEntityLink(
                    event_id=raw.id,
                    entity_type="instrument",
                    entity_key="MEBL",
                    link_method="issuer_metadata",
                    confidence=1,
                )
            )
            db.add(
                NormalizedEventEvidence(
                    normalized_event_id=event.id, raw_event_id=raw.id, evidence_role="primary"
                )
            )
            db.add(
                NormalizedEventSubject(
                    normalized_event_id=event.id,
                    subject_type="instrument",
                    subject_key="MEBL",
                    link_method="test",
                    confidence=Decimal("1"),
                    is_direct=True,
                )
            )
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


@pytest.mark.usefixtures("database")
def test_freshness_uses_source_sla_without_aging_reporting_period_facts():
    user_id, instrument_id = _seed_user_and_market()
    fixed_now = datetime.now(UTC)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        persist_normalized_observations(
            db,
            [
                SimpleNamespace(
                    symbol="MEBL",
                    trade_date=date.today(),
                    open=Decimal("100"),
                    high=Decimal("102"),
                    low=Decimal("99"),
                    close=Decimal("101"),
                    previous_close=Decimal("100"),
                    volume=1000,
                    market_cap=None,
                )
            ],
            "dps",
        )
        for source in db.scalars(select(DataSource)):
            source.freshness_sla_minutes = 1
        for artifact in db.scalars(select(SourceArtifact)):
            artifact.retrieved_at = fixed_now - timedelta(days=2)
        db.add(
            FinancialFact(
                instrument_id=instrument_id,
                taxonomy_key="assets",
                period_type="annual",
                period_end=date.today() - timedelta(days=365),
                value=50,
                unit="currency",
                version=1,
            )
        )
        db.commit()
        context = ContextBuilder(now=lambda: fixed_now).build(
            db,
            user,
            _company_request(ContextSectionName.MARKET_RISK, ContextSectionName.COMPANY_FACTS),
        )
    assert context.sections["market_risk"].state in {"stale", "incomplete"}
    assert any(
        row.category == "market_price" and row.observed_state == "stale"
        for row in context.deficiencies
    )
    assert context.sections["company_facts"].state == "current"


@pytest.mark.usefixtures("database")
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


@pytest.mark.usefixtures("database")
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


@pytest.mark.usefixtures("database")
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
