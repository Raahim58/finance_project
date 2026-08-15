from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.evidence import (
    Candidate,
    CandidateStatus,
    DiscoveryBatch,
    EvidenceSource,
    EvidenceSourceRegistry,
    ParsedEvidence,
    RawContent,
    validate_candidate_transition,
)
from app.models.evidence import DiscoveryCandidate, EvidenceSourceConfig, EvidenceSourceState
from app.models.workstation import DataSource, Event, EventSource


class FixtureEvidenceSource:
    key = "fixture"

    def discover_since(self, cursor, limit: int) -> DiscoveryBatch:
        del cursor
        candidate = Candidate(
            source_key=self.key,
            observed_url="https://example.com/story",
            headline="Observed fixture story",
            publisher="Fixture Publisher",
            discovered_at=datetime.now(UTC),
            discovery_method="fixture",
        )
        return DiscoveryBatch((candidate,)[:limit], {"page": 2})

    def fetch(self, candidate: Candidate) -> RawContent:
        return RawContent(
            candidate=candidate,
            content=b"fixture body",
            content_type="text/plain",
            retrieved_at=datetime.now(UTC),
            final_url=candidate.observed_url,
        )

    def normalize(self, raw: RawContent) -> ParsedEvidence:
        return ParsedEvidence(
            canonical_url=raw.final_url,
            title=raw.candidate.headline,
            body=raw.content.decode(),
            published_at=None,
            source_key=self.key,
            body_sha256="0" * 64,
            parser_method="fixture",
            extraction_quality=1.0,
        )


def test_source_registry_is_explicit_and_rejects_duplicates():
    source = FixtureEvidenceSource()
    assert isinstance(source, EvidenceSource)
    registry = EvidenceSourceRegistry()
    registry.register(source)
    assert registry.keys() == ("fixture",)
    assert registry.get(" FIXTURE ") is source
    with pytest.raises(ValueError, match="already registered"):
        registry.register(source)
    with pytest.raises(KeyError, match="Unknown evidence source"):
        registry.get("missing")


def test_candidate_state_machine_allows_retry_but_protects_terminal_states():
    assert (
        validate_candidate_transition(CandidateStatus.DISCOVERED, "fetch_ready")
        is CandidateStatus.FETCH_READY
    )
    assert validate_candidate_transition("failed", "fetch_ready") is CandidateStatus.FETCH_READY
    assert validate_candidate_transition("clustered", "selected") is CandidateStatus.SELECTED
    with pytest.raises(ValueError, match="selected -> fetch_ready"):
        validate_candidate_transition("selected", "fetch_ready")
    with pytest.raises(ValueError, match="discovered -> selected"):
        validate_candidate_transition("discovered", "selected")


def test_evidence_models_persist_source_state_candidate_and_cluster_links():
    with SessionLocal() as db:
        data_source = DataSource(
            name="Fixture Evidence",
            source_type="evidence",
            base_url="https://example.com",
            priority=10,
            enabled=False,
        )
        db.add(data_source)
        db.flush()
        config = EvidenceSourceConfig(
            data_source_id=data_source.id,
            source_key="fixture",
            source_tier="official",
            roles_json='["primary"]',
            discovery_methods_json='["rss"]',
            fetch_methods_json='["http"]',
            poll_interval_seconds=300,
            historical_days=90,
        )
        db.add(config)
        db.flush()
        state = EvidenceSourceState(source_config_id=config.id, cursor_json='{"page": 1}')
        event = Event(
            event_type="news",
            title="Fixture cluster",
            occurred_at=datetime.now(UTC),
            cluster_key="a" * 64,
            topic="pakistan_macro",
            geography="PK",
        )
        db.add_all([state, event])
        db.flush()
        candidate = DiscoveryCandidate(
            source_config_id=config.id,
            external_id="fixture-1",
            observed_url="https://example.com/story",
            canonical_url="https://example.com/story",
            canonical_url_hash="b" * 64,
            headline="Fixture story",
            publisher="Fixture Evidence",
            discovery_method="rss",
            topic="pakistan_macro",
            status=CandidateStatus.CLUSTERED.value,
            event_id=event.id,
            relevance_score=Decimal("0.900000"),
        )
        db.add(candidate)
        db.flush()
        source = EventSource(
            event_id=event.id,
            candidate_id=candidate.id,
            source_url=candidate.canonical_url,
            source_name="Fixture Evidence",
            evidence_role="official",
            selection_status="selected",
            relevance_score=Decimal("0.900000"),
        )
        db.add(source)
        db.commit()

        stored = db.scalar(
            select(DiscoveryCandidate).where(DiscoveryCandidate.external_id == "fixture-1")
        )
        stored_source = db.scalar(
            select(EventSource).where(EventSource.candidate_id == stored.id)
        )
        assert stored.status == CandidateStatus.CLUSTERED.value
        assert stored.event_id == event.id
        assert stored_source.selection_status == "selected"
        assert stored_source.evidence_role == "official"
        assert db.get(EvidenceSourceState, state.id).cursor_json == '{"page": 1}'
