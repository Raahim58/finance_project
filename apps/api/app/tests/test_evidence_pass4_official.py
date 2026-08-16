import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate, RawContent
from app.ingestion.evidence_catalog import SOURCE_SPECS, build_pass1_registry
from app.models.evidence import DiscoveryCandidate
from app.models.workstation import DataSource
from app.providers.evidence.sources import HttpEvidenceSource
from app.services.evidence_canary_service import (
    discovery_allowance,
    record_fetch,
    reserve_fetch,
    reserve_selection,
)
from app.services.evidence_pipeline import ensure_source_config, persist_candidate
from app.services.evidence_operations import EvidenceSpool, fetch_stage


OFFICIAL_CANARY_KEYS = {
    "mof_pakistan",
    "pbs_releases",
    "secp_releases",
    "nepra_releases",
    "ogra_releases",
    "nccpl_notices",
    "world_bank_news",
    "federal_reserve",
    "ecb_releases",
    "bis_releases",
    "eia_releases",
    "opec_releases",
    "sec_edgar_current",
    "ofac_actions",
}

LISTING_FIXTURE_URLS = {
    "mof_pakistan": "https://www.finance.gov.pk/example.pdf",
    "pbs_releases": "https://www.pbs.gov.pk/press-release/example/",
    "secp_releases": "https://www.secp.gov.pk/media-center/press-releases/example/",
    "nepra_releases": "https://nepra.org.pk/Press%20Release/example.pdf",
    "ogra_releases": "https://www.ogra.org.pk/press-release-example",
    "nccpl_notices": "https://www.nccpl.com.pk/legal-framework/example",
    "world_bank_news": "https://www.worldbank.org/en/news/press-release/example",
    "opec_releases": "https://www.opec.org/pr-detail/example",
    "ofac_actions": "https://ofac.treasury.gov/recent-actions/example",
}


def test_pass4_registry_contains_only_requested_official_canary_sources():
    canary_specs = {spec.key: spec for spec in SOURCE_SPECS if spec.canary_group}
    assert set(canary_specs) == OFFICIAL_CANARY_KEYS
    assert all(spec.tier == "official" for spec in canary_specs.values())
    assert all(spec.discovery_method in {"rss", "listing"} for spec in canary_specs.values())
    assert OFFICIAL_CANARY_KEYS <= set(build_pass1_registry().keys())
    assert not {"reuters", "bloomberg", "ft", "specialist_sector"} & set(canary_specs)
    assert canary_specs["sec_edgar_current"].enabled is False
    assert canary_specs["nccpl_notices"].enabled is False


def test_official_source_config_persists_bounds_provenance_and_fallback():
    with SessionLocal() as db:
        data_source, config, _ = ensure_source_config(db, "secp_releases")
        db.commit()

        assert data_source.enabled is settings.evidence_pass4_official_enabled
        assert config.canary_group == "pass4_official"
        assert config.daily_fetch_budget == 25
        assert config.daily_selected_budget == 10
        assert json.loads(config.provenance_json)["adapter"] == "listing"
        assert json.loads(config.provenance_json)["authority"] == "official"
        assert json.loads(config.fallback_json)["browser"] is False
        assert db.scalar(select(DataSource).where(DataSource.id == data_source.id)) is not None


def test_generic_rss_and_listing_adapters_parse_official_fixtures():
    rss = b"""<?xml version='1.0'?><rss version='2.0'><channel><item>
      <guid>fed-1</guid><title>Federal Reserve policy statement</title>
      <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260816a.htm</link>
      <pubDate>Sun, 16 Aug 2026 10:00:00 GMT</pubDate>
    </item></channel></rss>"""
    listing = b"""<html><body>
      <a href='/media-center/press-releases/secp-policy-update/'>SECP policy update</a>
      <a href='https://example.com/unrelated'>Unrelated</a>
    </body></html>"""

    def rss_fetcher(*args, **kwargs):
        return rss, str(args[0]), "application/rss+xml", {}

    def listing_fetcher(*args, **kwargs):
        return listing, str(args[0]), "text/html", {}

    rss_source = HttpEvidenceSource(
        "federal_reserve",
        "Federal Reserve Board",
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "rss",
        "global_macro",
        fetcher=rss_fetcher,
    )
    listing_source = HttpEvidenceSource(
        "secp_releases",
        "Securities and Exchange Commission of Pakistan",
        "https://www.secp.gov.pk/media-center/press-releases/",
        "listing",
        "pakistan_markets",
        link_pattern=r"^https://(?:www\.)?secp\.gov\.pk/(?:media-center|wp-content/uploads)/",
        fetcher=listing_fetcher,
    )

    assert rss_source.discover_since({}, 10).candidates[0].external_id == "fed-1"
    candidates = listing_source.discover_since({}, 10).candidates
    assert len(candidates) == 1
    assert candidates[0].headline == "SECP policy update"


@pytest.mark.parametrize("source_key", sorted(OFFICIAL_CANARY_KEYS))
def test_every_official_source_has_a_generic_adapter_fixture(source_key):
    spec = next(item for item in SOURCE_SPECS if item.key == source_key)
    if spec.discovery_method == "rss":
        payload = (
            "<?xml version='1.0'?><rss version='2.0'><channel><item>"
            f"<guid>{source_key}-1</guid><title>Official policy update</title>"
            f"<link>{spec.base_url}/official-update</link>"
            "</item></channel></rss>"
        ).encode()
    else:
        payload = (
            f"<html><body><a href='{LISTING_FIXTURE_URLS[source_key]}'>"
            "Official policy update</a></body></html>"
        ).encode()

    def fetcher(*args, **kwargs):
        return payload, str(args[0]), "application/xml" if spec.discovery_method == "rss" else "text/html", {}

    source = HttpEvidenceSource(
        spec.key,
        spec.name,
        spec.discovery_url,
        spec.discovery_method,
        spec.topic,
        link_pattern=spec.link_pattern,
        fetcher=fetcher,
    )
    candidates = source.discover_since({}, 1).candidates
    assert len(candidates) == 1
    assert candidates[0].source_key == source_key


def test_canary_budgets_are_reserved_at_each_funnel_boundary(monkeypatch):
    monkeypatch.setattr(settings, "evidence_canary_discovery_daily", 1)
    monkeypatch.setattr(settings, "evidence_canary_fetch_daily", 1)
    monkeypatch.setattr(settings, "evidence_canary_selected_daily", 1)
    monkeypatch.setattr(settings, "evidence_canary_storage_daily_mb", 1)
    monkeypatch.setattr(settings, "evidence_canary_storage_seven_day_mb", 1)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        _, config, _ = ensure_source_config(db, "secp_releases")
        config.daily_discovery_budget = 1
        config.daily_fetch_budget = 1
        config.daily_selected_budget = 1
        config.daily_storage_budget_bytes = 1024
        rows = []
        for suffix in ("one", "two"):
            candidate = Candidate(
                "secp_releases",
                f"https://www.secp.gov.pk/media-center/{suffix}",
                f"Pakistan regulation policy {suffix}",
                "SECP",
                now,
                "listing_page",
                external_id=suffix,
            )
            row, _ = persist_candidate(db, config, candidate)
            rows.append(row)
        db.commit()

        assert discovery_allowance(db, config, 10, now=now) == 0
        assert reserve_fetch(db, rows[0], config, now=now).allowed
        assert not reserve_fetch(db, rows[1], config, now=now).allowed
        assert record_fetch(db, rows[0], config, 512, now=now).allowed
        assert reserve_selection(db, rows[0], config, now=now).allowed
        assert not reserve_selection(db, rows[1], config, now=now).allowed
        db.commit()
        assert db.get(DiscoveryCandidate, rows[0].id).fetched_bytes == 512


def test_canary_storage_rejects_response_over_source_budget():
    now = datetime.now(UTC)
    with SessionLocal() as db:
        _, config, _ = ensure_source_config(db, "secp_releases")
        config.daily_storage_budget_bytes = 100
        candidate = Candidate(
            "secp_releases",
            "https://www.secp.gov.pk/media-center/oversize",
            "Pakistan regulation policy",
            "SECP",
            now,
            "listing_page",
            external_id="oversize",
        )
        row, _ = persist_candidate(db, config, candidate)
        assert reserve_fetch(db, row, config, now=now).allowed
        decision = record_fetch(db, row, config, 101, now=now)
        assert not decision.allowed
        assert decision.reason == "source_daily_storage_budget"


def test_official_canary_samples_low_information_headlines_before_full_relevance_gate(tmp_path):
    now = datetime.now(UTC)

    class OfficialFixtureSource:
        key = "secp_releases"

        def fetch(self, candidate):
            return RawContent(
                candidate,
                b"<html><body>Official regulation update</body></html>",
                "text/html",
                now,
                candidate.observed_url,
            )

    with SessionLocal() as db:
        _, config, _ = ensure_source_config(db, "secp_releases")
        candidate = Candidate(
            "secp_releases",
            "https://www.secp.gov.pk/media-center/press-releases/generic-title",
            "Official update",
            "SECP",
            now,
            "listing_page",
            external_id="generic-title",
        )
        row, _ = persist_candidate(db, config, candidate)
        db.commit()

        result = fetch_stage(db, OfficialFixtureSource(), row.id, spool=EvidenceSpool(tmp_path))

        assert result.outcome == "raw_ready"
        assert db.get(DiscoveryCandidate, row.id).fetched_at is not None
