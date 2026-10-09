"""Offline evidence pipeline contracts and fixtures."""

from sqlalchemy import func, select
from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import RawContent
from app.models.document import Citation, Document, DocumentChunk
from app.models.evidence import DiscoveryCandidate, EvidenceSourceState
from app.models.workstation import Event, EventSource, MacroObservation
from app.services.evidence_pipeline import run_source_once
from app.tests.support.evidence import FixtureDawnSource, BrokenDiscoverySource
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_synchronous_pdf_ingestion_routes_text_and_preserves_page_citations(tmp_path, monkeypatch):
    from app.providers.evidence.sources import HttpEvidenceSource
    from app.services.rag_service import ParsedPage

    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path))
    pages = [
        ParsedPage(
            2,
            "Pakistan inflation and SBP policy rate decisions affect reserves and the economic outlook.",
        )
    ]
    monkeypatch.setattr("app.services.evidence_operations.parse_pdf", lambda content: pages)
    monkeypatch.setattr("app.services.evidence_pipeline.parse_pdf", lambda content: pages)

    class PdfSource(FixtureDawnSource):
        def fetch(self, candidate):
            return RawContent(
                candidate, b"%PDF-fixture", "application/pdf", self.now, candidate.observed_url
            )

        def normalize(self, raw):
            return HttpEvidenceSource("dawn", "Dawn", "https://example.com", "rss").normalize(raw)

    with SessionLocal() as db:
        result = run_source_once(db, PdfSource(), limit=1)
        assert result.selected == 1
        assert db.scalar(select(DiscoveryCandidate.parser_version)) == "pypdf_evidence_v1"
        assert db.scalar(select(DocumentChunk.page_number)) == 2
        assert db.scalar(select(Citation.page_number)) == 2


def test_end_to_end_selection_indexes_once_and_keeps_exact_numbers_out_of_fact_tables(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    with SessionLocal() as db:
        first = run_source_once(db, FixtureDawnSource(), limit=10)
        second = run_source_once(db, FixtureDawnSource(), limit=10)

        assert first.discovered == 1
        assert first.evaluated == 1
        assert first.selected == 1
        assert second.discovered == 1
        assert second.evaluated == 0
        candidate = db.scalar(select(DiscoveryCandidate))
        event_source = db.scalar(select(EventSource))
        state = db.scalar(select(EvidenceSourceState))
        assert candidate.status == "selected"
        assert candidate.event_id == db.scalar(select(Event.id))
        assert event_source.selection_status == "selected"
        assert event_source.document_id is not None
        assert db.scalar(select(func.count()).select_from(Document)) == 1
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 1
        assert db.scalar(select(func.count()).select_from(Citation)) == 1
        assert db.scalar(select(func.count()).select_from(MacroObservation)) == 0
        assert "last_id" in state.cursor_json
        artifact_path = tmp_path / "artifacts"
        assert any(artifact_path.rglob("*.bin"))


def test_discovery_failure_is_recorded_in_durable_source_state():
    with SessionLocal() as db:
        result = run_source_once(db, BrokenDiscoverySource())
        state = db.scalar(select(EvidenceSourceState))
        assert result.failed == 1
        assert state.consecutive_failures == 1
        assert state.last_error_class == "ValueError"
        assert "discovery" in state.diagnostics_json
