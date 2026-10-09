from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.market import MarketIngestionRun
from app.models.pipeline import SourceTarget
from app.models.workstation import Instrument, MarketObservation, SourceArtifact, FinancialFact
from app.services.canonical_market_service import canonical_prices_for_date
from app.services.financial_evidence_eligibility import public_primary_financials
from app.services.market_ingestion import persist_market_data
from app.services.market_providers import LatestPriceRow
from app.services.market_service import get_market_freshness, get_latest_market_date
from app.services.market_session import resolve_session
import pytest


def daily(db, day, count=10):
    persist_market_data(db, source="dps", latest_prices=[LatestPriceRow(
        symbol=f"T{i}", name=f"Company {i}", sector="Test", trade_date=day,
        open=Decimal("100"), high=Decimal("103"), low=Decimal("99"), close=Decimal("102"),
        previous_close=Decimal("100"), volume=100, source_url="https://dps.psx.com.pk/historical",
    ) for i in range(count)])


def quotes(db, day, count):
    artifact = db.scalar(select(SourceArtifact))
    for i in range(count):
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == f"T{i}"))
        db.add(MarketObservation(instrument_id=instrument.id, artifact_id=artifact.id,
            frequency="intraday", effective_at=datetime.combine(day, datetime.min.time()),
            is_selected=True, values_json=json.dumps({"trade_date": str(day),
                "open": "100", "high": "104", "low": "99", "close": "103", "previous_close": "100", "volume": 200})))
    db.flush()


def test_two_newer_canary_quotes_do_not_replace_broad_daily_session(monkeypatch, client):
    monkeypatch.setattr(settings, "market_data_mode", "auto")
    with SessionLocal() as db:
        daily(db, date(2026, 10, 2))
        quotes(db, date(2026, 10, 7), 2)
        db.commit()
        session = resolve_session(db)
        assert (session.trade_date, session.basis, session.securities) == (date(2026, 10, 2), "daily", 10)
        assert (session.latest_quote_date, session.latest_quote_count) == (date(2026, 10, 7), 2)
    response = client.get("/market/overview").json()
    assert response["trade_date"] == "2026-10-02"
    assert len(response["top_volume"]) == 5 and response["sectors"]
    assert {r["trade_date"] for r in response["top_volume"]} == {"2026-10-02"}


def test_broad_intraday_session_is_eligible_and_sectors_match(monkeypatch, client):
    monkeypatch.setattr(settings, "market_data_mode", "auto")
    with SessionLocal() as db:
        daily(db, date(2026, 10, 2))
        quotes(db, date(2026, 10, 7), 9)
        db.commit()
        assert get_latest_market_date(db) == date(2026, 10, 7)
        prices = canonical_prices_for_date(db, date(2026, 10, 7), include_intraday=True)
        assert len(prices) == 9 and all(r.close == 103 for r in prices)
    body = client.get("/market/overview").json()
    assert body["price_basis"] == "intraday"
    assert body["priced_securities"] == 9
    assert body["sectors"][0]["trade_date"] == "2026-10-07"
    assert body["sectors"][0]["advancers"] == 9


@pytest.mark.usefixtures("database")
def test_tiny_new_daily_batch_does_not_hide_previous_coverage(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "auto")
    with SessionLocal() as db:
        daily(db, date(2026, 10, 2))
        daily(db, date(2026, 10, 7), 1)
        assert get_latest_market_date(db) == date(2026, 10, 2)


@pytest.mark.usefixtures("database")
def test_full_official_snapshot_is_available_early_in_session(monkeypatch):
    from app.models.workstation import DataSource
    monkeypatch.setattr(settings, "market_data_mode", "auto")
    with SessionLocal() as db:
        daily(db, date(2026, 10, 2))
        quotes(db, date(2026, 10, 7), 2)
        artifact = db.scalar(select(SourceArtifact))
        db.get(DataSource, artifact.data_source_id).name = "PSX DPS market watch"
        artifact.parser_version = "dps-market-watch-v1"
        artifact.response_metadata_json = json.dumps({"quote_scope": "symbol_subset"})
        db.flush()
        assert resolve_session(db).trade_date == date(2026, 10, 2)
        artifact.response_metadata_json = json.dumps({"quote_scope": "all_regular_equities"})
        db.flush()
        assert resolve_session(db).trade_date == date(2026, 10, 7)
        assert resolve_session(db).securities == 2  # No claim of complete-universe coverage.


@pytest.mark.usefixtures("database")
def test_new_daily_close_wins_over_older_intraday_snapshot(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "auto")
    with SessionLocal() as db:
        daily(db, date(2026, 10, 7))
        quotes(db, date(2026, 10, 7), 9)
        observations = db.scalars(select(MarketObservation).where(MarketObservation.frequency == "intraday")).all()
        old = db.get(SourceArtifact, observations[0].artifact_id)
        older = SourceArtifact(data_source_id=old.data_source_id, source_url=old.source_url,
            sha256="older", request_fingerprint="older", parser_version=old.parser_version,
            retrieved_at=old.retrieved_at - timedelta(hours=5))
        db.add(older); db.flush()
        for row in observations: row.artifact_id = older.id
        db.flush()
        assert resolve_session(db).basis == "daily"


def test_untraded_published_quote_preserves_zero_ohlc():
    from app.services.pipeline.prices import parse_market_watch
    html = """<table id='regular'><thead><tr><th>SYMBOL</th><th>LDCP</th><th>CURRENT</th><th>OPEN</th><th>HIGH</th><th>LOW</th><th>VOLUME</th></tr></thead>
    <tbody><tr><td>TEST</td><td>100</td><td>100</td><td>0</td><td>0</td><td>0</td><td>0</td></tr></tbody></table>"""
    rows = parse_market_watch(html)
    assert rows[0]["open"] == "0" and rows[0]["close"] == "100"


@pytest.mark.usefixtures("database")
def test_canonical_freshness_does_not_use_old_legacy_ingestion_run(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "auto")
    day = (datetime.now(UTC) - timedelta(days=7)).date()
    with SessionLocal() as db:
        daily(db, day)
        db.add(MarketIngestionRun(mode="dps", attempted_provider="dps", used_provider="dps", status="success",
                                latest_trade_date=date(2020, 1, 1)))
        db.commit()
        fresh = get_market_freshness(db)
        assert fresh.latest_trade_date == day and fresh.priced_securities == 10
        assert fresh.latest_source == "PSX DPS"
        # Re-fetching a historical artifact today cannot make its trade date current.
        assert fresh.is_stale and fresh.trade_date_status == "stale"


@pytest.mark.usefixtures("database")
def test_daily_lane_uses_pipeline_scheduler_and_numeric_queue(monkeypatch):
    from app.jobs.pipeline_tasks import QUEUES, perform, DeferredStage
    from app.jobs.pipeline_scheduler import schedule_sources
    from app.models.workstation import DataSource
    from app.models.pipeline import IngestionStageRun
    from app.services.pipeline.scheduling import scheduled_bucket
    import pytest
    now = datetime(2026, 10, 7, 20, tzinfo=UTC)
    with SessionLocal() as db:
        source = DataSource(name="Official targets", source_type="market", enabled=True)
        db.add(source); db.flush()
        target = SourceTarget(data_source_id=source.id, scope_key="market_daily", adapter_key="market_daily",
                              schedule="market_daily", enabled=True)
        db.add(target); db.commit()
        assert scheduled_bucket("market_daily", now, db) == "2026-10-07"
        assert schedule_sources(db, now) == 1
        assert schedule_sources(db, now) == 0
        run = db.scalar(select(IngestionStageRun))
        assert run.stage == "market_daily" and QUEUES[run.stage] == "pipeline_numeric"
        monkeypatch.setattr("app.jobs.market_daily.run_once", lambda: [{"status": "failed"}])
        with pytest.raises(DeferredStage): perform(db, run)


@pytest.mark.usefixtures("database")
def test_misclassified_primary_financial_labels_are_excluded_not_deleted():
    with SessionLocal() as db:
        instrument = Instrument(symbol="FFC", name="Fauji Fertilizer", sector="Fertilizer")
        db.add(instrument); db.flush()
        for key, label, value in [("revenue", "SALES TAX & EXCISE DUTY", -9715998),
                                  ("cash", "CASH & CASH EQUIVALENTS DIVIDEND RECEIPTS", 22400000),
                                  ("liabilities", "TOTAL LIABILITIES", -10),
                                  ("assets", "TOTAL ASSETS", 100)]:
            db.add(FinancialFact(instrument_id=instrument.id, taxonomy_key=key, source_label=label,
                period_type="instant", period_end=date(2026, 6, 30), value=value, unit="PKR"))
        db.flush()
        eligible = db.scalars(select(FinancialFact).where(public_primary_financials())).all()
        assert [r.taxonomy_key for r in eligible] == ["assets"]
        assert len(db.scalars(select(FinancialFact)).all()) == 4
