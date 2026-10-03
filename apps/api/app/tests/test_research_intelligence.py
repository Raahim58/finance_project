"""Critical research invariants, using offline fixtures and no paid model calls."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.core.security import encrypt_secret
from app.domain.research_relevance import detect_factors
from app.models.document import Document, DocumentPage, DocumentChunk
from app.models.user import User
from app.models.llm_key import LLMApiKey
from app.models.workstation import (
    Instrument,
    Event,
    EventSource,
    EventEntityLink,
    NormalizedEvent,
    NormalizedEventEvidence,
)
from app.models.research_intelligence import ResearchJob, ResearchAttempt, CompanyEventBrief
from app.models.intelligence_context import IntelligenceContextReceiptRecord, ContextIngestionWork
from app.schemas.research_intelligence import BatchRequest
from app.services.rag_service import create_document_from_pages, ParsedPage, index_document_pages
from app.services.research_intelligence_service import event_views, company_intelligence
from app.services.research_generation_service import validate_output
from app.services.research_job_service import preview_batch, enqueue_batch, job_status
from app.ai.providers.base import LLMProviderResult
from app.jobs import research_worker


@pytest.mark.parametrize(
    "text,expected",
    [
        ("OGDC announces oil discovery and commencement of production", []),
        ("Brent crude prices rise", ["oil_price"]),
        ("US Federal Reserve policy rate cut", []),
        ("SBP monetary policy leaves policy rate unchanged", ["pk_policy_rate"]),
        ("USD/PKR exchange rate changes", ["usd_pkr"]),
        ("Pakistan inflation rises", []),
    ],
)
def test_narrow_factor_matching(text, expected):
    assert detect_factors(text) == expected


def seed(db):
    user = User(email="research@example.test", password_hash="not-a-login-hash")
    other = User(email="other@example.test", password_hash="not-a-login-hash")
    a, b = (
        Instrument(symbol="AAA", name="A", sector="Energy"),
        Instrument(symbol="BBB", name="B", sector="Energy"),
    )
    db.add_all([user, other, a, b])
    db.flush()
    db.add(
        LLMApiKey(
            user_id=user.id,
            provider="gemini",
            encrypted_api_key=encrypt_secret("offline-test-key"),
            masked_api_key="****",
            default_model="offline-test-model",
        )
    )
    norm = NormalizedEvent(
        event_type="earnings",
        classification_status="classified",
        title="Shared quarterly report template",
        occurred_at=datetime.now(UTC),
        cluster_key="shared",
        materiality="medium",
        confidence=1,
        freshness_score=Decimal("0.2"),
        freshness_status="recent",
        detection_version="fixture",
    )
    db.add(norm)
    db.flush()
    for instrument in (a, b):
        doc = create_document_from_pages(
            db,
            [
                ParsedPage(
                    1,
                    "The company announced its quarterly financial results and operating outlook. "
                    * 4,
                )
            ],
            title=instrument.symbol + " report",
            document_type="announcement",
            symbol=instrument.symbol,
            source_name="Pakistan Stock Exchange",
            source_url="https://example.test/" + instrument.symbol,
            data_status="observed",
            commit=False,
        )
        raw = Event(
            event_type="announcement",
            title=instrument.symbol + " quarterly report",
            occurred_at=datetime.now(UTC),
        )
        db.add(raw)
        db.flush()
        db.add_all(
            [
                EventSource(
                    event_id=raw.id,
                    source_name="Pakistan Stock Exchange",
                    source_url=doc.source_url,
                    document_id=doc.id,
                    selection_status="selected",
                ),
                EventEntityLink(
                    event_id=raw.id,
                    entity_type="instrument",
                    entity_key=instrument.symbol,
                    link_method="issuer_metadata",
                    confidence=1,
                ),
                NormalizedEventEvidence(
                    normalized_event_id=norm.id, raw_event_id=raw.id, evidence_role="primary"
                ),
            ]
        )
    db.commit()
    return user, other, a, b


def test_issuer_scope_and_pending_sources_are_not_cluster_inherited():
    with SessionLocal() as db:
        user, _, a, _ = seed(db)
        rows = event_views(db, symbol="AAA")
        assert len(rows) == 1 and rows[0]["title"] == "AAA quarterly report"
        assert [s["subject_key"] for s in rows[0]["subjects"]] == ["AAA"]
        assert rows[0]["freshness_status"] == "recent" and rows[0]["freshness_score"] == Decimal(
            "0.2"
        )
        source = db.scalar(
            select(EventSource).where(EventSource.event_id == rows[0]["raw_event_id"])
        )
        source.selection_status = "pending"
        db.commit()
        assert event_views(db, symbol="AAA") == []


def test_existing_document_reindex_preserves_identity_and_physical_pages():
    with SessionLocal() as db:
        seed(db)
        doc = db.scalar(select(Document).where(Document.symbol == "AAA"))
        identity, original_hash = doc.id, doc.content_hash
        index_document_pages(
            db, doc, [ParsedPage(7, "Floating rate debt affects financing costs. " * 8)]
        )
        db.commit()
        assert doc.id == identity and doc.content_hash == original_hash
        assert list(
            db.scalars(select(DocumentPage.page_number).where(DocumentPage.document_id == identity))
        ) == [7]
        assert all(
            c.page_number == 7
            for c in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == identity))
        )
        index_document_pages(
            db, doc, [ParsedPage(7, "Floating rate debt affects financing costs. " * 8)]
        )
        db.commit()
        assert (
            db.scalar(
                select(func.count())
                .select_from(DocumentPage)
                .where(DocumentPage.document_id == identity)
            )
            == 1
        )


def test_generation_evidence_validation_rejects_invented_quotes_and_ids():
    payload = {
        "evidence": [{"id": "chunk:a", "text": "Floating-rate debt exposes financing costs."}]
    }
    relationship = {
        "factor": "pk_policy_rate",
        "channel": "financing",
        "mechanism": "Debt financing costs may change.",
        "conditions": [],
        "evidence_ids": ["chunk:a"],
        "supporting_quotes": [{"evidence_id": "chunk:a", "quote": "Floating-rate debt"}],
        "status": "ai_proposed",
    }
    assert validate_output(
        "profile", json.dumps({"relationships": [relationship], "coverage_gaps": []}), payload
    )
    relationship["supporting_quotes"][0]["quote"] = "Invented debt fact"
    with pytest.raises(ValueError, match="quote_not_in_source"):
        validate_output(
            "profile", json.dumps({"relationships": [relationship], "coverage_gaps": []}), payload
        )
    relationship["evidence_ids"] = ["other-owner:private-document"]
    with pytest.raises(ValueError, match="unknown_evidence_id"):
        validate_output(
            "profile", json.dumps({"relationships": [relationship], "coverage_gaps": []}), payload
        )


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


def test_worker_one_turn_calls_cache_and_never_exposes_keys(monkeypatch):
    calls = []

    class Provider:
        async def chat_with_options(self, key, messages, model, *, options):
            assert (
                key == "offline-test-key" and len(messages) == 2 and options.continuation_id is None
            )
            payload = json.loads(
                messages[1]["content"].split("INPUT_JSON\n")[1].split("\nOUTPUT_SCHEMA")[0]
            )
            calls.append(payload)
            if "allowed_factors" in payload:
                result = {"relationships": [], "coverage_gaps": ["No retained reports"]}
            else:
                events = []
                for e in payload["events"]:
                    ref = e["evidence"][0]["id"]
                    events.append(
                        {
                            "event_key": e["event_key"],
                            "relationship_kind": e["relationship_kind"],
                            "status": "explained",
                            "what_happened": {
                                "text": "Quarterly results were announced.",
                                "evidence_ids": [ref],
                                "fact_ids": [],
                            },
                            "why_it_matters": [],
                            "countereffects": [],
                            "unknowns": ["Financial consequences not established."],
                        }
                    )
                result = {"events": events}
            return LLMProviderResult(
                content=json.dumps(result),
                provider="gemini",
                model=model,
                input_tokens=100,
                output_tokens=50,
            )

    monkeypatch.setattr(research_worker, "get_provider", lambda _: Provider())
    with SessionLocal() as db:
        user, _, a, _ = seed(db)
        uid = user.id
        aid = a.id
        root = enqueue_batch(
            db, user, BatchRequest(client_request_id="worker-1", instrument_ids=[aid])
        )
    asyncio.run(research_worker.drain(once=True))
    with SessionLocal() as db:
        user = db.get(User, uid)
        status = job_status(db, user, root["id"])
        assert status["status"] == "completed" and status["reserved_calls"] == 2
        assert status["actual_usage"]["input_tokens"] == 200
        assert "offline-test-key" not in json.dumps(status)
        result = company_intelligence(db, user, "AAA")
        assert result["events"][0]["saved_brief"]["explanation"]["what_happened"]["text"]
        preview = preview_batch(
            db, user, BatchRequest(client_request_id="worker-2", instrument_ids=[aid])
        )
        assert preview["maximum_calls"] == 0
        enqueue_batch(db, user, BatchRequest(client_request_id="worker-2", instrument_ids=[aid]))
    asyncio.run(research_worker.drain(once=True))
    assert len(calls) == 2


def test_worker_uncertain_call_is_not_replayed(monkeypatch):
    calls = []

    class Provider:
        async def chat_with_options(self, *args, **kwargs):
            calls.append(1)
            raise TimeoutError()

    monkeypatch.setattr(research_worker, "get_provider", lambda _: Provider())
    with SessionLocal() as db:
        user, _, a, _ = seed(db)
        enqueue_batch(db, user, BatchRequest(client_request_id="uncertain", instrument_ids=[a.id]))
    asyncio.run(research_worker.drain(once=True))
    asyncio.run(research_worker.drain(once=True))
    assert len(calls) == 1
    with SessionLocal() as db:
        assert db.scalar(select(ResearchAttempt)).status == "uncertain"
        assert db.scalar(select(func.count()).select_from(CompanyEventBrief)) == 0


def test_company_only_tool_boundary():
    from app.ai.tool_loop import _company_tool_allowed

    assert _company_tool_allowed("research.event_relevance", {"symbol": "AAA"})
    assert not _company_tool_allowed("portfolio.summary", {})
    assert not _company_tool_allowed("research.search", {"portfolio_id": "private"})
    assert not _company_tool_allowed("research.company_sections", {"sections": ["ips"]})


def test_retained_report_hash_and_physical_pages_preserve_financial_facts(monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from datetime import date
    from app.models.workstation import SourceArtifact, DataSource, FinancialFact
    from app.services import research_evidence_service as service

    content = b"offline retained PDF fixture"
    monkeypatch.setattr(
        service, "get_artifact_store", lambda _: SimpleNamespace(get=lambda _: content)
    )
    monkeypatch.setattr(
        service,
        "_native_text_pages",
        lambda _: [ParsedPage(3, "Floating rate debt and financing risk. " * 10)],
    )
    with SessionLocal() as db:
        user, _, a, _ = seed(db)
        source = DataSource(name="Retained fixture", source_type="report")
        db.add(source)
        db.flush()
        artifact = SourceArtifact(
            data_source_id=source.id,
            source_url="https://example.test/report.pdf",
            sha256=hashlib.sha256(content).hexdigest(),
            storage_path="fixture",
            parser_version="test",
        )
        db.add(artifact)
        db.flush()
        doc = Document(
            symbol=a.symbol,
            document_type="annual_report",
            title="Annual report",
            source_name="PSX",
            content_hash=artifact.sha256,
            artifact_id=artifact.id,
            status="parsed",
            published_date=date.today(),
            data_status="observed",
        )
        db.add(doc)
        db.flush()
        fact = FinancialFact(
            instrument_id=a.id,
            taxonomy_key="debt",
            period_type="annual",
            period_end=date.today(),
            value=123,
            unit="PKR",
            document_id=doc.id,
            page_number=3,
        )
        db.add(fact)
        db.commit()
        result = service.prepare_report(db, doc.id)
        assert result["status"] == "indexed"
        assert (
            db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id)).page_number
            == 3
        )
        assert db.get(FinancialFact, fact.id).value == Decimal("123")
        assert service.prepare_report(db, doc.id)["status"] == "cached"
        doc2 = Document(
            symbol=a.symbol,
            document_type="annual_report",
            title="Wrong hash",
            source_name="PSX",
            content_hash="wrong",
            artifact_id=artifact.id,
        )
        db.add(doc2)
        artifact.sha256 = "wrong"
        db.commit()
        with pytest.raises(ValueError, match="Artifact hash mismatch"):
            service.prepare_report(db, doc2.id)


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


def test_digest_cannot_cite_other_events_and_requires_exact_event_keys():
    payload = {
        "events": [
            {
                "event_key": "raw:a",
                "relationship_kind": "direct",
                "evidence": [{"id": "chunk:a", "text": "A results"}],
            },
            {
                "event_key": "raw:b",
                "relationship_kind": "direct",
                "evidence": [{"id": "chunk:b", "text": "B results"}],
            },
        ]
    }
    entry = {
        "event_key": "raw:a",
        "relationship_kind": "direct",
        "status": "explained",
        "what_happened": {
            "text": "Results announced.",
            "evidence_ids": ["chunk:b"],
            "fact_ids": [],
        },
        "why_it_matters": [],
        "countereffects": [],
        "unknowns": [],
    }
    with pytest.raises(ValueError, match="digest_event_keys_mismatch"):
        validate_output("digest", json.dumps({"events": [entry]}), payload)
    second = {**entry, "event_key": "raw:b"}
    with pytest.raises(ValueError, match="unknown_claim_reference"):
        validate_output("digest", json.dumps({"events": [entry, second]}), payload)


def test_response_checkpoint_recovers_without_second_provider_call(monkeypatch):
    from types import SimpleNamespace
    from app.services.research_intelligence_service import profile_input
    from app.domain.research_relevance import canonical, fingerprint

    with SessionLocal() as db:
        user, _, instrument, _ = seed(db)
        root = enqueue_batch(
            db, user, BatchRequest(client_request_id="checkpoint", instrument_ids=[instrument.id])
        )
        company = db.scalar(
            select(ResearchJob).where(
                ResearchJob.parent_id == root["id"], ResearchJob.job_type == "company"
            )
        )
        payload = profile_input(db, instrument)
        stage = ResearchJob(
            user_id=user.id,
            parent_id=root["id"],
            instrument_id=instrument.id,
            job_type="profile",
            dedup_key=company.id + ":profile:" + fingerprint(payload),
            request_hash=fingerprint(payload),
            status="running",
            max_calls=1,
        )
        db.add(stage)
        db.flush()
        db.add(
            ResearchAttempt(
                job_id=stage.id,
                provider="gemini",
                model="offline-test-model",
                status="response_received",
                request_hash=fingerprint(payload),
                response_encrypted=encrypt_secret(
                    canonical({"relationships": [], "coverage_gaps": ["No reports"]})
                ),
            )
        )
        db.commit()

        async def should_not_call(*_args, **_kwargs):
            raise AssertionError("Paid replay")

        monkeypatch.setattr(
            research_worker,
            "get_provider",
            lambda _: SimpleNamespace(chat_with_options=should_not_call),
        )
        asyncio.run(
            research_worker.call_stage(
                db,
                company,
                user,
                instrument,
                "profile",
                payload,
                {"provider": "gemini", "model": "offline-test-model"},
            )
        )
        assert db.get(ResearchJob, stage.id).status == "completed"
        assert db.scalar(select(func.count()).select_from(ResearchAttempt)) == 1


def test_news_clusters_merge_only_with_compatible_raw_scope():
    with SessionLocal() as db:
        seed(db)
        for raw in db.scalars(select(Event)):
            raw.event_type = "news"
        db.commit()
        assert len(event_views(db)) == 2  # Different issuers must remain separate.
        for link in db.scalars(select(EventEntityLink)):
            link.entity_key = "AAA"
        db.commit()
        rows = event_views(db)
        assert len(rows) == 1
        assert rows[0]["event_key"].startswith("normalized:")
        assert len(rows[0]["raw_event_ids"]) == 2
        assert len({e["document_id"] for e in rows[0]["evidence"]}) == 2


def test_reserved_call_recovers_without_reserving_twice(monkeypatch):
    from types import SimpleNamespace
    from app.services.research_intelligence_service import profile_input
    from app.domain.research_relevance import fingerprint

    with SessionLocal() as db:
        user, _, instrument, _ = seed(db)
        root = enqueue_batch(
            db, user, BatchRequest(client_request_id="reserved", instrument_ids=[instrument.id])
        )
        company = db.scalar(
            select(ResearchJob).where(
                ResearchJob.parent_id == root["id"], ResearchJob.job_type == "company"
            )
        )
        payload = profile_input(db, instrument)
        stage = ResearchJob(
            user_id=user.id,
            parent_id=root["id"],
            instrument_id=instrument.id,
            job_type="profile",
            dedup_key=company.id + ":profile:" + fingerprint(payload),
            request_hash=fingerprint(payload),
            status="running",
            max_calls=1,
        )
        db.add(stage)
        db.flush()
        db.add(
            ResearchAttempt(
                job_id=stage.id,
                provider="gemini",
                model="offline-test-model",
                status="reserved",
                request_hash=fingerprint(payload),
            )
        )
        db.get(ResearchJob, root["id"]).reserved_calls = 1
        db.commit()
        calls = []

        async def respond(*args, **kwargs):
            calls.append(args)
            return LLMProviderResult(
                provider="gemini",
                model="offline-test-model",
                content='{"relationships":[],"coverage_gaps":["No reports"]}',
            )

        monkeypatch.setattr(
            research_worker, "get_provider", lambda _: SimpleNamespace(chat_with_options=respond)
        )
        asyncio.run(
            research_worker.call_stage(
                db,
                company,
                user,
                instrument,
                "profile",
                payload,
                {"provider": "gemini", "model": "offline-test-model"},
            )
        )
        assert len(calls) == 1
        assert db.get(ResearchJob, root["id"]).reserved_calls == 1
        assert stage.status == "completed"


def test_profile_schema_quotes_are_contiguous_source_excerpts():
    from app.services.research_generation_service import generation_request

    source = "The company earns interest income from floating rate deposits and investments held for its operating cash requirements."
    messages, schema = generation_request(
        "profile", {"evidence": [{"id": "chunk:real", "text": source}]}
    )
    prompt_schema = json.loads(messages[1]["content"].split("OUTPUT_SCHEMA\n")[1])
    quotes = prompt_schema["$defs"]["SupportingQuote"]["properties"]["quote"]["enum"]
    assert "enum" not in schema["$defs"]["SupportingQuote"]["properties"]["quote"]
    assert quotes and all(q in source for q in quotes)
    assert len(messages) == 2


def test_events_without_current_source_chunks_are_excluded():
    from sqlalchemy import delete
    from app.models.document import Citation

    with SessionLocal() as db:
        seed(db)
        db.execute(delete(Citation))
        db.execute(delete(DocumentChunk))
        db.commit()
        assert event_views(db) == []


def test_digest_rejects_financial_quantity_without_structured_fact():
    payload = {
        "events": [
            {
                "event_key": "raw:real",
                "relationship_kind": "direct",
                "evidence": [{"id": "chunk:real", "text": "Reported results."}],
            }
        ]
    }
    output = {
        "events": [
            {
                "event_key": "raw:real",
                "relationship_kind": "direct",
                "status": "explained",
                "what_happened": {
                    "text": "Revenue was PKR 9 billion.",
                    "evidence_ids": ["chunk:real"],
                },
                "why_it_matters": [],
                "countereffects": [],
                "unknowns": [],
            }
        ]
    }
    with pytest.raises(ValueError, match="numerical_claim_requires_structured_fact"):
        validate_output("digest", json.dumps(output), payload)


def test_digest_rejects_quantity_that_differs_from_cited_database_value():
    payload = {
        "facts": [{"id": "fact:real", "value": "8000000000", "unit": "PKR"}],
        "events": [
            {
                "event_key": "raw:real",
                "relationship_kind": "direct",
                "evidence": [{"id": "chunk:real", "text": "Reported results."}],
            }
        ],
    }
    output = {
        "events": [
            {
                "event_key": "raw:real",
                "relationship_kind": "direct",
                "status": "explained",
                "what_happened": {
                    "text": "Revenue was PKR 9 billion.",
                    "evidence_ids": ["chunk:real"],
                    "fact_ids": ["fact:real"],
                },
                "why_it_matters": [],
                "countereffects": [],
                "unknowns": [],
            }
        ]
    }
    with pytest.raises(ValueError, match="numerical_claim_value_mismatch"):
        validate_output("digest", json.dumps(output), payload)
    output["events"][0]["what_happened"]["text"] = "Revenue was PKR 8 billion."
    assert validate_output("digest", json.dumps(output), payload)["events"]
