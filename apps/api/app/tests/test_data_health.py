from datetime import UTC, date, datetime, timedelta
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.models.workstation import Event, EventEntityLink, EventSource, IngestionRun, Instrument, InstrumentAlias, StandardizedFinancialFact
from app.services.company_event_service import relink_stored_news
from app.services.data_health_service import company_completeness, source_health
from app.services.ingestion_run_service import fail_ingestion_run, finish_ingestion_run, start_ingestion_run
from app.services.ingestion_service import refresh_provider, run_due_ingestion_jobs
from app.services.market_ingestion import generate_mock_market_data


def _auth(client):
    response = client.post("/auth/signup", json={"email": "health@example.com", "password": "password123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_run_accounting_supports_success_partial_and_failed():
    with SessionLocal() as db:
        success, _ = start_ingestion_run(db, job_key="test:success", run_key="1", provider="sbp")
        success = finish_ingestion_run(db, success, {"attempted": 2, "accepted": 2})
        partial, _ = start_ingestion_run(db, job_key="test:partial", run_key="1", provider="mettis")
        partial = finish_ingestion_run(db, partial, {"attempted": 3, "accepted": 2, "rejected": 1, "diagnostics": {"errors": ["one malformed row"]}})
        failed, _ = start_ingestion_run(db, job_key="test:failed", run_key="1", provider="pbs")
        failed = fail_ingestion_run(db, failed.id, RuntimeError("workbook unavailable"))

        assert success.status == "success"
        assert partial.status == "partial" and partial.rejected_count == 1
        assert partial.error_message == "one malformed row"
        assert failed.status == "failed" and failed.error_message == "workbook unavailable"


def test_rejected_rows_are_retained_by_provider_refresh(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion_service._refresh_scstrade",
        lambda db: {"attempted": 4, "accepted": 3, "updated": 0, "rejected": 1, "diagnostics": {"errors": ["MEBL row 4: invalid close"]}},
    )
    with SessionLocal() as db:
        run = refresh_provider(db, "scstrade", "partial-test")
    assert run.status == "partial"
    assert (run.attempted_count, run.accepted_count, run.rejected_count) == (4, 3, 1)
    assert "invalid close" in (run.error_message or "")


def test_one_scheduled_provider_failure_does_not_block_others(monkeypatch):
    attempted: list[str] = []

    def fake_refresh(db, provider, key):
        attempted.append(provider)
        if provider == "mettis":
            raise RuntimeError("listing unavailable")
        return SimpleNamespace(id=f"run-{provider}", status="success")

    monkeypatch.setattr(settings, "scheduled_research_enabled", True)
    monkeypatch.setattr(settings, "market_data_mode", "dps")
    monkeypatch.setattr("app.services.ingestion_service.refresh_provider", fake_refresh)
    with SessionLocal() as db:
        results = run_due_ingestion_jobs(db)

    assert attempted == ["sbp", "scstrade", "pbs", "world_bank"]
    assert all(row["status"] == "success" for row in results)


def test_freshness_derivation_is_honest_about_absence_and_age():
    today = date(2026, 8, 13)
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    with SessionLocal() as db:
        generate_mock_market_data(db, days=2, end_date=today)
        price = db.scalar(select(MarketPrice).where(MarketPrice.trade_date == today))
        price.source = "dps"
        run = IngestionRun(job_key="refresh:dps", run_key="today", provider="dps", status="success", attempted_count=1, accepted_count=1, started_at=now - timedelta(minutes=5), finished_at=now - timedelta(minutes=4))
        db.add(run)
        db.commit()
        health = source_health(db, now=now)

    by_source = {row["source"]: row for row in health["sources"]}
    assert by_source["DPS"]["status"] == "healthy"
    assert by_source["Mettis"]["status"] == "never_run"
    assert by_source["PSX Announcements"]["status"] == "never_run"


def test_yahoo_fallback_does_not_report_dps_as_healthy():
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=now.date())
        for price in db.scalars(select(MarketPrice)):
            price.source = "yahoo"
        db.add(
            IngestionRun(
                job_key="refresh:auto",
                run_key="fallback",
                provider="auto",
                status="success",
                attempted_count=1,
                accepted_count=1,
                diagnostics_json=json.dumps({"used_provider": "yahoo"}),
                started_at=now,
                finished_at=now,
            )
        )
        db.commit()

        health = source_health(db, now=now)

    dps = next(row for row in health["sources"] if row["source"] == "DPS")
    assert dps["status"] == "never_run"
    assert dps["latest_data_at"] is None


def test_company_completeness_excludes_demo_market_data_and_reports_missing_categories():
    with SessionLocal() as db:
        generate_mock_market_data(db, days=3, end_date=date(2026, 8, 13))
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        assert instrument is not None
        missing = company_completeness(db, "MEBL")
        assert missing["price"]["available"] is False
        assert missing["announcements"]["available"] is False
        assert "No observed PSX announcements" in missing["announcements"]["reason"]

        prices = list(db.scalars(select(MarketPrice).where(MarketPrice.symbol == "MEBL")))
        for price in prices:
            price.source = "dps"
        db.commit()
        observed = company_completeness(db, "MEBL")
        assert observed["price"]["available"] is True
        assert observed["price"]["observations"] == 3


def test_company_completeness_counts_normalized_announcement_and_news_events():
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=date(2026, 8, 13))
        for event_type, suffix in (("announcement", "notice"), ("news", "story")):
            event = Event(
                event_type=event_type,
                title=f"{'Meezan Bank Limited' if event_type == 'news' else 'MEBL'} {suffix}",
                occurred_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
                details_json="{}",
            )
            db.add(event)
            db.flush()
            db.add(EventEntityLink(event_id=event.id, entity_type="instrument", entity_key="MEBL", link_method="exact_alias", confidence=1))
            db.add(EventSource(event_id=event.id, source_url=f"https://example.test/{suffix}", source_name="Observed Fixture"))
        db.commit()

        completeness = company_completeness(db, "MEBL")

    assert completeness["announcements"]["available"] is True
    assert completeness["news"]["available"] is True


def test_company_completeness_counts_observed_standardized_fundamentals():
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=date(2026, 8, 13))
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        assert instrument is not None
        db.add(
            StandardizedFinancialFact(
                instrument_id=instrument.id,
                metric="revenue",
                period_type="annual",
                period_key="2025",
                period_end=date(2025, 12, 31),
                value=100,
                unit="PKR",
                currency="PKR",
                source="dps",
                source_url="https://dps.psx.com.pk/company/MEBL",
                quality_status="observed",
            )
        )
        db.commit()

        completeness = company_completeness(db, "MEBL")

    assert completeness["fundamentals"]["available"] is True
    assert completeness["fundamentals"]["fact_count"] == 1
    assert completeness["fundamentals"]["latest_period"].date() == date(2025, 12, 31)


def test_company_research_exposes_observed_standardized_fundamentals(client):
    headers = _auth(client)
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=date(2026, 8, 13))
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        assert instrument is not None
        instrument_id = instrument.id
        db.add(
            StandardizedFinancialFact(
                instrument_id=instrument.id,
                metric="revenue",
                period_type="annual",
                period_key="2025",
                period_end=date(2025, 12, 31),
                value=100,
                unit="PKR",
                currency="PKR",
                source="dps",
                source_url="https://dps.psx.com.pk/company/MEBL",
                quality_status="observed",
            )
        )
        db.commit()

    response = client.get(f"/companies/{instrument_id}/overview", headers=headers)

    assert response.status_code == 200
    fact = next(row for row in response.json()["fundamentals"] if row["taxonomy_key"] == "revenue")
    assert fact["classification"] == "standardized_secondary"
    assert fact["provenance"]["source_name"] == "DPS"


def test_company_research_exposes_linked_event_publishers(client):
    headers = _auth(client)
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=date(2026, 8, 13))
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        assert instrument is not None
        instrument_id = instrument.id
        event = Event(
            event_type="news",
            title="Meezan Bank Limited stored publisher story",
            occurred_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
            details_json="{}",
        )
        db.add(event)
        db.flush()
        db.add(EventEntityLink(event_id=event.id, entity_type="instrument", entity_key="mebl", link_method="exact_alias", confidence=1))
        db.add(EventSource(event_id=event.id, source_url="https://publisher.test/mebl", source_name="Observed Publisher"))
        db.commit()

    response = client.get(f"/companies/{instrument_id}/overview", headers=headers)

    assert response.status_code == 200
    event_row = response.json()["events"][0]
    assert event_row["event_type"] == "news"
    assert event_row["sources"] == [
        {
            "source_name": "Observed Publisher",
            "source_url": "https://publisher.test/mebl",
            "published_at": None,
            "selection_status": "legacy",
        }
    ]


def test_company_research_rejects_legacy_lowercase_word_news_links(client):
    headers = _auth(client)
    with SessionLocal() as db:
        instrument = Instrument(symbol="CASH", name="Cash Corporation", sector="Other")
        event = Event(
            event_type="news",
            title="Households face a cash squeeze",
            occurred_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
            details_json="{}",
        )
        db.add_all([instrument, event])
        db.flush()
        instrument_id = instrument.id
        db.add(EventEntityLink(event_id=event.id, entity_type="instrument", entity_key="CASH", link_method="exact_alias", confidence=1))
        db.add(EventSource(event_id=event.id, source_url="https://publisher.test/cash-squeeze", source_name="Observed Publisher"))
        db.commit()

    overview = client.get(f"/companies/{instrument_id}/overview", headers=headers)
    completeness = client.get("/ingestion/companies/CASH/completeness", headers=headers)

    assert overview.status_code == 200
    assert overview.json()["events"] == []
    assert completeness.status_code == 200
    assert completeness.json()["news"]["available"] is False


def test_stored_news_relink_replaces_false_links_with_name_alias_and_ticker_matches():
    with SessionLocal() as db:
        instruments = [
            Instrument(symbol="CASH", name="Cash Corporation", sector="Other"),
            Instrument(symbol="MEBL", name="Meezan Bank Limited", sector="Banks"),
            Instrument(symbol="KEL", name="K-Electric Limited", sector="Power"),
            Instrument(symbol="ALPHA", name="Alpha Holdings Limited", sector="Other"),
        ]
        db.add_all(instruments)
        db.flush()
        db.add(InstrumentAlias(instrument_id=instruments[3].id, provider="fixture", alias="Alpha Finance"))
        events = [
            Event(event_type="news", title="Households face a cash squeeze", occurred_at=datetime(2026, 8, 13, tzinfo=UTC), details_json='{"entity_keys":["CASH"]}'),
            Event(event_type="news", title="Meezan Bank expands its branch network", occurred_at=datetime(2026, 8, 13, tzinfo=UTC), details_json="{}"),
            Event(event_type="news", title="PSX:KEL files an operational update", occurred_at=datetime(2026, 8, 13, tzinfo=UTC), details_json="{}"),
            Event(event_type="news", title="Alpha Finance announces a new service", occurred_at=datetime(2026, 8, 13, tzinfo=UTC), details_json="{}"),
            Event(event_type="news", title="MEBL shares rise on PSX after financial results", occurred_at=datetime(2026, 8, 13, tzinfo=UTC), details_json="{}"),
        ]
        db.add_all(events)
        db.flush()
        event_ids = [event.id for event in events]
        db.add(EventEntityLink(event_id=events[0].id, entity_type="instrument", entity_key="CASH", link_method="exact_alias", confidence=1))
        for index, event in enumerate(events):
            db.add(EventSource(event_id=event.id, source_url=f"https://publisher.test/{index}", source_name="Observed Publisher"))
        db.commit()

        dry_run = relink_stored_news(db)
        assert dry_run["links_written"] == 4
        assert db.scalar(select(EventEntityLink.entity_key)) == "CASH"

        applied = relink_stored_news(db, apply=True)
        links = {
            (row.event_id, row.entity_key, row.link_method)
            for row in db.scalars(select(EventEntityLink))
        }
        rerun = relink_stored_news(db, apply=True)

    assert applied["old_links"] == 1
    assert applied["links_written"] == 4
    assert links == {
        (event_ids[1], "MEBL", "stored_company_name"),
        (event_ids[2], "KEL", "stored_ticker"),
        (event_ids[3], "ALPHA", "stored_alias"),
        (event_ids[4], "MEBL", "stored_ticker_context"),
    }
    assert rerun["old_links"] == 4
    assert rerun["links_written"] == 4


def test_research_events_can_filter_stored_news(client):
    with SessionLocal() as db:
        db.add_all(
            [
                Event(event_type="announcement", title="Issuer notice", occurred_at=datetime(2026, 8, 13, tzinfo=UTC), details_json="{}"),
                Event(event_type="news", title="Stored publisher story", occurred_at=datetime(2026, 8, 13, tzinfo=UTC), details_json="{}"),
            ]
        )
        db.flush()
        news_event = db.scalar(select(Event).where(Event.event_type == "news"))
        db.add(EventSource(event_id=news_event.id, source_url="https://publisher.test/story", source_name="Observed Publisher"))
        db.commit()

    response = client.get("/research/events?event_type=news&limit=30")

    assert response.status_code == 200
    assert [row["event_type"] for row in response.json()] == ["news"]
    assert response.json()[0]["sources"][0]["source_name"] == "Observed Publisher"


def test_health_and_completeness_apis_require_auth_and_return_missing_states(client):
    assert client.get("/ingestion/health").status_code == 401
    headers = _auth(client)
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=date(2026, 8, 13))

    health = client.get("/ingestion/health", headers=headers)
    assert health.status_code == 200
    assert any(row["source"] == "PSX Announcements" and row["status"] == "never_run" for row in health.json()["sources"])

    completeness = client.get("/ingestion/companies/MEBL/completeness", headers=headers)
    assert completeness.status_code == 200
    body = completeness.json()
    assert body["price"]["available"] is False
    assert body["announcements"]["available"] is False
