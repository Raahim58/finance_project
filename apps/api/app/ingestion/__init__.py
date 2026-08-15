"""Verified-source ingestion primitives."""

from app.ingestion.evidence import (
    ALLOWED_CANDIDATE_TRANSITIONS,
    Candidate,
    CandidateStatus,
    DiscoveryBatch,
    EvidenceSource,
    EvidenceSourceRegistry,
    ParsedEvidence,
    RawContent,
    validate_candidate_transition,
)

__all__ = [
    "ALLOWED_CANDIDATE_TRANSITIONS",
    "Candidate",
    "CandidateStatus",
    "DiscoveryBatch",
    "EvidenceSource",
    "EvidenceSourceRegistry",
    "ParsedEvidence",
    "RawContent",
    "validate_candidate_transition",
]
