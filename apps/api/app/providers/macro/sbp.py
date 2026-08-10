from __future__ import annotations

from datetime import date, datetime
import re

import httpx
from bs4 import BeautifulSoup

from app.providers.macro.official_workbooks import MacroObservation


class SbpKeyIndicatorsProvider:
    source = "sbp"
    page_url = "https://www.sbp.org.pk/"
    parser_version = "sbp-key-indicators-html-v1"
    enabled = True

    @staticmethod
    def parse(content: bytes, retrieved_on: date) -> list[MacroObservation]:
        text = " ".join(BeautifulSoup(content, "html.parser").get_text(" ", strip=True).split())
        rows: list[MacroObservation] = []
        policy = re.search(r"SBP\s+Policy\s+Rate\s+([0-9]+(?:\.[0-9]+)?)\s*%", text, re.I)
        if policy:
            rows.append(MacroObservation("sbp.policy_rate", retrieved_on, float(policy.group(1)), "percent", "sbp"))

        auction = re.search(
            r"MTBs.*?3\s*-?\s*M\s+([0-9]+(?:\.[0-9]+)?)\s*%.*?\(\s*as\s+on\s+([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})\s*\)",
            text,
            re.I,
        )
        if auction:
            effective = datetime.strptime(auction.group(2), "%b %d, %Y").date() if len(auction.group(2).split()[0]) == 3 else datetime.strptime(auction.group(2), "%B %d, %Y").date()
            rows.append(MacroObservation("sbp.tbill.3m_yield", effective, float(auction.group(1)), "percent", "sbp"))

        if not rows:
            raise ValueError("SBP key-indicator page contract changed")
        return rows

    def fetch(self) -> tuple[bytes, list[MacroObservation]]:
        response = httpx.get(self.page_url, timeout=30, follow_redirects=True, headers={"User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate ingestion)"})
        response.raise_for_status()
        return response.content, self.parse(response.content, date.today())
