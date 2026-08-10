from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import re
from typing import Any
from zoneinfo import ZoneInfo

import httpx


@dataclass(frozen=True)
class ScsTradePrice:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    change: Decimal


class ScsTradeProvider:
    source = "scstrade"
    endpoint = "https://www.scstrade.com/MarketStatistics/MS_HistoricalPrices.aspx/chart"
    parser_version = "scstrade-chart-json-v1"
    enabled = True

    @staticmethod
    def parse_history(payload: Any) -> list[ScsTradePrice]:
        if not isinstance(payload, dict) or not isinstance(payload.get("d"), list):
            raise ValueError("SCSTrade chart response must contain a d array")
        rows = []
        for item in payload["d"]:
            if not isinstance(item, dict):
                continue
            match = re.fullmatch(r"/Date\((\d+)\)/", str(item.get("trading_Date", "")))
            if not match:
                continue
            try:
                open_price = Decimal(str(item["trading_open"])); high = Decimal(str(item["trading_high"])); low = Decimal(str(item["trading_low"])); close = Decimal(str(item["trading_close"])); change = Decimal(str(item["trading_change"])); volume = int(item["trading_vol"])
            except (KeyError, ValueError, TypeError):
                continue
            if min(open_price, high, low, close) <= 0 or high < max(open_price, close) or low > min(open_price, close) or volume < 0:
                continue
            day = datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC).astimezone(ZoneInfo("Asia/Karachi")).date()
            rows.append(ScsTradePrice(day, open_price, high, low, close, volume, change))
        return sorted(rows, key=lambda row: row.trade_date)

    def fetch_history(self, symbol: str, start_date: date, end_date: date) -> list[ScsTradePrice]:
        body = {"par": symbol.strip().upper(), "date1": start_date.strftime("%m/%d/%Y"), "date2": end_date.strftime("%m/%d/%Y")}
        with httpx.Client(timeout=30, headers={"User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate ingestion)", "Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest"}) as client:
            response = client.post(self.endpoint, json=body)
            response.raise_for_status()
            return self.parse_history(response.json())
