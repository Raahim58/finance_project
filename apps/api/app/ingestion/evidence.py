"""Typed, network-free contracts for Global Evidence ingestion.

Pass 0 defines orchestration boundaries only. Concrete providers and workers are
added in later passes so importing this module can never trigger source traffic.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class CandidateStatus(StrEnum):
    DISCOVERED = "discovered"
    FETCH_READY = "fetch_ready"
    EVALUATING = "evaluating"
    CLUSTERED = "clustered"
    SELECTED = "selected"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"


TERMINAL_CANDIDATE_STATUSES = frozenset(
    {
        CandidateStatus.SELECTED,
        CandidateStatus.DUPLICATE,
        CandidateStatus.REJECTED,
        CandidateStatus.EXPIRED,
    }
)

ALLOWED_CANDIDATE_TRANSITIONS: Mapping[CandidateStatus, frozenset[CandidateStatus]] = {
    CandidateStatus.DISCOVERED: frozenset(
        {CandidateStatus.FETCH_READY, CandidateStatus.REJECTED, CandidateStatus.EXPIRED}
    ),
    CandidateStatus.FETCH_READY: frozenset(
        {CandidateStatus.EVALUATING, CandidateStatus.REJECTED, CandidateStatus.EXPIRED}
    ),
    CandidateStatus.EVALUATING: frozenset(
        {
            CandidateStatus.CLUSTERED,
            CandidateStatus.DUPLICATE,
            CandidateStatus.REJECTED,
            CandidateStatus.FAILED,
        }
    ),
    CandidateStatus.FAILED: frozenset(
        {CandidateStatus.FETCH_READY, CandidateStatus.EXPIRED}
    ),
    CandidateStatus.CLUSTERED: frozenset(
        {
            CandidateStatus.SELECTED,
            CandidateStatus.DUPLICATE,
            CandidateStatus.REJECTED,
            CandidateStatus.FAILED,
        }
    ),
    CandidateStatus.SELECTED: frozenset(),
    CandidateStatus.DUPLICATE: frozenset(),
    CandidateStatus.REJECTED: frozenset(),
    CandidateStatus.EXPIRED: frozenset(),
}


def validate_candidate_transition(
    current: CandidateStatus | str,
    target: CandidateStatus | str,
) -> CandidateStatus:
    """Return the normalized target or reject an invalid state transition."""

    current_status = CandidateStatus(current)
    target_status = CandidateStatus(target)
    if target_status not in ALLOWED_CANDIDATE_TRANSITIONS[current_status]:
        raise ValueError(
            f"Invalid evidence candidate transition: {current_status.value} -> {target_status.value}"
        )
    return target_status


@dataclass(frozen=True)
class Candidate:
    source_key: str
    observed_url: str
    headline: str
    publisher: str
    discovered_at: datetime
    discovery_method: str
    external_id: str | None = None
    canonical_url: str | None = None
    published_at: datetime | None = None
    topic: str | None = None
    language: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryBatch:
    candidates: tuple[Candidate, ...]
    next_cursor: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawContent:
    candidate: Candidate
    content: bytes
    content_type: str
    retrieved_at: datetime
    final_url: str
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedEvidence:
    canonical_url: str
    title: str
    body: str
    published_at: datetime | None
    source_key: str
    body_sha256: str
    parser_method: str
    extraction_quality: float
    author: str | None = None
    language: str | None = None
    sections: tuple[str, ...] = ()
    entity_keys: tuple[str, ...] = ()
    important_number_fingerprints: tuple[str, ...] = ()
    simhash: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class EvidenceSource(Protocol):
    key: str

    def discover_since(
        self,
        cursor: Mapping[str, Any] | None,
        limit: int,
    ) -> DiscoveryBatch: ...

    def fetch(self, candidate: Candidate) -> RawContent: ...

    def normalize(self, raw: RawContent) -> ParsedEvidence: ...


class EvidenceSourceRegistry:
    """Small explicit registry; it has no import-time provider discovery."""

    def __init__(self) -> None:
        self._sources: dict[str, EvidenceSource] = {}

    def register(self, source: EvidenceSource) -> None:
        key = source.key.strip().lower()
        if not key:
            raise ValueError("Evidence source key cannot be blank")
        if key in self._sources:
            raise ValueError(f"Evidence source {key!r} is already registered")
        self._sources[key] = source

    def get(self, key: str) -> EvidenceSource:
        normalized = key.strip().lower()
        try:
            return self._sources[normalized]
        except KeyError as exc:
            raise KeyError(f"Unknown evidence source {normalized!r}") from exc

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._sources))
