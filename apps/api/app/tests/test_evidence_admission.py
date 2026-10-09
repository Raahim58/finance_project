"""Offline evidence admission contracts and fixtures."""

import json
from sqlalchemy import select
from app.db.session import SessionLocal
import hashlib
from app.ingestion.evidence import Candidate, ParsedEvidence
from app.models.evidence import DiscoveryCandidate
from app.models.workstation import Instrument, InstrumentAlias
from app.services.evidence_pipeline import (
    ensure_source_config,
    persist_candidate,
    run_source_once,
    score_evidence,
)
from app.tests.support.evidence import FixtureDawnSource, IrrelevantDawnSource
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_global_market_channels_pass_metadata_without_company_link():
    from dataclasses import replace
    from app.services.evidence_pipeline import score_candidate_metadata

    candidate = FixtureDawnSource().discover_since({}, 1).candidates[0]
    with SessionLocal() as db:
        for headline in (
            "New sanctions announced",
            "Export controls expanded",
            "Freight rates climb",
            "Freight Market Update: 5 Signals Capacity Is Tight",
            "Aurora reports Q2 results, details per-mile pricing",
        ):
            score = score_candidate_metadata(
                db, replace(candidate, source_key="bbc_world", headline=headline)
            )
            assert score.relevance >= 0.30
            assert score.entity_keys == ()
        for headline in (
            "Local automakers voice concerns as imports of used cars surge in Sept",
            "Gold prices rise as bond yields fall",
            "Manufacturing activity contracts",
            "Company quarterly earnings fall",
            "Remittances support the currency",
        ):
            score = score_candidate_metadata(db, replace(candidate, headline=headline))
            assert score.relevance >= 0.30
        for headline in (
            "Coalition announces its sports award winners",
            "China hosts football final",
            "$20M in cocaine found beneath floorboards of commercial truck trailer",
        ):
            score = score_candidate_metadata(
                db, replace(candidate, source_key="bbc_world", headline=headline)
            )
            assert score.relevance < 0.18


def test_repaired_gate_revisits_only_unfetched_metadata_rejections():
    from dataclasses import replace
    from decimal import Decimal

    candidate = replace(
        FixtureDawnSource().discover_since({}, 1).candidates[0], headline="New sanctions announced"
    )
    with SessionLocal() as db:
        _, config, _ = ensure_source_config(db, "dawn")
        row, _ = persist_candidate(db, config, candidate)
        row.status = "rejected"
        row.relevance_score = Decimal("0.14")
        row.scoring_reasons_json = '["geopolitics:sanctions"]'
        _, reconsidered = persist_candidate(db, config, candidate)
        assert reconsidered and row.status == "fetch_ready"
        assert json.loads(row.metadata_json)["prior_metadata_rejection"]["score"] == "0.14"
        row.status = "rejected"
        row.body_sha256 = "previously-parsed-body"
        _, reconsidered = persist_candidate(db, config, candidate)
        assert not reconsidered and row.status == "rejected"


def test_relevance_uses_dynamic_instruments_aliases_and_sector_drivers():
    with SessionLocal() as db:
        instrument = Instrument(symbol="HBL", name="Habib Bank Limited", sector="Commercial Banks")
        db.add(instrument)
        db.flush()
        db.add(InstrumentAlias(instrument_id=instrument.id, provider="fixture", alias="Habib Bank"))
        db.flush()
        candidate = Candidate(
            "dawn",
            "https://example.com/hbl",
            "Habib Bank outlook",
            "Dawn",
            FixtureDawnSource.now,
            "rss",
        )
        body = "Habib Bank faces KIBOR and government borrowing changes in Pakistan."
        parsed = ParsedEvidence(
            canonical_url=candidate.observed_url,
            title=candidate.headline,
            body=body,
            published_at=candidate.discovered_at,
            source_key="dawn",
            body_sha256=hashlib.sha256(body.encode()).hexdigest(),
            parser_method="fixture",
            extraction_quality=1.0,
        )
        score = score_evidence(db, parsed, candidate)
        assert score.relevance == 1.0
        assert score.entity_keys == ("HBL",)
        assert any(reason.startswith("sector_driver:Commercial Banks") for reason in score.reasons)


def test_official_psx_scoring_trusts_declared_symbol_not_incidental_aliases():
    with SessionLocal() as db:
        db.add_all(
            [
                Instrument(symbol="AAA", name="Alpha Limited", sector="Commercial Banks"),
                Instrument(symbol="CASH", name="Cash Corporation", sector="Other"),
            ]
        )
        db.flush()
        candidate = Candidate(
            "psx_announcements",
            "https://dps.psx.com.pk/announcement/1",
            "Board Meeting / Closed Period",
            "Pakistan Stock Exchange",
            FixtureDawnSource.now,
            "api",
            metadata={"symbol": "AAA"},
        )
        parsed = ParsedEvidence(
            canonical_url=candidate.observed_url,
            title=candidate.headline,
            body="The company reviewed its cash position at the board meeting.",
            published_at=candidate.discovered_at,
            source_key=candidate.source_key,
            body_sha256="a" * 64,
            parser_method="fixture",
            extraction_quality=1.0,
            entity_keys=("AAA",),
        )

        score = score_evidence(db, parsed, candidate)

        assert score.entity_keys == ("AAA",)


def test_news_scoring_does_not_treat_lowercase_words_as_tickers():
    with SessionLocal() as db:
        db.add(Instrument(symbol="CASH", name="Cash Corporation", sector="Other"))
        db.flush()
        candidate = Candidate(
            "dawn",
            "https://example.com/liquidity",
            "Households face a cash squeeze",
            "Dawn",
            FixtureDawnSource.now,
            "rss",
        )
        body = "Higher costs may reduce cash balances next quarter."
        parsed = ParsedEvidence(
            canonical_url=candidate.observed_url,
            title=candidate.headline,
            body=body,
            published_at=candidate.discovered_at,
            source_key=candidate.source_key,
            body_sha256=hashlib.sha256(body.encode()).hexdigest(),
            parser_method="fixture",
            extraction_quality=1.0,
        )

        score = score_evidence(db, parsed, candidate)

        assert "CASH" not in score.entity_keys


def test_metadata_gate_rejects_irrelevant_candidate_without_fetching():
    with SessionLocal() as db:
        result = run_source_once(db, IrrelevantDawnSource())
        candidate = db.scalar(select(DiscoveryCandidate))
        assert result.rejected == 1
        assert result.evaluated == 0
        assert candidate.status == "rejected"
        assert "no_substantive_metadata_match" in candidate.scoring_reasons_json
