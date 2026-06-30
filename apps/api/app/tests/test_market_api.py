from datetime import date

from app.db.session import SessionLocal
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
