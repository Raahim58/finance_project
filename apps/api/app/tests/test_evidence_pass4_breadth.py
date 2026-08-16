import json

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate
from app.ingestion.evidence_catalog import SOURCE_SPECS, build_pass1_registry
from app.models.workstation import DataSource
from app.providers.evidence.sources import HttpEvidenceSource
from app.services.evidence_canary_service import reserve_fetch
from app.services.evidence_pipeline import ensure_source_config, persist_candidate


BREADTH_KEYS = {
    "reuters_world",
    "bloomberg_markets",
    "financial_times",
    "associated_press",
    "new_york_times",
    "bbc_world",
    "guardian_world",
    "cnbc_top_news",
    "nikkei_asia",
    "al_jazeera",
    "zeteo",
    "semiconductor_engineering",
    "eetimes",
    "electrive",
    "mining_com",
    "lng_prime",
    "gcaptain",
    "freightwaves",
    "cotton_grower",
    "fertilizer_daily",
    "coal_age",
    "mpoc",
    "metalminer",
    "steel_market_update",
}

DORMANT_KEYS = {
    "reuters_world",
    "bloomberg_markets",
    "financial_times",
    "new_york_times",
    "al_jazeera",
    "mining_com",
}

LISTING_FIXTURES = {
    "reuters_world": "https://www.reuters.com/world/example-story/",
    "associated_press": "https://apnews.com/article/example-story",
}


def test_breadth_catalog_matches_the_agreed_source_scope():
    specs = {spec.key: spec for spec in SOURCE_SPECS if spec.canary_group == "pass4_breadth"}
    assert set(specs) == BREADTH_KEYS
    assert BREADTH_KEYS <= set(build_pass1_registry().keys())
    assert all(not specs[key].enabled for key in DORMANT_KEYS)
    assert all(
        specs[key].enabled is settings.evidence_pass4_breadth_enabled
        for key in BREADTH_KEYS - DORMANT_KEYS
    )
    assert all(spec.historical_days == 90 for spec in specs.values())
    assert all(spec.daily_fetch_budget <= 8 for spec in specs.values())
    assert all(spec.daily_selected_budget <= 4 for spec in specs.values())

    tier_one = {
        "reuters_world",
        "bloomberg_markets",
        "financial_times",
        "associated_press",
        "new_york_times",
        "bbc_world",
        "guardian_world",
        "cnbc_top_news",
        "nikkei_asia",
    }
    assert all(specs[key].tier == "reporting" for key in tier_one)
    assert "geopolitics" in specs["zeteo"].categories
    assert {"semiconductors", "ai_infrastructure"} <= set(
        specs["semiconductor_engineering"].categories
    )
    assert {"shipping", "freight"} <= set(specs["gcaptain"].categories)


@pytest.mark.parametrize("source_key", sorted(BREADTH_KEYS))
def test_every_breadth_source_has_a_generic_adapter_fixture(source_key):
    spec = next(item for item in SOURCE_SPECS if item.key == source_key)
    if spec.discovery_method == "rss":
        article_url = f"{spec.base_url}/fixture-story"
        payload = (
            "<?xml version='1.0'?><rss version='2.0'><channel><item>"
            f"<guid>{source_key}-1</guid><title>Official market sector update</title>"
            f"<link>{article_url}</link>"
            "</item></channel></rss>"
        ).encode()
    else:
        article_url = LISTING_FIXTURES[source_key]
        payload = (
            f"<html><body><a href='{article_url}'>"
            "Official market sector update</a></body></html>"
        ).encode()

    def fetcher(*args, **kwargs):
        del kwargs
        return (
            payload,
            str(args[0]),
            "application/rss+xml" if spec.discovery_method == "rss" else "text/html",
            {},
        )

    source = HttpEvidenceSource(
        spec.key,
        spec.name,
        spec.discovery_url,
        spec.discovery_method,
        spec.topic,
        link_pattern=spec.link_pattern,
        fetcher=fetcher,
    )
    candidates = source.discover_since({}, 2).candidates
    assert len(candidates) == 1
    assert candidates[0].source_key == source_key
    assert candidates[0].observed_url.startswith("https://")


def test_breadth_source_config_persists_shared_canary_and_provenance():
    with SessionLocal() as db:
        data_source, config, _ = ensure_source_config(db, "semiconductor_engineering")
        db.commit()

        assert data_source.enabled is settings.evidence_pass4_breadth_enabled
        assert config.canary_group == "pass4_breadth"
        assert config.daily_fetch_budget == 6
        assert config.daily_selected_budget == 3
        assert json.loads(config.provenance_json)["adapter"] == "rss"
        assert json.loads(config.provenance_json)["authority"] == "specialist"
        assert json.loads(config.fallback_json)["browser"] is False
        assert db.scalar(select(DataSource).where(DataSource.id == data_source.id)) is not None


def test_dormant_breadth_sources_preserve_documented_non_browser_fallbacks():
    specs = {spec.key: spec for spec in SOURCE_SPECS if spec.key in DORMANT_KEYS}
    assert "401" in specs["reuters_world"].fallback
    assert "403" in specs["bloomberg_markets"].fallback
    assert "403" in specs["financial_times"].fallback
    assert "403" in specs["new_york_times"].fallback
    assert "DNS" in specs["al_jazeera"].fallback
    assert "403" in specs["mining_com"].fallback
    assert all("browser" not in spec.fallback.lower() for spec in specs.values())


def test_official_and_breadth_sources_share_one_global_fetch_ceiling(monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setattr(settings, "evidence_canary_fetch_daily", 1)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        official_config = ensure_source_config(db, "secp_releases")[1]
        breadth_config = ensure_source_config(db, "semiconductor_engineering")[1]
        official, _ = persist_candidate(
            db,
            official_config,
            Candidate(
                "secp_releases",
                "https://www.secp.gov.pk/media-center/shared-budget",
                "Pakistan securities policy update",
                "SECP",
                now,
                "listing_page",
                external_id="shared-budget-official",
            ),
        )
        breadth, _ = persist_candidate(
            db,
            breadth_config,
            Candidate(
                "semiconductor_engineering",
                "https://semiengineering.com/shared-budget",
                "Semiconductor supply update",
                "Semiconductor Engineering",
                now,
                "rss_atom",
                external_id="shared-budget-breadth",
            ),
        )

        assert reserve_fetch(db, official, official_config, now=now).allowed
        assert not reserve_fetch(db, breadth, breadth_config, now=now).allowed
