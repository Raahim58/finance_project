from datetime import UTC, datetime

import pytest

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
