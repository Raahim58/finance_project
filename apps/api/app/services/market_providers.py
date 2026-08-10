from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import logging
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.market_numbers import safe_decimal, safe_int

logger = logging.getLogger(__name__)


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _dps_decimal(value: Any) -> Decimal | None:
    return safe_decimal(str(value).replace(",", "").replace("%", "").strip())


def _dps_int(value: Any) -> int | None:
    parsed = _dps_decimal(value)
    return int(parsed) if parsed is not None else None


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value))


def _coerce_rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, tuple):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "results", "quotes", "stocks"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
        return [payload]
    if hasattr(payload, "to_dict"):
        maybe_rows = payload.to_dict(orient="records")
        if isinstance(maybe_rows, list):
            return [row for row in maybe_rows if isinstance(row, dict)]
    return []


@dataclass(slots=True)
class LatestPriceRow:
    symbol: str
    trade_date: date
    close: Decimal | None
    previous_close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    volume: int | None
    name: str | None = None
    sector: str | None = None
    source_url: str | None = None
    market_cap: Decimal | None = None


@dataclass(slots=True)
class SymbolHistoryRow:
    symbol: str
    trade_date: date
    close: Decimal | None
    previous_close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    volume: int | None
    source_url: str | None = None
    market_cap: Decimal | None = None


@dataclass(slots=True)
class SectorStatRow:
    sector: str
    trade_date: date
    total_volume: int
    total_value: Decimal
    average_change_percent: Decimal
    advancers: int
    decliners: int
    unchanged: int


class MarketDataProvider(ABC):
    mode: str
    source: str

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def fetch_latest_prices(self, symbols: list[str] | None = None) -> list[LatestPriceRow]:
        raise NotImplementedError

    @abstractmethod
    def fetch_symbol_history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SymbolHistoryRow]:
        raise NotImplementedError

    @abstractmethod
    def fetch_sector_stats(self) -> list[SectorStatRow]:
        raise NotImplementedError

    def refresh_latest(self, db: Session) -> dict[str, Any]:
        from app.services.market_ingestion import persist_market_data

        latest_prices = self.fetch_latest_prices()
        if not latest_prices:
            raise RuntimeError(f"{self.source} returned no usable market price rows")
        result = persist_market_data(db, latest_prices=latest_prices, source=self.source)
        result["attempted_provider"] = self.source
        result["used_provider"] = self.source
        result["message"] = f"Refreshed market data via {self.source}."
        return result


class MockMarketDataProvider(MarketDataProvider):
    mode = "mock"
    source = "mock"

    def health_check(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.source, "detail": "Mock generator available"}

    def fetch_latest_prices(self, symbols: list[str] | None = None) -> list[LatestPriceRow]:
        raise NotImplementedError("Mock mode uses the deterministic local generator, not a fetch adapter.")

    def fetch_symbol_history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SymbolHistoryRow]:
        raise NotImplementedError("Mock history is generated through the local market seeding flow.")

    def fetch_sector_stats(self) -> list[SectorStatRow]:
        return []

    def refresh_latest(self, db: Session) -> dict[str, Any]:
        from app.services.market_ingestion import generate_mock_market_data

        result = generate_mock_market_data(db, days=365, end_date=date.today())
        result["attempted_provider"] = self.source
        result["used_provider"] = self.source
        result["message"] = "Refreshed market data via mock generator."
        result["latest_trade_date"] = date.today()
        return result


class DpsMarketDataProvider(MarketDataProvider):
    mode = "dps"
    source = "dps"
    base_url = "https://dps.psx.com.pk"
    parser_version = "dps-html-v1"

    def __init__(self) -> None:
        self.captured_responses: list[dict[str, Any]] = []

    def _capture(self, response: httpx.Response, effective_date: date | None = None) -> None:
        self.captured_responses.append({
            "url": str(response.url), "content": response.content,
            "content_type": response.headers.get("content-type"), "effective_date": effective_date,
        })

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate ingestion)",
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            },
        )

    @staticmethod
    def parse_symbols(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise ValueError("DPS symbols response must be a JSON list")
        rows = []
        for item in payload:
            if not isinstance(item, dict) or not _normalize_symbol(item.get("symbol")):
                continue
            rows.append(
                {
                    "symbol": _normalize_symbol(item["symbol"]),
                    "name": str(item.get("name") or item["symbol"]).strip(),
                    "sector": str(item.get("sectorName") or "Unknown").strip(),
                    "is_etf": bool(item.get("isETF")),
                    "is_debt": bool(item.get("isDebt")),
                    "is_gem": bool(item.get("isGEM")),
                }
            )
        return rows

    @staticmethod
    def parse_datewise_history(html: str, trade_date: date) -> list[LatestPriceRow]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="historicalTable")
        if table is None:
            raise ValueError("DPS date-wise history response did not contain #historicalTable")
        headers = [cell.get_text(" ", strip=True).upper() for cell in table.find_all("th")]
        expected = ["SYMBOL", "LDCP", "OPEN", "HIGH", "LOW", "CLOSE", "CHANGE", "CHANGE (%)", "VOLUME"]
        if headers != expected:
            raise ValueError(f"DPS date-wise history headers changed: {headers}")
        rows: list[LatestPriceRow] = []
        for tr in table.find_all("tr")[1:]:
            if tr.get("data-type") == "debt":
                continue
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all("td")]
            if len(cells) != len(expected):
                continue
            symbol = _normalize_symbol(cells[0])
            values = [_dps_decimal(value) for value in cells[1:8]]
            volume = _dps_int(cells[8])
            if not symbol or any(value is None for value in values[:5]) or volume is None:
                continue
            previous_close, open_price, high, low, close = values[:5]
            if min(previous_close, open_price, high, low, close) <= 0 or high < max(open_price, close) or low > min(open_price, close) or volume < 0:
                logger.warning("Quarantined invalid DPS row for %s on %s", symbol, trade_date)
                continue
            rows.append(
                LatestPriceRow(
                    symbol=symbol,
                    trade_date=trade_date,
                    close=close,
                    previous_close=previous_close,
                    open=open_price,
                    high=high,
                    low=low,
                    volume=volume,
                    source_url=f"https://dps.psx.com.pk/historical?date={trade_date.isoformat()}",
                )
            )
        return rows

    @staticmethod
    def parse_symbol_history(html: str, symbol: str) -> list[SymbolHistoryRow]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="historicalTable")
        if table is None:
            raise ValueError("DPS symbol history response did not contain #historicalTable")
        headers = [cell.get_text(" ", strip=True).upper() for cell in table.find_all("th")]
        if headers != ["DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]:
            raise ValueError(f"DPS symbol history headers changed: {headers}")
        parsed: list[tuple[date, Decimal, Decimal, Decimal, Decimal, int]] = []
        for tr in table.find_all("tr")[1:]:
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all("td")]
            if len(cells) != 6:
                continue
            try:
                day = datetime.strptime(cells[0], "%b %d, %Y").date()
            except ValueError:
                continue
            numbers = [_dps_decimal(cell) for cell in cells[1:5]]
            volume = _dps_int(cells[5])
            if any(value is None for value in numbers) or volume is None:
                continue
            open_price, high, low, close = numbers
            if min(open_price, high, low, close) <= 0 or high < max(open_price, close) or low > min(open_price, close) or volume < 0:
                continue
            parsed.append((day, open_price, high, low, close, volume))
        parsed.sort(key=lambda item: item[0])
        result: list[SymbolHistoryRow] = []
        previous_close: Decimal | None = None
        for day, open_price, high, low, close, volume in parsed:
            result.append(SymbolHistoryRow(symbol=_normalize_symbol(symbol), trade_date=day, close=close, previous_close=previous_close or close, open=open_price, high=high, low=low, volume=volume, source_url=f"https://dps.psx.com.pk/historical?symbol={_normalize_symbol(symbol)}"))
            previous_close = close
        return result

    @staticmethod
    def parse_daily_manifest(html: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        rows = []
        for link in soup.find_all("a", href=True):
            href = str(link["href"])
            if not href.startswith("/download/"):
                continue
            rows.append({"label": link.get_text(" ", strip=True), "href": href, "format": next(iter(link.get("class", [])), "").lower()})
        return rows

    def health_check(self) -> dict[str, Any]:
        try:
            with self._client() as client:
                response = client.get("/symbols")
                response.raise_for_status()
                count = len(self.parse_symbols(response.json()))
            return {"ok": count > 0, "provider": self.source, "symbols": count, "parser_version": self.parser_version}
        except Exception as exc:
            return {"ok": False, "provider": self.source, "detail": str(exc), "parser_version": self.parser_version}

    def fetch_latest_prices(self, symbols: list[str] | None = None) -> list[LatestPriceRow]:
        now = datetime.now(ZoneInfo("Asia/Karachi"))
        cursor = now.date() if now.hour >= 18 else now.date().fromordinal(now.date().toordinal() - 1)
        with self._client() as client:
            universe_response = client.get("/symbols")
            universe_response.raise_for_status()
            self._capture(universe_response)
            metadata = {row["symbol"]: row for row in self.parse_symbols(universe_response.json())}
            rows: list[LatestPriceRow] = []
            for _ in range(10):
                if cursor.weekday() < 5:
                    response = client.post("/historical", data={"date": cursor.isoformat()})
                    response.raise_for_status()
                    self._capture(response, cursor)
                    rows = self.parse_datewise_history(response.text, cursor)
                    if rows:
                        break
                cursor = cursor.fromordinal(cursor.toordinal() - 1)
        selected = {_normalize_symbol(value) for value in symbols} if symbols else None
        result = []
        for row in rows:
            if selected is not None and row.symbol not in selected:
                continue
            details = metadata.get(row.symbol, {})
            row.name = details.get("name")
            row.sector = details.get("sector")
            result.append(row)
        return result

    def refresh_latest(self, db: Session) -> dict[str, Any]:
        from app.ingestion.artifact_store import LocalArtifactStore
        from app.models.workstation import DataSource, SourceArtifact
        from app.services.market_ingestion import persist_market_data
        from sqlalchemy import select
        from hashlib import sha256
        import json

        self.captured_responses = []
        latest_prices = self.fetch_latest_prices()
        if not latest_prices:
            raise RuntimeError("DPS returned no usable market price rows")
        result = persist_market_data(db, latest_prices=latest_prices, source=self.source)
        data_source = db.scalar(select(DataSource).where(DataSource.name == "PSX DPS"))
        if data_source is None:
            data_source = DataSource(name="PSX DPS", source_type="market", base_url=self.base_url, priority=10, freshness_sla_minutes=1440, enabled=True, use_notes="Personal, non-commercial low-rate retrieval; redistribution prohibited.")
            db.add(data_source); db.flush()
        store = LocalArtifactStore(settings.source_artifact_root)
        artifact_count = 0
        for captured in self.captured_responses:
            digest = sha256(captured["content"]).hexdigest()
            if db.scalar(select(SourceArtifact).where(SourceArtifact.sha256 == digest)) is not None:
                continue
            suffix = ".json" if "json" in (captured["content_type"] or "") else ".html"
            stored = store.put(captured["content"], suffix)
            effective_at = None
            if captured["effective_date"]:
                effective_at = datetime.combine(captured["effective_date"], datetime.min.time(), tzinfo=ZoneInfo("Asia/Karachi"))
            db.add(SourceArtifact(data_source_id=data_source.id, source_url=captured["url"], effective_at=effective_at, sha256=stored.sha256, content_type=captured["content_type"], storage_path=stored.storage_path, parser_version=self.parser_version, status="parsed", response_metadata_json=json.dumps({"bytes": stored.bytes})))
            artifact_count += 1
        db.commit()
        result.update({"attempted_provider": self.source, "used_provider": self.source, "artifacts_written": artifact_count, "message": "Refreshed verified DPS market data with immutable raw artifacts."})
        return result

    def fetch_symbol_history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SymbolHistoryRow]:
        symbol = _normalize_symbol(symbol)
        end = end_date or date.today()
        start = start_date or date(end.year - 5, end.month, 1)
        cursor = date(start.year, start.month, 1)
        rows: dict[date, SymbolHistoryRow] = {}
        with self._client() as client:
            while cursor <= end:
                response = client.post("/historical", data={"month": str(cursor.month), "year": str(cursor.year), "symbol": symbol})
                response.raise_for_status()
                for row in self.parse_symbol_history(response.text, symbol):
                    if start <= row.trade_date <= end:
                        rows[row.trade_date] = row
                cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
        ordered = [rows[day] for day in sorted(rows)]
        for index in range(1, len(ordered)):
            ordered[index].previous_close = ordered[index - 1].close
        return ordered

    def fetch_sector_stats(self) -> list[SectorStatRow]:
        return []


class VendorMarketDataProvider(MarketDataProvider):
    mode = "vendor"
    source = "vendor"

    def health_check(self) -> dict[str, Any]:
        return {"ok": False, "provider": self.source, "detail": "Vendor adapter is a thin placeholder for a future paid/current-data integration."}

    def fetch_latest_prices(self, symbols: list[str] | None = None) -> list[LatestPriceRow]:
        raise NotImplementedError("Vendor adapter is intentionally a placeholder in this MVP phase.")

    def fetch_symbol_history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SymbolHistoryRow]:
        raise NotImplementedError("Vendor adapter is intentionally a placeholder in this MVP phase.")

    def fetch_sector_stats(self) -> list[SectorStatRow]:
        raise NotImplementedError("Vendor adapter is intentionally a placeholder in this MVP phase.")


class PsxDataMarketDataProvider(MarketDataProvider):
    mode = "psxdata"
    source = "psxdata"

    def _load_client(self) -> Any:
        try:
            from psxdata import PSXClient  # type: ignore
        except Exception as exc:  # pragma: no cover - exercised through tests via failure path
            raise RuntimeError("psxdata is not installed or failed to import") from exc
        return PSXClient()

    def health_check(self) -> dict[str, Any]:
        try:
            self._load_client()
        except Exception as exc:
            return {"ok": False, "provider": self.source, "detail": str(exc)}
        return {"ok": True, "provider": self.source}

    def _latest_payload(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        client = self._load_client()
        target_symbols = symbols or client.tickers()
        rows: list[dict[str, Any]] = []
        for symbol in target_symbols:
            quote_frame = client.quote(symbol)
            quote_rows = _coerce_rows(quote_frame)
            if not quote_rows:
                continue
            row = quote_rows[0]
            row["symbol"] = row.get("symbol") or symbol
            rows.append(row)
        return rows

    def fetch_latest_prices(self, symbols: list[str] | None = None) -> list[LatestPriceRow]:
        rows = self._latest_payload(symbols=symbols)
        latest_prices: list[LatestPriceRow] = []
        for row in rows:
            symbol = _normalize_symbol(row.get("symbol") or row.get("ticker") or row.get("code"))
            if not symbol:
                continue
            close = safe_decimal(row.get("close") or row.get("price") or row.get("ldcp") or row.get("last"))
            previous_close = safe_decimal(
                row.get("previous_close")
                or row.get("prev_close")
                or row.get("yesterday")
                or row.get("ldcp")
                or close
            )
            latest_prices.append(
                LatestPriceRow(
                    symbol=symbol,
                    name=row.get("name") or row.get("company") or row.get("company_name"),
                    sector=row.get("sector") or row.get("sector_name"),
                    trade_date=_as_date(row.get("trade_date") or row.get("date") or date.today()),
                    open=safe_decimal(row.get("open") or previous_close),
                    high=safe_decimal(row.get("high") or close),
                    low=safe_decimal(row.get("low") or close),
                    close=close,
                    previous_close=previous_close,
                    volume=safe_int(row.get("volume")),
                    source_url=row.get("source_url"),
                    market_cap=safe_decimal(row.get("market_cap")),
                )
            )
        return latest_prices

    def fetch_symbol_history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SymbolHistoryRow]:
        client = self._load_client()
        rows = _coerce_rows(client.stocks(symbol, start=start_date, end=end_date))
        history: list[SymbolHistoryRow] = []
        previous_close: Decimal | None = None
        for row in rows:
            close = safe_decimal(row.get("close") or row.get("price") or row.get("last"))
            history.append(
                SymbolHistoryRow(
                    symbol=_normalize_symbol(symbol),
                    trade_date=_as_date(row.get("trade_date") or row.get("date")),
                    open=safe_decimal(row.get("open") or previous_close or close),
                    high=safe_decimal(row.get("high") or close),
                    low=safe_decimal(row.get("low") or close),
                    close=close,
                    previous_close=safe_decimal(
                        row.get("previous_close") or row.get("prev_close") or previous_close or close
                    ),
                    volume=safe_int(row.get("volume")),
                    source_url=row.get("source_url"),
                    market_cap=safe_decimal(row.get("market_cap")),
                )
            )
            previous_close = close
        return history

    def fetch_sector_stats(self) -> list[SectorStatRow]:
        return []


class YahooFinanceMarketDataProvider(MarketDataProvider):
    mode = "yahoo"
    source = "yahoo"

    def __init__(self) -> None:
        self.last_ingestion_summary: dict[str, list[str]] = {
            "attempted_symbols": [],
            "successful_symbols": [],
            "skipped_symbols": [],
            "failed_symbols": [],
        }

    @staticmethod
    def resolve_yahoo_symbol(psx_symbol: str) -> str:
        return f"{_normalize_symbol(psx_symbol)}.KA"

    def _load_yfinance(self) -> Any:
        try:
            import yfinance as yf  # type: ignore
        except Exception as exc:  # pragma: no cover - exercised through tests via failure path
            raise RuntimeError("yfinance is not installed or failed to import") from exc
        return yf

    def health_check(self) -> dict[str, Any]:
        try:
            self._load_yfinance()
        except Exception as exc:
            return {"ok": False, "provider": self.source, "detail": str(exc)}
        return {"ok": True, "provider": self.source}

    def _resolve_symbols(self, symbols: list[str] | None = None) -> list[str]:
        if symbols is not None:
            return [_normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)]
        return [_normalize_symbol(symbol) for symbol in settings.market_data_default_symbols if _normalize_symbol(symbol)]

    def fetch_latest_prices(self, symbols: list[str] | None = None) -> list[LatestPriceRow]:
        yf = self._load_yfinance()
        symbols = self._resolve_symbols(symbols)
        if not symbols:
            raise RuntimeError(
                "Yahoo Finance provider requires explicit symbols or MARKET_DATA_DEFAULT_SYMBOLS; it will not fetch every company by default."
            )

        attempted_symbols: list[str] = []
        successful_symbols: list[str] = []
        skipped_symbols: list[str] = []
        failed_symbols: list[str] = []
        rows: list[LatestPriceRow] = []
        for symbol in symbols:
            attempted_symbols.append(symbol)
            yahoo_symbol = self.resolve_yahoo_symbol(symbol)
            try:
                history = yf.Ticker(yahoo_symbol).history(period="5d", auto_adjust=False)
            except Exception:
                failed_symbols.append(symbol)
                logger.warning("Yahoo Finance fetch failed for %s", yahoo_symbol, exc_info=True)
                continue
            if getattr(history, "empty", False):
                skipped_symbols.append(symbol)
                logger.info("Yahoo Finance returned no data for %s; skipping symbol.", yahoo_symbol)
                continue
            latest = history.iloc[-1]
            previous_close = latest.get("Close")
            if len(history.index) > 1:
                previous_close = history.iloc[-2].get("Close")
            close = safe_decimal(latest.get("Close"))
            open_price = safe_decimal(latest.get("Open"))
            high = safe_decimal(latest.get("High"))
            low = safe_decimal(latest.get("Low"))
            previous_close_decimal = safe_decimal(previous_close)
            volume = safe_int(latest.get("Volume"))
            if close is None:
                skipped_symbols.append(symbol)
                logger.info("Yahoo Finance returned unusable price data for %s; skipping symbol.", yahoo_symbol)
                continue
            rows.append(
                LatestPriceRow(
                    symbol=_normalize_symbol(symbol),
                    trade_date=_as_date(history.index[-1]),
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    previous_close=previous_close_decimal,
                    volume=volume,
                    source_url=f"https://finance.yahoo.com/quote/{yahoo_symbol}",
                )
            )
            successful_symbols.append(symbol)

        self.last_ingestion_summary = {
            "attempted_symbols": attempted_symbols,
            "successful_symbols": successful_symbols,
            "skipped_symbols": skipped_symbols,
            "failed_symbols": failed_symbols,
        }
        return rows

    def fetch_symbol_history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SymbolHistoryRow]:
        yf = self._load_yfinance()
        yahoo_symbol = self.resolve_yahoo_symbol(symbol)
        history = yf.Ticker(yahoo_symbol).history(start=start_date, end=end_date, auto_adjust=False)
        if getattr(history, "empty", False):
            return []

        rows: list[SymbolHistoryRow] = []
        previous_close: Decimal | None = None
        for idx, row in history.iterrows():
            close = safe_decimal(row.get("Close"))
            rows.append(
                SymbolHistoryRow(
                    symbol=_normalize_symbol(symbol),
                    trade_date=_as_date(idx),
                    open=safe_decimal(row.get("Open")),
                    high=safe_decimal(row.get("High")),
                    low=safe_decimal(row.get("Low")),
                    close=close,
                    previous_close=previous_close or close,
                    volume=safe_int(row.get("Volume")),
                    source_url=f"https://finance.yahoo.com/quote/{yahoo_symbol}",
                )
            )
            previous_close = close
        return rows

    def fetch_sector_stats(self) -> list[SectorStatRow]:
        return []

    def refresh_latest(self, db: Session) -> dict[str, Any]:
        from app.services.market_ingestion import persist_market_data

        symbols = self._resolve_symbols()
        latest_prices = self.fetch_latest_prices(symbols=symbols)
        if not latest_prices:
            raise RuntimeError(
                "yahoo returned no usable market price rows "
                f"(attempted={len(self.last_ingestion_summary['attempted_symbols'])}, "
                f"skipped={len(self.last_ingestion_summary['skipped_symbols'])}, "
                f"failed={len(self.last_ingestion_summary['failed_symbols'])})"
            )
        result = persist_market_data(db, latest_prices=latest_prices, source=self.source)
        result["attempted_provider"] = self.source
        result["used_provider"] = self.source
        result.update(self.last_ingestion_summary)
        result["message"] = (
            "Refreshed market data via yahoo. "
            f"attempted={len(self.last_ingestion_summary['attempted_symbols'])} "
            f"successful={len(self.last_ingestion_summary['successful_symbols'])} "
            f"skipped={len(self.last_ingestion_summary['skipped_symbols'])} "
            f"failed={len(self.last_ingestion_summary['failed_symbols'])}."
        )
        return result


class AutoMarketDataProvider(MarketDataProvider):
    mode = "auto"
    source = "auto"

    def __init__(self) -> None:
        self.primary_provider = DpsMarketDataProvider()
        self.fallback_provider = YahooFinanceMarketDataProvider()

    def health_check(self) -> dict[str, Any]:
        primary = self.primary_provider.health_check()
        if primary.get("ok"):
            return {"ok": True, "provider": self.primary_provider.source}
        fallback = self.fallback_provider.health_check()
        return {
            "ok": bool(fallback.get("ok")),
            "provider": fallback.get("provider"),
            "detail": primary.get("detail"),
        }

    def fetch_latest_prices(self, symbols: list[str] | None = None) -> list[LatestPriceRow]:
        try:
            rows = self.primary_provider.fetch_latest_prices(symbols=symbols)
            if rows:
                return rows
        except Exception:
            pass
        return self.fallback_provider.fetch_latest_prices(symbols=symbols)

    def fetch_symbol_history(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SymbolHistoryRow]:
        try:
            rows = self.primary_provider.fetch_symbol_history(symbol, start_date, end_date)
            if rows:
                return rows
        except Exception:
            pass
        return self.fallback_provider.fetch_symbol_history(symbol, start_date, end_date)

    def fetch_sector_stats(self) -> list[SectorStatRow]:
        return []

    def refresh_latest(self, db: Session) -> dict[str, Any]:
        primary_error: str | None = None
        try:
            result = self.primary_provider.refresh_latest(db)
            result["attempted_provider"] = self.source
            result["used_provider"] = self.primary_provider.source
            return result
        except Exception as exc:
            primary_error = str(exc)

        result = self.fallback_provider.refresh_latest(db)
        result["attempted_provider"] = self.source
        result["used_provider"] = self.fallback_provider.source
        result["message"] = (
            "DPS refresh failed; Yahoo fallback succeeded."
            if primary_error
            else result.get("message", "yahoo fallback succeeded.")
        )
        return result


def get_market_data_provider(mode: str) -> MarketDataProvider:
    normalized = mode.lower()
    providers: dict[str, MarketDataProvider] = {
        "mock": MockMarketDataProvider(),
        "psxdata": PsxDataMarketDataProvider(),
        "yahoo": YahooFinanceMarketDataProvider(),
        "auto": AutoMarketDataProvider(),
        "dps": DpsMarketDataProvider(),
        "vendor": VendorMarketDataProvider(),
    }
    if normalized not in providers:
        raise KeyError(f"Unsupported market data mode: {mode}")
    return providers[normalized]
