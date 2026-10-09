from decimal import Decimal
import json
from pathlib import Path

from datetime import date

import httpx

from app.db.session import SessionLocal
from app.services.market_providers import (
    DpsMarketDataProvider,
    MockMarketDataProvider,
    get_market_data_provider,
    LatestPriceRow,
)
import pytest










DPS_FIXTURES = Path(__file__).parent / "fixtures" / "providers" / "dps"


def test_dps_symbol_contract_fixture():
    payload = json.loads((DPS_FIXTURES / "symbols.sample.json").read_text())
    rows = DpsMarketDataProvider.parse_symbols(payload)
    assert [row["symbol"] for row in rows] == ["MEBL", "OGDC", "SYS"]
    assert rows[0]["sector"] == "COMMERCIAL BANKS"
    assert rows[0]["is_debt"] is False


def test_dps_session_uses_public_page_request_header(monkeypatch):
    real_client = httpx.Client
    def respond(request):
        if request.url.path == "/historical":
            return httpx.Response(200, text='window.__ps = {"_k":"fixture-public-session"};')
        assert request.headers["X-Req-Id"] == "fixture-public-session"
        assert request.headers["X-Requested-With"] == "XMLHttpRequest"
        return httpx.Response(200, json=json.loads((DPS_FIXTURES / "symbols.sample.json").read_text()))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    assert DpsMarketDataProvider().health_check()["symbols"] == 3


def test_dps_datewise_history_contract_and_debt_filter():
    html = (DPS_FIXTURES / "historical_date.sample.html").read_text()
    rows = DpsMarketDataProvider.parse_datewise_history(html, date(2026, 8, 7))
    assert [row.symbol for row in rows] == ["786", "MEBL"]
    assert rows[1].previous_close == Decimal("587.92")
    assert rows[1].high == Decimal("592.97")
    assert rows[1].volume == 1_367_419


def test_dps_symbol_history_is_normalized_oldest_first():
    html = (DPS_FIXTURES / "historical_mebl.sample.html").read_text()
    rows = DpsMarketDataProvider.parse_symbol_history(html, "MEBL")
    assert [row.trade_date for row in rows] == [date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10)]
    assert rows[0].previous_close is None
    assert rows[1].previous_close == Decimal("587.93")
    assert rows[2].volume == 48_388


def test_dps_history_uses_prior_session_before_requested_window(monkeypatch):
    history_html = (DPS_FIXTURES / "historical_mebl.sample.html").read_text()
    empty_html = '<table id="historicalTable"><tr><th>DATE</th><th>OPEN</th><th>HIGH</th><th>LOW</th><th>CLOSE</th><th>VOLUME</th></tr></table>'

    class FixtureClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, path, data):
            body = history_html if data["month"] == "8" else empty_html
            request = httpx.Request("POST", f"https://dps.psx.com.pk{path}", data=data)
            return httpx.Response(200, text=body, headers={"content-type": "text/html"}, request=request)

    provider = DpsMarketDataProvider()
    monkeypatch.setattr(provider, "_client", lambda: FixtureClient())

    rows = provider.fetch_symbol_history("MEBL", date(2026, 8, 7), date(2026, 8, 10))

    assert [row.trade_date for row in rows] == [date(2026, 8, 7), date(2026, 8, 10)]
    assert rows[0].previous_close == Decimal("587.93")


@pytest.mark.usefixtures("database")
def test_dps_refresh_reports_missing_ordinary_symbols_as_partial(tmp_path, monkeypatch):
    from app.core.config import settings

    provider = DpsMarketDataProvider()

    def fixture_prices():
        provider.observed_universe = [
            {"symbol": "AAA", "name": "Alpha", "sector": "Test", "is_debt": False, "is_etf": False, "is_gem": False},
            {"symbol": "BBB", "name": "Beta", "sector": "Test", "is_debt": False, "is_etf": False, "is_gem": False},
        ]
        return [
            LatestPriceRow(
                symbol="AAA",
                name="Alpha",
                sector="Test",
                trade_date=date(2026, 8, 10),
                open=Decimal("99"),
                high=Decimal("102"),
                low=Decimal("98"),
                close=Decimal("101"),
                previous_close=Decimal("100"),
                volume=1000,
                source_url="https://dps.psx.com.pk/historical?date=2026-08-10",
            )
        ]

    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(provider, "fetch_latest_prices", fixture_prices)
    with SessionLocal() as db:
        result = provider.refresh_latest(db)

    assert result["coverage_status"] == "partial"
    assert (result["attempted"], result["accepted"], result["rejected"]) == (2, 1, 1)
    assert result["missing_symbols"] == ["BBB"]


def test_dps_parser_rejects_contract_header_drift():
    html = (DPS_FIXTURES / "historical_date.sample.html").read_text().replace("LDCP", "PREVIOUS")
    import pytest
    with pytest.raises(ValueError, match="headers changed"):
        DpsMarketDataProvider.parse_datewise_history(html, date(2026, 8, 7))


def test_dps_daily_manifest_uses_observed_links():
    html = (DPS_FIXTURES / "daily_manifest.sample.html").read_text()
    links = DpsMarketDataProvider.parse_daily_manifest(html)
    assert links[2] == {"label": "ZIP", "href": "/download/symbol_price/2026-08-07.zip", "format": "zip"}










def test_market_provider_factory_returns_supported_provider_types():
    assert isinstance(get_market_data_provider("mock"), MockMarketDataProvider)
    assert isinstance(get_market_data_provider("dps"), DpsMarketDataProvider)
    with pytest.raises(KeyError):
        get_market_data_provider("yahoo")
