import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate, DiscoveryBatch, EvidenceSourceRegistry, RawContent
from app.models.evidence import DiscoveryCandidate, EvidenceRefreshRequest, EvidenceSourceState
from app.models.workstation import Instrument
from app.services.evidence_history_service import (
    create_historical_request,
    run_historical_discovery_slice,
)
from app.services.evidence_operations import EvidenceSpool, fetch_stage
from app.services.evidence_pipeline import ensure_source_config, persist_candidate


NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)


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


def test_presets_create_bounded_durable_progress_and_are_idempotent():
    with SessionLocal() as db:
        first = create_historical_request(db, preset_key="psx_12m")
        second = create_historical_request(db, preset_key="psx_12m")
        progress = json.loads(first.progress_json)

        assert first.id == second.id
        assert (first.date_to - first.date_from).days == 365
        assert json.loads(first.source_keys_json) == ["psx_announcements"]
        assert first.priority_class == "historical"
        assert first.max_candidates == 5000
        assert progress["unit_index"] == 0
        assert progress["total_units"] == 1


def test_psx_history_advances_one_page_and_resumes_from_postgres(monkeypatch):
    source = PagedPsxSource()
    monkeypatch.setattr(
        "app.services.evidence_history_service.build_pass1_registry",
        lambda: Registry(source),
    )
    monkeypatch.setattr(settings, "evidence_historical_batch_candidates", 3)
    with SessionLocal() as db:
        request = create_historical_request(
            db,
            preset_key="psx_12m",
            max_candidates=3,
        )
        result, outcome = run_historical_discovery_slice(db, request)
        db.refresh(request)
        progress = json.loads(request.progress_json)

        assert outcome == "slice_complete"
        assert result.discovered == 3
        assert progress["units"][0]["offset"] == 3
        assert request.status == "queued"

        result, outcome = run_historical_discovery_slice(db, request)
        assert result is None
        assert outcome == "candidate_budget_reached"
        assert db.get(EvidenceRefreshRequest, request.id).status == "processing"


def test_historical_discovery_yields_while_live_work_exists(monkeypatch):
    monkeypatch.setattr(settings, "evidence_historical_live_backlog_reserve", 1)
    monkeypatch.setattr(settings, "evidence_fetch_queue_target", 2)
    with SessionLocal() as db:
        request = create_historical_request(db, preset_key="psx_12m")
        _, config, _ = ensure_source_config(db, "dawn")
        persist_candidate(
            db,
            config,
            Candidate(
                "dawn",
                "https://www.dawn.com/news/live-pressure",
                "Pakistan policy rate update",
                "Dawn",
                NOW,
                "rss_atom",
                external_id="live-pressure",
                metadata={"priority_class": "live"},
            ),
        )
        db.commit()

        result, outcome = run_historical_discovery_slice(db, request)
        db.refresh(request)

        assert result is None
        assert outcome == "yielded_to_live"
        assert request.status == "queued"
        assert json.loads(request.progress_json)["halted_reason"] == "yielding_to_live_work"


def test_small_live_backlog_does_not_starve_history(monkeypatch):
    source = PagedPsxSource()
    monkeypatch.setattr(
        "app.services.evidence_history_service.build_pass1_registry",
        lambda: Registry(source),
    )
    monkeypatch.setattr(settings, "evidence_historical_live_backlog_reserve", 1)
    monkeypatch.setattr(settings, "evidence_fetch_queue_target", 80)
    monkeypatch.setattr(settings, "evidence_historical_batch_candidates", 1)
    with SessionLocal() as db:
        request = create_historical_request(db, preset_key="psx_12m", max_candidates=1)
        _, config, _ = ensure_source_config(db, "dawn")
        persist_candidate(
            db,
            config,
            Candidate(
                "dawn",
                "https://www.dawn.com/news/small-live-pressure",
                "Pakistan policy rate update",
                "Dawn",
                NOW,
                "rss_atom",
                external_id="small-live-pressure",
                metadata={"priority_class": "live"},
            ),
        )
        db.commit()

        result, outcome = run_historical_discovery_slice(db, request)

        assert outcome == "slice_complete"
        assert result is not None
        assert result.discovered == 1


def test_historical_request_respects_open_source_circuit(monkeypatch):
    monkeypatch.setattr(settings, "evidence_fetch_queue_target", 80)
    monkeypatch.setattr(settings, "evidence_historical_live_backlog_reserve", 1)
    with SessionLocal() as db:
        request = create_historical_request(db, preset_key="psx_12m")
        _, _, state = ensure_source_config(db, "psx_announcements")
        state.consecutive_failures = settings.evidence_circuit_failure_threshold
        state.next_poll_at = datetime.now(UTC) + timedelta(minutes=10)
        db.commit()

        result, outcome = run_historical_discovery_slice(db, request)
        db.refresh(request)

        assert result is None
        assert outcome == "source_circuit_open"
        assert request.status == "queued"
        assert (
            json.loads(request.progress_json)["halted_reason"]
            == "source_circuit_open:psx_announcements"
        )


def test_historical_fetch_stops_before_storage_budget_is_exceeded(tmp_path):
    with SessionLocal() as db:
        request = create_historical_request(db, preset_key="psx_12m")
        request.storage_budget_bytes = 10
        _, config, _ = ensure_source_config(db, "psx_announcements")
        candidate = Candidate(
            "psx_announcements",
            "https://dps.psx.com.pk/announcements?id=budget",
            "HBL financial results",
            "Pakistan Stock Exchange",
            NOW,
            "psx_announcements_post",
            external_id="budget",
            metadata={
                "priority_class": "historical",
                "request_id": request.id,
                "symbol": "HBL",
            },
        )
        row, _ = persist_candidate(db, config, candidate)
        db.commit()

        result = fetch_stage(
            db,
            OversizePsxSource(),
            row.id,
            spool=EvidenceSpool(tmp_path),
        )
        db.refresh(request)

        assert result.outcome == "historical_storage_budget_reached"
        assert db.get(DiscoveryCandidate, row.id).status == "rejected"
        assert request.status == "partial"
        assert request.fetched_count == 1
        assert request.fetched_bytes == 0


def test_budget_expansion_requires_seven_continuous_healthy_days():
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="seven continuous healthy"):
            create_historical_request(
                db,
                preset_key="news_90d",
                max_candidates=201,
            )
        end = datetime.now(UTC).date()
        with pytest.raises(ValueError, match="seven continuous healthy"):
            create_historical_request(
                db,
                preset_key="news_90d",
                date_from=end - timedelta(days=91),
                date_to=end,
            )
        _, _, state = ensure_source_config(db, "gdelt")
        state.healthy_since = datetime.now(UTC) - timedelta(days=8)
        state.consecutive_failures = 0
        db.commit()

        request = create_historical_request(
            db,
            preset_key="news_90d",
            max_candidates=201,
        )

        assert request.max_candidates == 201
        assert db.scalar(select(EvidenceSourceState)).healthy_since is not None


def test_registry_contract_still_has_no_pass4_sources():
    from app.ingestion.evidence_catalog import build_pass1_registry

    registry: EvidenceSourceRegistry = build_pass1_registry()
    assert "google_news_archive" not in registry.keys()
    assert "fed_releases" not in registry.keys()


def test_pass2_historical_row_is_upgraded_to_resumable_pass3_progress(monkeypatch):
    source = PagedPsxSource()
    monkeypatch.setattr(
        "app.services.evidence_history_service.build_pass1_registry",
        lambda: Registry(source),
    )
    monkeypatch.setattr(settings, "evidence_historical_batch_candidates", 1)
    with SessionLocal() as db:
        instrument = Instrument(symbol="LEG", name="Legacy Limited", sector="Technology")
        db.add(instrument)
        db.flush()
        request = EvidenceRefreshRequest(
            request_type="historical",
            scope_key=f"deep_instrument:{instrument.id}",
            query_text='("LEG" OR "Legacy Limited") AND Pakistan',
            source_keys_json='["gdelt"]',
            status="queued",
            priority_class="historical",
            max_candidates=1,
        )
        db.add(request)
        db.commit()

        result, outcome = run_historical_discovery_slice(db, request)
        db.refresh(request)
        progress = json.loads(request.progress_json)

        assert outcome == "slice_complete"
        assert result.discovered == 1
        assert request.preset_key == "deep_company_12m"
        assert (request.date_to - request.date_from).days == 365
        assert progress["upgraded_from_pass2"] is True
        assert progress["units"][0]["source_key"] == "psx_announcements"
