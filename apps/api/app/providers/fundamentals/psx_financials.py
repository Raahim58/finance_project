from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ReportCatalogItem:
    symbol: str
    report_type: str
    period_ended: str
    posting_date: date
    report_url: str
    report_id: str


class PsxFinancialsProvider:
    source = "psx_financials"
    base_url = "https://financials.psx.com.pk/"
    parser_version = "psx-financials-json-v1"
    enabled = True

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=30, follow_redirects=True, headers={"User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate ingestion)"})

    @classmethod
    def parse_catalog(cls, payload: Any, symbol: str) -> list[ReportCatalogItem]:
        if not isinstance(payload, list):
            raise ValueError("PSX Financials catalog must be a JSON array")
        items: list[ReportCatalogItem] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            fragment = BeautifulSoup(str(row.get("Reports") or ""), "html.parser")
            link = fragment.find("a", href=True)
            if link is None or "DownloadPDF.php?id=" not in str(link["href"]):
                continue
            report_id = str(link["href"]).split("id=", 1)[1].strip()
            try:
                posted = date.fromisoformat(str(row["posting_date"]))
            except (KeyError, ValueError):
                continue
            items.append(ReportCatalogItem(
                symbol=symbol.strip().upper(), report_type=link.get_text(" ", strip=True).lower(),
                period_ended=str(row.get("period_ended") or "").strip(), posting_date=posted,
                report_url=urljoin(cls.base_url, str(link["href"])), report_id=report_id,
            ))
        return items

    def fetch_company_catalog(self, symbol: str) -> list[ReportCatalogItem]:
        symbol = symbol.strip().upper()
        with self._client() as client:
            response = client.post("annQtrStmts.php", data={"name": "get_comp_data", "smbCode": symbol})
            response.raise_for_status()
            return self.parse_catalog(response.json(), symbol)

    def fetch_company_year_catalog(self, symbol: str, year: int) -> list[ReportCatalogItem]:
        symbol = symbol.strip().upper()
        with self._client() as client:
            response = client.post("annQtrStmts.php", data={"name": "get_comp_y_data", "smbCode": symbol, "year": str(year)})
            response.raise_for_status()
            return self.parse_catalog(response.json(), symbol)

    def fetch_report(self, item: ReportCatalogItem) -> bytes:
        with self._client() as client:
            response = client.get(item.report_url)
            response.raise_for_status()
            if "application/pdf" not in response.headers.get("content-type", "").lower() or not response.content.startswith(b"%PDF"):
                raise ValueError("PSX Financials report response was not a PDF")
            return response.content
