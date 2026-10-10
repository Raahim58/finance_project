from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.ingestion.evidence import Candidate, DiscoveryBatch, EvidenceSourceRegistry, RawContent


NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)






@pytest.fixture(autouse=True)
def _enable_psx_history_for_history_contract_tests(monkeypatch):
    monkeypatch.setattr(settings, "evidence_psx_announcement_history_enabled", True)


class PagedPsxSource:
    key = "psx_announcements"

    def discover_since(self, cursor, limit):
        offset = int((cursor or {}).get("offset", 0))
        if offset:
            return DiscoveryBatch((), {"offset": offset})
        rows = tuple(
            Candidate(
                source_key=self.key,
                observed_url=f"https://dps.psx.com.pk/announcements?id={index}",
                canonical_url=f"https://dps.psx.com.pk/announcements?id={index}",
                external_id=str(index),
                headline=f"Company financial results {index}",
                publisher="Pakistan Stock Exchange",
                discovered_at=NOW,
                published_at=NOW,
                discovery_method="psx_announcements_post",
                topic="psx_company",
                metadata={"symbol": "HBL", "category": "financial_results"},
            )
            for index in range(limit)
        )
        return DiscoveryBatch(rows, {"offset": limit})

    def fetch(self, candidate):
        return RawContent(candidate, b"{}", "application/json", NOW, candidate.observed_url)

    def normalize(self, raw):
        raise AssertionError("not used in a discovery-only test")


class OversizePsxSource(PagedPsxSource):
    def fetch(self, candidate):
        return RawContent(candidate, b"x" * 20, "application/json", NOW, candidate.observed_url)


class Registry:
    def __init__(self, source):
        self.source = source

    def get(self, key):
        assert key == self.source.key
        return self.source




















def test_registry_contract_still_has_no_pass4_sources():
    from app.ingestion.evidence_catalog import build_pass1_registry

    registry: EvidenceSourceRegistry = build_pass1_registry()
    assert "google_news_archive" not in registry.keys()
    assert "fed_releases" not in registry.keys()


