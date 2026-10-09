import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate, DiscoveryBatch, RawContent
from app.models.document import Document
from app.models.evidence import DiscoveryCandidate, EvidenceSourceState
from app.models.workstation import EventSource, Instrument
from app.services.evidence_operations import (
    EvidenceSpool,
    discover_stage,
    fetch_stage,
    index_stage,
    parse_stage,
)


NOW = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)




class StagedDawnSource:
    key = "dawn"

    def discover_since(self, cursor, limit):
        del cursor
        candidate = Candidate(
            source_key=self.key,
            observed_url="https://www.dawn.com/news/staged-pass2",
            canonical_url="https://www.dawn.com/news/staged-pass2",
            external_id="staged-pass2",
            headline="MEBL outlook amid Pakistan inflation and SBP policy rates",
            publisher="Dawn",
            discovered_at=NOW,
            published_at=NOW,
            discovery_method="rss_atom",
            topic="pakistan_macro",
        )
        return DiscoveryBatch((candidate,)[:limit], {"last_id": candidate.external_id})

    def fetch(self, candidate):
        html = b"""<html><script type="application/ld+json">{"@type":"NewsArticle","headline":"MEBL outlook amid Pakistan inflation and SBP policy rates","datePublished":"2026-08-14T10:00:00Z","articleBody":"Meezan Bank Limited and MEBL are assessing Pakistan inflation and the SBP policy rate outlook."}</script></html>"""
        return RawContent(candidate, html, "text/html", NOW, candidate.observed_url)

    def normalize(self, raw):
        from app.providers.evidence.extraction import extract_article

        return extract_article(raw)


@pytest.mark.usefixtures("database")
def test_staged_pipeline_spools_then_indexes_selected_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    spool = EvidenceSpool(tmp_path)
    source = StagedDawnSource()
    with SessionLocal() as db:
        db.add(Instrument(symbol="MEBL", name="Meezan Bank Limited", sector="Commercial Banks"))
        db.flush()
        discovered = discover_stage(db, source, limit=10)
        candidate_id = discovered.candidate_ids[0]
        fetched = fetch_stage(db, source, candidate_id, spool=spool)
        parsed = parse_stage(db, source, candidate_id, spool=spool)

        assert fetched.outcome == "raw_ready"
        assert parsed.outcome == "index_ready"
        assert db.get(DiscoveryCandidate, candidate_id).status == "clustered"
        assert db.scalar(select(EventSource)).selection_status == "pending"
        assert spool.read_raw(candidate_id)
        assert spool.read_parsed(candidate_id).body_sha256

        indexed = index_stage(db, candidate_id, spool=spool)
        assert indexed.outcome == "selected"
        assert db.get(DiscoveryCandidate, candidate_id).status == "selected"
        assert db.scalar(select(EventSource)).selection_status == "selected"
        document = db.scalar(select(Document))
        assert document.document_type == "news"
        assert document.symbol == "MEBL"
        assert not (spool.root / f"{candidate_id}.raw").exists()


class BrokenDawnSource(StagedDawnSource):
    def discover_since(self, cursor, limit):
        raise RuntimeError("fixture source unavailable")


@pytest.mark.usefixtures("database")
def test_source_circuit_opens_after_configured_failures(monkeypatch):
    monkeypatch.setattr(settings, "evidence_circuit_failure_threshold", 2)
    with SessionLocal() as db:
        for _ in range(2):
            with pytest.raises(RuntimeError, match="unavailable"):
                discover_stage(db, BrokenDawnSource(), limit=5)
        state = db.scalar(select(EvidenceSourceState))
        diagnostics = json.loads(state.diagnostics_json)
        assert state.consecutive_failures == 2
        assert state.next_poll_at is not None
        assert diagnostics["circuit_open_until"] is not None














