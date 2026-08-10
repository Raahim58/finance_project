from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.market import MarketIngestionRun, MarketPrice
from app.services.market_service import serialize_price
from app.services.market_ingestion import generate_mock_market_data


def _seed_market_data():
    with SessionLocal() as db:
        generate_mock_market_data(db, days=8, end_date=date(2026, 6, 30))


def test_market_overview_and_rankings(client):
    _seed_market_data()

    overview = client.get("/market/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["snapshot"]["snapshot_date"] == "2026-06-30"
    assert len(body["top_gainers"]) == 5
    assert len(body["top_losers"]) == 5
    assert len(body["top_volume"]) == 5
    assert body["sectors"]

    gainers = client.get("/market/top-gainers?limit=3")
    assert gainers.status_code == 200
    assert len(gainers.json()) == 3

    sectors = client.get("/market/sectors")
    assert sectors.status_code == 200
    assert any(row["sector"] == "Banking" for row in sectors.json())

    freshness = client.get("/market/freshness")
    assert freshness.status_code == 200
    freshness_body = freshness.json()
    assert freshness_body["latest_source"] == "mock"
    assert freshness_body["latest_used_provider"] == "mock"
    assert freshness_body["market_data_mode"] == "mock"
    assert freshness_body["stale_warning"]
    assert freshness_body["backup_warning"] is None


def test_company_detail_history_and_search(client):
    _seed_market_data()

    search = client.get("/market/companies?q=meb")
    assert search.status_code == 200
    assert search.json()[0]["symbol"] == "MEBL"

    detail = client.get("/market/company/MEBL")
    assert detail.status_code == 200
    assert detail.json()["company"]["name"] == "Meezan Bank Limited"
    assert detail.json()["latest_price"]["trade_date"] == "2026-06-30"

    history = client.get("/market/company/MEBL/history?limit=4")
    assert history.status_code == 200
    assert len(history.json()) == 4
    assert history.json()[-1]["trade_date"] == "2026-06-30"


def test_missing_market_date_returns_404(client):
    _seed_market_data()

    response = client.get("/market/snapshot?date=2025-01-01")
    assert response.status_code == 404


def test_market_freshness_shows_provider_and_backup_warning(client):
    with SessionLocal() as db:
        db.add(
            MarketIngestionRun(
                mode="auto",
                attempted_provider="auto",
                used_provider="yahoo",
                status="success",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                latest_trade_date=date(2026, 6, 30),
                records_written=12,
                message="psxdata refresh failed; yahoo fallback succeeded.",
            )
        )
        db.commit()

    response = client.get("/market/freshness")

    assert response.status_code == 200
    body = response.json()
    assert body["latest_source"] == "yahoo"
    assert body["latest_attempted_provider"] == "auto"
    assert body["latest_used_provider"] == "yahoo"
    assert body["backup_warning"]


def test_serialize_price_handles_nan_market_cap():
    with SessionLocal() as db:
        generate_mock_market_data(db, days=1, end_date=date(2026, 6, 30))
        price = db.query(MarketPrice).first()
        assert price is not None
        price.market_cap = Decimal("NaN")
        db.commit()
        db.refresh(price)

        serialized = serialize_price(price)

    assert serialized.market_cap is None


def test_market_overview_returns_200_even_with_nan_in_db(client):
    _seed_market_data()

    with SessionLocal() as db:
        price = db.query(MarketPrice).first()
        assert price is not None
        db.execute(text("UPDATE market_prices SET market_cap = 'NaN' WHERE id = :id"), {"id": price.id})
        db.commit()

    response = client.get("/market/overview")

    assert response.status_code == 200
    assert "NaN" not in response.text
    assert "Infinity" not in response.text
    assert "-Infinity" not in response.text
