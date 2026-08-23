from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
import hashlib

from app.ingestion.evidence import Candidate, DiscoveryBatch, ParsedEvidence, RawContent
from app.models.document import Citation, Document, DocumentChunk
from app.models.evidence import DiscoveryCandidate, EvidenceSourceState
from app.models.workstation import Event, EventEntityLink, EventSource, Instrument, InstrumentAlias, MacroObservation
from app.services.evidence_pipeline import (
    Score,
    _cluster,
    _find_duplicate,
    ensure_source_config,
    persist_candidate,
    run_source_once,
    score_evidence,
)


class FixtureDawnSource:
    key = "dawn"
    now = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)

    def discover_since(self, cursor, limit):
        del cursor
        item = Candidate(
            source_key=self.key,
            observed_url="https://www.dawn.com/news/pass1",
            canonical_url="https://www.dawn.com/news/pass1",
            external_id="pass1-dawn-1",
            headline="Pakistan inflation and policy rate outlook",
            publisher="Dawn",
            discovered_at=self.now,
            published_at=self.now,
            discovery_method="rss_atom",
            topic="pakistan_macro",
        )
        return DiscoveryBatch((item,)[:limit], {"last_id": "pass1-dawn-1"})

    def fetch(self, candidate):
        html = b'''<html><head><script type="application/ld+json">{"@type":"NewsArticle","headline":"Pakistan inflation and policy rate outlook","datePublished":"2026-08-13T10:00:00Z","articleBody":"Pakistan inflation and the SBP policy rate remain central to the economic outlook. This narrative evidence does not create a structured numerical observation."}</script></head></html>'''
        return RawContent(candidate, html, "text/html", self.now, candidate.observed_url)

    def normalize(self, raw):
        from app.providers.evidence.extraction import extract_article

        return extract_article(raw)


def test_end_to_end_selection_indexes_once_and_keeps_exact_numbers_out_of_fact_tables(tmp_path, monkeypatch):
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


class DuplicateDawnSource(FixtureDawnSource):
    def discover_since(self, cursor, limit):
        del cursor
        items = tuple(
            Candidate(
                source_key=self.key,
                observed_url=f"https://www.dawn.com/news/{suffix}",
                external_id=f"duplicate-{suffix}",
                headline="Pakistan inflation and policy rate outlook",
                publisher="Dawn",
                discovered_at=self.now,
                published_at=self.now,
                discovery_method="rss_atom",
                topic="pakistan_macro",
            )
            for suffix in ("a", "b")
        )
        return DiscoveryBatch(items[:limit], {})


def test_exact_body_duplicate_is_not_indexed_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    with SessionLocal() as db:
        result = run_source_once(db, DuplicateDawnSource())
        statuses = sorted(db.scalars(select(DiscoveryCandidate.status)).all())
        assert result.selected == 1
        assert result.duplicates == 1
        assert statuses == ["duplicate", "selected"]
        assert db.scalar(select(func.count()).select_from(Document)) == 1


def test_relevance_uses_dynamic_instruments_aliases_and_sector_drivers():
    with SessionLocal() as db:
        instrument = Instrument(symbol="HBL", name="Habib Bank Limited", sector="Commercial Banks")
        db.add(instrument)
        db.flush()
        db.add(InstrumentAlias(instrument_id=instrument.id, provider="fixture", alias="Habib Bank"))
        db.flush()
        candidate = Candidate("dawn", "https://example.com/hbl", "Habib Bank outlook", "Dawn", FixtureDawnSource.now, "rss")
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


def test_official_psx_same_title_does_not_cluster_or_deduplicate_across_symbols():
    with SessionLocal() as db:
        config = ensure_source_config(db, "psx_announcements")[1]
        candidates = []
        parsed_items = []
        for index, symbol in enumerate(("AAA", "BBB"), start=1):
            candidate = Candidate(
                "psx_announcements",
                f"https://dps.psx.com.pk/announcement/{index}",
                "Board Meeting / Closed Period",
                "Pakistan Stock Exchange",
                FixtureDawnSource.now,
                "api",
                external_id=str(index),
                metadata={"symbol": symbol},
            )
            row, _ = persist_candidate(db, config, candidate)
            parsed = ParsedEvidence(
                canonical_url=candidate.observed_url,
                title=candidate.headline,
                body="Identical exchange template body.",
                published_at=candidate.discovered_at,
                source_key=candidate.source_key,
                body_sha256="b" * 64,
                parser_method="fixture",
                extraction_quality=1.0,
                entity_keys=(symbol,),
            )
            candidates.append(row)
            parsed_items.append(parsed)

        first_score = Score(1.0, ("official_psx_announcement",), ("AAA",), "board_meeting")
        second_score = Score(1.0, ("official_psx_announcement",), ("BBB",), "board_meeting")
        first_event = _cluster(db, candidates[0], parsed_items[0], first_score)
        db.flush()

        assert _find_duplicate(db, candidates[1], parsed_items[1]) is None
        second_event = _cluster(db, candidates[1], parsed_items[1], second_score)
        assert second_event.id != first_event.id


def test_cluster_creation_reuses_deterministic_key_idempotently():
    with SessionLocal() as db:
        config = ensure_source_config(db, "psx_announcements")[1]
        candidate = Candidate(
            "psx_announcements",
            "https://dps.psx.com.pk/announcement/idempotent",
            "Voluntary Delisting",
            "Pakistan Stock Exchange",
            FixtureDawnSource.now,
            "api",
            metadata={"symbol": "PMPK"},
        )
        row, _ = persist_candidate(db, config, candidate)
        parsed = ParsedEvidence(
            canonical_url=candidate.observed_url,
            title=candidate.headline,
            body="Official voluntary delisting announcement.",
            published_at=candidate.discovered_at,
            source_key=candidate.source_key,
            body_sha256="c" * 64,
            parser_method="fixture",
            extraction_quality=1.0,
            entity_keys=("PMPK",),
        )
        score = Score(1.0, ("official_psx_announcement",), ("PMPK",), "psx_company")

        first = _cluster(db, row, parsed, score)
        db.flush()
        second = _cluster(db, row, parsed, score)

        assert second.id == first.id
        assert first.event_type == "announcement"
        assert len(db.scalars(select(Event)).all()) == 1


def test_reused_story_cluster_merges_new_entity_links():
    with SessionLocal() as db:
        config = ensure_source_config(db, "dawn")[1]
        rows = []
        parsed_items = []
        for suffix in ("first", "second"):
            candidate = Candidate(
                "dawn",
                f"https://www.dawn.com/news/{suffix}",
                "Banks respond to policy rate outlook",
                "Dawn",
                FixtureDawnSource.now,
                "rss_atom",
                external_id=suffix,
                topic="pakistan_macro",
            )
            row, _ = persist_candidate(db, config, candidate)
            rows.append(row)
            parsed_items.append(
                ParsedEvidence(
                    canonical_url=candidate.observed_url,
                    title=candidate.headline,
                    body="Pakistan banks respond to the policy rate outlook.",
                    published_at=candidate.discovered_at,
                    source_key="dawn",
                    body_sha256=suffix * 8,
                    parser_method="fixture",
                    extraction_quality=1.0,
                )
            )

        first = _cluster(db, rows[0], parsed_items[0], Score(1.0, (), ("HBL",), "pakistan_macro"))
        db.flush()
        reused = _cluster(db, rows[1], parsed_items[1], Score(1.0, (), ("MEBL",), "pakistan_macro"))
        db.flush()
        links = set(db.scalars(select(EventEntityLink.entity_key).where(EventEntityLink.event_id == first.id)))

    assert reused.id == first.id
    assert first.event_type == "news"
    assert links == {"HBL", "MEBL"}


class ClusteredDawnSource(DuplicateDawnSource):
    def normalize(self, raw):
        suffix = raw.candidate.observed_url.rsplit("/", 1)[-1]
        body = (
            "Pakistan inflation policy rate coverage with central bank context and monetary transmission."
            if suffix == "a"
            else "Pakistan budget tax revenue outlook with fiscal accounts and government financing details."
        )
        return ParsedEvidence(
            canonical_url=raw.candidate.observed_url,
            title=raw.candidate.headline,
            body=body,
            published_at=raw.candidate.published_at,
            source_key=self.key,
            body_sha256=hashlib.sha256(body.encode()).hexdigest(),
            parser_method="fixture",
            extraction_quality=0.9,
            simhash="0000000000000000" if suffix == "a" else "ffffffffffffffff",
        )


def test_same_story_clusters_and_keeps_one_reporting_document(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    with SessionLocal() as db:
        result = run_source_once(db, ClusteredDawnSource())
        sources = db.scalars(select(EventSource)).all()
        assert result.selected == 1
        assert result.rejected == 1
        assert db.scalar(select(func.count()).select_from(Event)) == 1
        assert sorted(item.selection_status for item in sources) == ["reference", "selected"]
        assert db.scalar(select(func.count()).select_from(Document)) == 1


class IrrelevantDawnSource(FixtureDawnSource):
    def discover_since(self, cursor, limit):
        del cursor
        item = Candidate(
            self.key,
            "https://www.dawn.com/lifestyle/recipe",
            "A seasonal dessert recipe",
            "Dawn",
            self.now,
            "rss_atom",
            external_id="irrelevant-1",
        )
        return DiscoveryBatch((item,)[:limit], {})

    def fetch(self, candidate):
        raise AssertionError(f"irrelevant candidate was fetched: {candidate.observed_url}")


def test_metadata_gate_rejects_irrelevant_candidate_without_fetching():
    with SessionLocal() as db:
        result = run_source_once(db, IrrelevantDawnSource())
        candidate = db.scalar(select(DiscoveryCandidate))
        assert result.rejected == 1
        assert result.evaluated == 0
        assert candidate.status == "rejected"
        assert "no_substantive_metadata_match" in candidate.scoring_reasons_json


class BrokenDiscoverySource(FixtureDawnSource):
    def discover_since(self, cursor, limit):
        raise ValueError("fixture feed contract changed")


def test_discovery_failure_is_recorded_in_durable_source_state():
    with SessionLocal() as db:
        result = run_source_once(db, BrokenDiscoverySource())
        state = db.scalar(select(EvidenceSourceState))
        assert result.failed == 1
        assert state.consecutive_failures == 1
        assert state.last_error_class == "ValueError"
        assert "discovery" in state.diagnostics_json
