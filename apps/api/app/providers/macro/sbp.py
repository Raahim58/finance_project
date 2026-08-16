# from __future__ import annotations

# from datetime import date, datetime
# import re

# import httpx
# from bs4 import BeautifulSoup

# from app.providers.macro.official_workbooks import MacroObservation


# class SbpKeyIndicatorsProvider:
#     source = "sbp"
#     page_url = "https://www.sbp.org.pk/"
#     parser_version = "sbp-key-indicators-html-v1"
#     enabled = True

#     @staticmethod
#     def parse(content: bytes, retrieved_on: date) -> list[MacroObservation]:
#         text = " ".join(BeautifulSoup(content, "html.parser").get_text(" ", strip=True).split())
#         rows: list[MacroObservation] = []
#         policy = re.search(r"SBP\s+Policy\s+Rate\s+([0-9]+(?:\.[0-9]+)?)\s*%", text, re.I)
#         if policy:
#             rows.append(MacroObservation("sbp.policy_rate", retrieved_on, float(policy.group(1)), "percent", "sbp"))

#         auction = re.search(
#             r"MTBs.*?3\s*-?\s*M\s+([0-9]+(?:\.[0-9]+)?)\s*%.*?\(\s*as\s+on\s+([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})\s*\)",
#             text,
#             re.I,
#         )
#         if auction:
#             effective = datetime.strptime(auction.group(2), "%b %d, %Y").date() if len(auction.group(2).split()[0]) == 3 else datetime.strptime(auction.group(2), "%B %d, %Y").date()
#             rows.append(MacroObservation("sbp.tbill.3m_yield", effective, float(auction.group(1)), "percent", "sbp"))

#         if not rows:
#             raise ValueError("SBP key-indicator page contract changed")
#         return rows

#     def fetch(self) -> tuple[bytes, list[MacroObservation]]:
#         response = httpx.get(self.page_url, timeout=30, follow_redirects=True, headers={"User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate ingestion)"})
#         response.raise_for_status()
#         return response.content, self.parse(response.content, date.today())

from __future__ import annotations

from datetime import date, datetime
import re

import httpx
from bs4 import BeautifulSoup

from app.providers.macro.official_workbooks import MacroObservation


def _number(value: str) -> float:
    return float(value.replace(",", "").strip())


def _parse_sbp_date(value: str) -> date:
    """
    Handles SBP formats such as:
      10- July - 2026
      20- Jul - 26
      20 Jul - 2026
      Jun 23, 2026
    """
    cleaned = value.replace(",", " ")
    cleaned = re.sub(r"\s*-\s*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    formats = (
        "%d %B %Y",
        "%d %b %Y",
        "%d %B %y",
        "%d %b %y",
        "%B %d %Y",
        "%b %d %Y",
    )

    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Could not parse SBP date: {value!r}")


class SbpKeyIndicatorsProvider:
    source = "sbp"
    page_url = "https://www.sbp.org.pk/"
    parser_version = "sbp-key-indicators-html-v2"
    enabled = True

    @staticmethod
    def parse(
        content: bytes,
        retrieved_on: date,
    ) -> list[MacroObservation]:
        text = " ".join(
            BeautifulSoup(
                content,
                "html.parser",
            ).get_text(" ", strip=True).split()
        )

        rows: list[MacroObservation] = []

        # ---------------------------------------------------------
        # 1. POLICY RATE
        # ---------------------------------------------------------

        policy = re.search(
            r"SBP\s+Policy\s+Rate\s+"
            r"([0-9]+(?:\.[0-9]+)?)\s*%",
            text,
            re.I,
        )

        if policy:
            rows.append(
                MacroObservation(
                    "sbp.policy_rate",
                    retrieved_on,
                    _number(policy.group(1)),
                    "percent",
                    "sbp",
                )
            )

        # ---------------------------------------------------------
        # 2. TOTAL FX RESERVES
        #
        # SBP reports USD million, while our canonical series is USD.
        # ---------------------------------------------------------

        reserves = re.search(
            r"Liquid\s+Foreign\s+Exchange\s+Reserves"
            r"\s*\(USD\s+million\)"
            r".*?"
            r"As\s+on\s+"
            r"(?P<date>.+?)"
            r"\s+SBP.?s\s+Reserves"
            r".*?"
            r"Bank.?s\s+Reserves"
            r".*?"
            r"Total\s+Reserves\s+"
            r"(?P<value>[0-9,]+(?:\.[0-9]+)?)"
            r"\s+Money\s+Market",
            text,
            re.I,
        )

        if reserves:
            effective = _parse_sbp_date(
                reserves.group("date")
            )

            # Page reports USD million.
            total_usd = (
                _number(reserves.group("value"))
                * 1_000_000
            )

            rows.append(
                MacroObservation(
                    "sbp.total_reserves_usd",
                    effective,
                    total_usd,
                    "USD",
                    "sbp",
                )
            )

        # ---------------------------------------------------------
        # 3. 3-MONTH KIBOR OFFER RATE
        # ---------------------------------------------------------

        kibor = re.search(
            r"KIBOR\s+As\s+on\s+"
            r"(?P<date>.+?)"
            r"\s+Tenor\s+BID\s+Offer\s+"
            r"3-M\s+"
            r"(?P<bid>[0-9]+(?:\.[0-9]+)?)\s+"
            r"(?P<offer>[0-9]+(?:\.[0-9]+)?)",
            text,
            re.I,
        )

        if kibor:
            effective = _parse_sbp_date(
                kibor.group("date")
            )

            rows.append(
                MacroObservation(
                    "sbp.kibor.3m_offer",
                    effective,
                    _number(kibor.group("offer")),
                    "percent",
                    "sbp",
                )
            )

        # ---------------------------------------------------------
        # 4. USD / PKR M2M RATE
        # ---------------------------------------------------------

        fx = re.search(
            r"USD/\s*PKR\s+Rates"
            r".*?"
            r"As\s+on\s+"
            r"(?P<date>.+?)"
            r"\s+M2M\s+Revaluation\s+Rate\s+"
            r"(?P<value>[0-9,]+(?:\.[0-9]+)?)"
            r"\s+Weighted\s+Average\s+Rate",
            text,
            re.I,
        )

        if fx:
            effective = _parse_sbp_date(
                fx.group("date")
            )

            rows.append(
                MacroObservation(
                    "sbp.usd_pkr.m2m",
                    effective,
                    _number(fx.group("value")),
                    "PKR_per_USD",
                    "sbp",
                )
            )

        # ---------------------------------------------------------
        # 5. EXISTING 3M MTB PARSER
        #
        # Leave existing behavior here for now.
        # ---------------------------------------------------------

        auction = re.search(
            r"MTBs.*?"
            r"3\s*-?\s*M\s+"
            r"([0-9]+(?:\.[0-9]+)?)\s*%"
            r".*?"
            r"\(\s*as\s+on\s+"
            r"([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})"
            r"\s*\)",
            text,
            re.I,
        )

        if auction:
            try:
                effective = datetime.strptime(
                    auction.group(2),
                    "%b %d, %Y",
                ).date()
            except ValueError:
                effective = datetime.strptime(
                    auction.group(2),
                    "%B %d, %Y",
                ).date()

            rows.append(
                MacroObservation(
                    "sbp.tbill.3m_yield",
                    effective,
                    _number(auction.group(1)),
                    "percent",
                    "sbp",
                )
            )

        if not rows:
            raise ValueError(
                "SBP key-indicator page contract changed"
            )

        return rows

    def fetch(
        self,
    ) -> tuple[bytes, list[MacroObservation]]:
        response = httpx.get(
            self.page_url,
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "psx-ai-portfolio-agent/0.1 "
                    "(personal research; low-rate ingestion)"
                )
            },
        )

        response.raise_for_status()

        return (
            response.content,
            self.parse(
                response.content,
                date.today(),
            ),
        )