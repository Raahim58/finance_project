"""Observed parser for the standardized tables rendered on DPS company pages."""
from dataclasses import dataclass
from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation
import re

import httpx
from bs4 import BeautifulSoup, Tag


METRICS = {
    "sales": "revenue",
    "revenue": "revenue",
    "total income": "total_income",
    "profit after taxation": "net_income",
    "profit after tax": "net_income",
    "net income": "net_income",
    "eps": "earnings_per_share",
    "gross profit margin (%)": "gross_margin",
    "net profit margin (%)": "net_margin",
    "eps growth (%)": "eps_growth",
}


@dataclass(frozen=True)
class StandardizedFactRow:
    metric: str
    period_type: str
    period_key: str
    period_end: date | None
    value: Decimal
    unit: str
    currency: str | None
    source_label: str


def _number(value: str) -> Decimal | None:
    token = value.strip().replace(",", "")
    negative = token.startswith("(") and token.endswith(")")
    try:
        parsed = Decimal(token.strip("()"))
    except InvalidOperation:
        return None
    return -parsed if negative else parsed


def _period(value: str, fiscal_year_end_month: int | None = None) -> tuple[str, date | None, str] | None:
    label = " ".join(value.split()).upper()
    annual = re.fullmatch(r"20\d{2}", label)
    quarter = re.fullmatch(r"Q([1-4])\s+(20\d{2})", label)
    if not annual and not quarter: return None
    if fiscal_year_end_month is None:
        return label,None,"annual" if annual else "quarterly"
    if not 1<=fiscal_year_end_month<=12: raise ValueError("Invalid fiscal year end month")
    year=int(label) if annual else int(quarter.group(2))
    if annual: month=fiscal_year_end_month
    else:
        # Fiscal year labels identify the year in which that fiscal year ends.
        end_index=year*12+fiscal_year_end_month-1-(4-int(quarter.group(1)))*3
        year,zero_month=divmod(end_index,12);month=zero_month+1
    return label,date(year,month,monthrange(year,month)[1]),"annual" if annual else "quarterly"


def parse_company_page(html: str, *, fiscal_year_end_month: int | None = None) -> tuple[list[StandardizedFactRow], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    tables: list[Tag] = []
    for table in soup.find_all("table"):
        labels = {" ".join(cell.get_text(" ", strip=True).lower().split()) for cell in table.find_all(["th", "td"])}
        if labels & set(METRICS):
            tables.append(table)
    facts: list[StandardizedFactRow] = []
    seen: set[tuple[str, str, str]] = set()
    diagnostics: list[str] = []
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
        parsed_periods = [_period(value, fiscal_year_end_month) for value in headers[1:]]
        if not parsed_periods or all(value is None for value in parsed_periods):
            continue
        for row in rows[1:]:
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            source_label = " ".join(cells[0].lower().split())
            metric = METRICS.get(source_label)
            if metric is None:
                continue
            for raw, period in zip(cells[1:], parsed_periods, strict=False):
                if period is None:
                    continue
                value = _number(raw)
                if value is None:
                    continue
                period_key, period_end, period_type = period
                is_per_share = metric == "earnings_per_share"
                is_ratio = metric in {"gross_margin", "net_margin", "eps_growth"}
                key = (metric, period_type, period_key)
                if key in seen:
                    continue
                facts.append(StandardizedFactRow(
                    metric=metric, period_type=period_type, period_key=period_key,
                    period_end=period_end, value=value if is_per_share or is_ratio else value * Decimal("1000"),
                    unit="percent" if is_ratio else "PKR", currency=None if is_ratio else "PKR", source_label=cells[0],
                ))
                seen.add(key)
    if facts and fiscal_year_end_month is None:
        diagnostics.append("Fiscal calendar is unverified; period labels retained without invented dates.")
    if not facts:
        diagnostics.append("DPS page exposed no recognized standardized financial rows; values remain unavailable.")
    return facts, diagnostics


class DpsStandardizedFundamentalsProvider:
    source = "dps"
    parser_version = "dps-company-financials-v2"
    base_url = "https://dps.psx.com.pk"

    def fetch(self, symbol: str, *, fiscal_year_end_month: int | None = None) -> tuple[bytes, list[StandardizedFactRow], list[str], str]:
        url = f"{self.base_url}/company/{symbol.strip().upper()}"
        with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate ingestion)"}) as client:
            response = client.get(url)
            response.raise_for_status()
        facts, diagnostics = parse_company_page(response.text, fiscal_year_end_month=fiscal_year_end_month)
        return response.content, facts, diagnostics, url
