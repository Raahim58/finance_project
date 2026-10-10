"""Offline research evidence contracts and fixtures."""

from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.models.document import Document, DocumentPage, DocumentChunk
from app.models.workstation import Event, EventSource, EventEntityLink
from app.services.rag_service import ParsedPage, index_document_pages
from app.services.research_intelligence_service import event_views
from app.tests.support.research import seed

pytestmark = pytest.mark.usefixtures("database")


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


def test_news_clusters_merge_only_with_compatible_raw_scope():
    with SessionLocal() as db:
        seed(db)
        for raw in db.scalars(select(Event)):
            raw.event_type = "news"
        for document in db.scalars(select(Document)):
            document.document_type = "news"
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


def test_events_without_current_source_chunks_are_excluded():
    from sqlalchemy import delete
    from app.models.document import Citation

    with SessionLocal() as db:
        seed(db)
        db.execute(delete(Citation))
        db.execute(delete(DocumentChunk))
        db.commit()
        assert event_views(db) == []


def test_scanned_retained_report_uses_bounded_ocr_and_keeps_physical_pages(monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from app.models.workstation import DataSource, SourceArtifact
    from app.services import research_evidence_service as service
    from app.providers.fundamentals.extraction import FinancialPage

    content = b"offline scanned report fixture"
    monkeypatch.setattr(
        service, "get_artifact_store", lambda _: SimpleNamespace(get=lambda _: content)
    )
    monkeypatch.setattr(service, "_native_text_pages", lambda _: [FinancialPage(8, "")])
    monkeypatch.setattr(
        service,
        "parse_financial_pdf",
        lambda _: (
            [FinancialPage(8, "Source financing disclosure from OCR.")],
            "ocr",
            ["Bounded OCR"],
        ),
    )
    with SessionLocal() as db:
        source = DataSource(name="Offline fixture", source_type="report")
        db.add(source)
        db.flush()
        artifact = SourceArtifact(
            data_source_id=source.id,
            sha256=hashlib.sha256(content).hexdigest(),
            storage_path="fixture",
            parser_version="fixture",
            source_url="https://example.test/offline-report.pdf",
        )
        db.add(artifact)
        db.flush()
        doc = Document(
            title="Offline scanned report",
            document_type="annual_report",
            source_name="Fixture",
            content_hash=artifact.sha256,
            artifact_id=artifact.id,
            data_status="observed",
        )
        db.add(doc)
        db.commit()
        result = service.prepare_report(db, doc.id)
        assert result["status"] == "indexed" and result["coverage_note"].startswith("Bounded OCR")
        assert (
            db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id)).page_number
            == 8
        )
