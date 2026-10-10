"""Offline company data health contracts and fixtures."""

from datetime import UTC, date, datetime
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.models.workstation import (
    Event,
    EventEntityLink,
    EventSource,
    Instrument,
    InstrumentAlias,
    StandardizedFinancialFact,
)
from app.services.company_event_service import relink_stored_news
from app.services.event_intelligence_service import normalize_raw_event
from app.services.data_health_service import company_completeness
from app.services.market_ingestion import generate_mock_market_data
from app.tests.support.ingestion import _auth
import pytest

pytestmark = pytest.mark.usefixtures("database")


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
            db.add(
                EventEntityLink(
                    event_id=event.id,
                    entity_type="instrument",
                    entity_key="MEBL",
                    link_method="exact_alias",
                    confidence=1,
                )
            )
            db.add(
                EventSource(
                    event_id=event.id,
                    source_url=f"https://example.test/{suffix}",
                    source_name="Observed Fixture",
                )
            )
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


def test_company_research_withholds_unverified_standardized_fundamentals(client):
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
    # Secondary DPS rows lack a verified fiscal period/basis, so they fail closed: they
    # are never presented as exact company fundamentals (the observation stays in SQL).
    assert not any(row["taxonomy_key"] == "revenue" for row in response.json()["fundamentals"])


def test_company_research_exposes_normalized_event_publishers(client):
    headers = _auth(client)
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=date(2026, 8, 13))
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        assert instrument is not None
        instrument_id = instrument.id
        event = Event(
            event_type="news",
            title="MEBL declares 80 percent interim cash dividend",
            occurred_at=datetime(2026, 8, 13, 10, tzinfo=UTC),
            details_json="{}",
        )
        db.add(event)
        db.flush()
        db.add(
            EventEntityLink(
                event_id=event.id,
                entity_type="instrument",
                entity_key="mebl",
                link_method="exact_alias",
                confidence=1,
            )
        )
        from app.services.rag_service import create_document_from_pages, ParsedPage

        document = create_document_from_pages(
            db,
            [ParsedPage(1, event.title + " Meezan Bank Limited.")],
            title=event.title,
            document_type="news",
            symbol="MEBL",
            source_name="Observed Publisher",
            source_url="https://publisher.test/mebl",
            published_date=date(2026, 8, 13),
            commit=False,
        )
        db.add(
            EventSource(
                event_id=event.id,
                document_id=document.id,
                source_url="https://publisher.test/mebl",
                source_name="Observed Publisher",
            )
        )
        db.commit()
        normalize_raw_event(db, event.id)

    response = client.get(f"/companies/{instrument_id}/overview", headers=headers)

    assert response.status_code == 200
    event_row = response.json()["events"][0]
    assert event_row["event_type"] == "dividend"
    assert event_row["sources"] == [
        {
            "source_name": "Observed Publisher",
            "source_url": "https://publisher.test/mebl",
            "published_at": None,
            "selection_status": "normalized",
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
        db.add(
            EventEntityLink(
                event_id=event.id,
                entity_type="instrument",
                entity_key="CASH",
                link_method="exact_alias",
                confidence=1,
            )
        )
        db.add(
            EventSource(
                event_id=event.id,
                source_url="https://publisher.test/cash-squeeze",
                source_name="Observed Publisher",
            )
        )
        db.commit()

    overview = client.get(f"/companies/{instrument_id}/overview", headers=headers)
    completeness = client.get("/ingestion/companies/CASH/completeness", headers=headers)

    assert overview.status_code == 200, overview.text
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
        db.add(
            InstrumentAlias(
                instrument_id=instruments[3].id, provider="fixture", alias="Alpha Finance"
            )
        )
        events = [
            Event(
                event_type="news",
                title="Households face a cash squeeze",
                occurred_at=datetime(2026, 8, 13, tzinfo=UTC),
                details_json='{"entity_keys":["CASH"]}',
            ),
            Event(
                event_type="news",
                title="Meezan Bank expands its branch network",
                occurred_at=datetime(2026, 8, 13, tzinfo=UTC),
                details_json="{}",
            ),
            Event(
                event_type="news",
                title="PSX:KEL files an operational update",
                occurred_at=datetime(2026, 8, 13, tzinfo=UTC),
                details_json="{}",
            ),
            Event(
                event_type="news",
                title="Alpha Finance announces a new service",
                occurred_at=datetime(2026, 8, 13, tzinfo=UTC),
                details_json="{}",
            ),
            Event(
                event_type="news",
                title="MEBL shares rise on PSX after financial results",
                occurred_at=datetime(2026, 8, 13, tzinfo=UTC),
                details_json="{}",
            ),
        ]
        db.add_all(events)
        db.flush()
        event_ids = [event.id for event in events]
        db.add(
            EventEntityLink(
                event_id=events[0].id,
                entity_type="instrument",
                entity_key="CASH",
                link_method="exact_alias",
                confidence=1,
            )
        )
        for index, event in enumerate(events):
            db.add(
                EventSource(
                    event_id=event.id,
                    source_url=f"https://publisher.test/{index}",
                    source_name="Observed Publisher",
                )
            )
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
                Event(
                    event_type="announcement",
                    title="Issuer notice",
                    occurred_at=datetime(2026, 8, 13, tzinfo=UTC),
                    details_json="{}",
                ),
                Event(
                    event_type="news",
                    title="Stored publisher story",
                    occurred_at=datetime(2026, 8, 13, tzinfo=UTC),
                    details_json="{}",
                ),
            ]
        )
        db.flush()
        news_event = db.scalar(select(Event).where(Event.event_type == "news"))
        db.add(
            EventSource(
                event_id=news_event.id,
                source_url="https://publisher.test/story",
                source_name="Observed Publisher",
            )
        )
        db.commit()

    response = client.get("/research/events?event_type=news&limit=30")

    assert response.status_code == 200
    assert [row["event_type"] for row in response.json()] == ["news"]
    assert response.json()[0]["sources"][0]["source_name"] == "Observed Publisher"
