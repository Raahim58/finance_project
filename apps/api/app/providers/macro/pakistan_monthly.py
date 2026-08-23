from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from app.core.config import settings
from app.providers.macro.contracts import ProviderObservation, ProviderResult


USER_AGENT = (
    f"psx-ai-portfolio-agent/0.1 "
    f"({settings.evidence_contact_email})"
)

MAX_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class PakistanMonthlyContract:
    key: str
    landing_url: str
    link_patterns: tuple[str, ...]
    row_patterns: tuple[str, ...]
    unit_multiplier: Decimal = Decimal("1")


CONTRACTS: dict[str, PakistanMonthlyContract] = {
    # SBP summary BOP workbook is reported in million USD.
    "CURRENT_ACCOUNT_USD": PakistanMonthlyContract(
        key="CURRENT_ACCOUNT_USD",
        landing_url="https://www.sbp.org.pk/economic-data",
        link_patterns=(
            "summary of balance of payments as per bpm6",
            "summary balance of payments bpm6",
        ),
        row_patterns=(
            r"^current\s+account\s+balance$",
        ),
        unit_multiplier=Decimal("1000000"),
    ),

    "EXPORTS_USD": PakistanMonthlyContract(
        key="EXPORTS_USD",
        landing_url="https://www.sbp.org.pk/economic-data",
        link_patterns=(
            "export and import of goods and services",
            "summary of balance of payments as per bpm6",
        ),
        row_patterns=(
            r"^exports?\s+of\s+goods\s+fob$",
            r"^exports?\s+of\s+goods$",
        ),
        unit_multiplier=Decimal("1000000"),
    ),

    "IMPORTS_USD": PakistanMonthlyContract(
        key="IMPORTS_USD",
        landing_url="https://www.sbp.org.pk/economic-data",
        link_patterns=(
            "export and import of goods and services",
            "summary of balance of payments as per bpm6",
        ),
        row_patterns=(
            r"^imports?\s+of\s+goods\s+fob$",
            r"^imports?\s+of\s+goods$",
        ),
        unit_multiplier=Decimal("1000000"),
    ),
}


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None

    text = str(value).strip().replace(",", "")

    if not text or text.lower() in {
        "nan",
        "none",
        "-",
        "—",
        "..",
    }:
        return None

    # Parentheses = negative accounting value.
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]

    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None

    return value if value.is_finite() else None


def _get(url: str) -> tuple[bytes, str, str]:
    with httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()

            chunks: list[bytes] = []
            total = 0

            for chunk in response.iter_bytes():
                total += len(chunk)

                if total > MAX_BYTES:
                    raise ValueError(
                        "Pakistan monthly macro response exceeded 25 MiB"
                    )

                chunks.append(chunk)

            return (
                b"".join(chunks),
                str(response.url),
                response.headers.get("content-type", ""),
            )


def _normalize(value: object) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _discover_download(
    landing_url: str,
    patterns: tuple[str, ...],
) -> str:
    """
    Find the current official Excel/download URL from the SBP landing page.

    This means we do NOT hard-code a dated workbook URL.
    """
    content, final_url, _ = _get(landing_url)

    soup = BeautifulSoup(content, "html.parser")

    candidates: list[tuple[int, str]] = []

    for anchor in soup.find_all("a", href=True):
        text = _normalize(anchor.get_text(" ", strip=True))
        href = str(anchor.get("href") or "").strip()

        if not href:
            continue

        combined = f"{text} {_normalize(href)}"

        score = 0

        for pattern in patterns:
            if pattern in combined:
                score += 10

        lower_href = href.lower()

        if lower_href.endswith((".xls", ".xlsx")):
            score += 5

        if "excel" in text:
            score += 3

        if score:
            candidates.append(
                (score, urljoin(final_url, href))
            )

    if not candidates:
        raise ValueError(
            f"No official workbook link matched {patterns!r}"
        )

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return candidates[0][1]


MONTH_RE = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[- /]*(\d{2,4})$",
    re.I,
)


def _parse_month(value: object) -> date | None:
    if isinstance(value, pd.Timestamp):
        return date(
            value.year,
            value.month,
            1,
        )

    if isinstance(value, datetime):
        return date(
            value.year,
            value.month,
            1,
        )

    text = _normalize(value)

    if not text:
        return None

    # 2026-06 / 2026-06-30 etc.
    parsed = pd.to_datetime(
        text,
        errors="coerce",
    )

    if not pd.isna(parsed):
        return date(
            parsed.year,
            parsed.month,
            1,
        )

    match = MONTH_RE.match(text)

    if match:
        month_name = match.group(1)[:3].title()
        year = int(match.group(2))

        if year < 100:
            year += 2000

        month = datetime.strptime(
            month_name,
            "%b",
        ).month

        return date(year, month, 1)

    return None


def _matching_row(
    frame: pd.DataFrame,
    patterns: tuple[str, ...],
) -> int | None:
    compiled = [
        re.compile(pattern, re.I)
        for pattern in patterns
    ]

    for row_number in range(len(frame)):
        values = [
            _normalize(value)
            for value in frame.iloc[row_number].tolist()
        ]

        for value in values:
            if any(
                pattern.search(value)
                for pattern in compiled
            ):
                return row_number

    return None


def _extract_monthly_row(
    frame: pd.DataFrame,
    row_number: int,
    multiplier: Decimal,
) -> list[ProviderObservation]:
    """
    Handles the common SBP layout:

        Items | Jul-2025 | Aug-2025 | Sep-2025 ...
        Current Account Balance | -500 | ...

    It finds month-like headers above the matching row rather than relying
    on a fixed header row.
    """
    row = frame.iloc[row_number]

    best_header: int | None = None
    best_months: dict[int, date] = {}

    # Header should normally be somewhere above the data row.
    start = max(0, row_number - 15)

    for candidate_header in range(
        start,
        row_number,
    ):
        months: dict[int, date] = {}

        for col in range(frame.shape[1]):
            observed = _parse_month(
                frame.iloc[candidate_header, col]
            )

            if observed:
                months[col] = observed

        if len(months) > len(best_months):
            best_header = candidate_header
            best_months = months

    if best_header is None or not best_months:
        raise ValueError(
            "Could not identify monthly columns in official workbook"
        )

    observations: list[ProviderObservation] = []

    for col, effective_date in best_months.items():
        value = _decimal(row.iloc[col])

        if value is None:
            continue

        observations.append(
            ProviderObservation(
                effective_date=effective_date,
                value=value * multiplier,
            )
        )

    return sorted(
        observations,
        key=lambda item: item.effective_date,
    )


def _read_excel_any_sheet(
    content: bytes,
    patterns: tuple[str, ...],
    multiplier: Decimal,
) -> tuple[list[ProviderObservation], str]:
    workbook = pd.ExcelFile(
        io.BytesIO(content)
    )

    for sheet_name in workbook.sheet_names:
        frame = pd.read_excel(
            io.BytesIO(content),
            sheet_name=sheet_name,
            header=None,
        )

        row_number = _matching_row(
            frame,
            patterns,
        )

        if row_number is None:
            continue

        observations = _extract_monthly_row(
            frame,
            row_number,
            multiplier,
        )

        if observations:
            return observations, str(sheet_name)

    raise ValueError(
        f"Could not find target row {patterns!r} "
        f"in workbook sheets {workbook.sheet_names!r}"
    )


def fetch_sbp_monthly(
    source_series_id: str,
    start: date,
    end: date,
) -> ProviderResult:
    contract = CONTRACTS[source_series_id]

    download_url = _discover_download(
        contract.landing_url,
        contract.link_patterns,
    )

    content, final_url, content_type = _get(
        download_url
    )

    observations, sheet = _read_excel_any_sheet(
        content,
        contract.row_patterns,
        contract.unit_multiplier,
    )

    filtered = tuple(
        observation
        for observation in observations
        if start <= observation.effective_date <= end
    )

    if not filtered:
        raise ValueError(
            f"SBP monthly provider {source_series_id} "
            "returned no observations"
        )

    return ProviderResult(
        provider_key="",  # filled by series.py wrapper
        source_series_id=source_series_id,
        url=final_url,
        content=content,
        content_type=(
            content_type
            or "application/vnd.ms-excel"
        ),
        parser_version=(
            f"sbp-monthly-workbook-v1:{sheet}"
        ),
        retrieved_at=datetime.now(UTC),
        observations=filtered,
    )

SBP_REMITTANCES_URL = (
    "https://easydata.sbp.org.pk/apex/"
    "f?p=10:220:3863248920700::NO:RP:"
    "P220_SERIES_KEY,P220_PAGE_ID:"
    "TS_GP_BOP_WR_M.WR0340,215"
)


def fetch_sbp_remittances_recent(
    start: date,
    end: date,
) -> ProviderResult:
    content, final_url, content_type = _get(
        SBP_REMITTANCES_URL
    )

    soup = BeautifulSoup(
        content,
        "html.parser",
    )

    text = " ".join(
        soup.stripped_strings
    )

    # EasyData chart page contains period labels like:
    # Jan-2026 Feb-2026 ... followed by recent observations.
    months = re.findall(
        r"\b("
        r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|"
        r"Sep|Oct|Nov|Dec"
        r")-(\d{4})\b",
        text,
        re.I,
    )

    # Locate the Recent Observations section.
    marker = text.lower().find(
        "recent observations"
    )

    if marker == -1:
        raise ValueError(
            "SBP EasyData remittance page contract changed"
        )

    recent = text[marker:]

    number_strings = re.findall(
        r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?",
        recent,
    )

    values = [
        _decimal(value)
        for value in number_strings
    ]

    values = [
        value
        for value in values
        if value is not None
    ]

    month_dates = [
        date(
            int(year),
            datetime.strptime(
                month[:3].title(),
                "%b",
            ).month,
            1,
        )
        for month, year in months
    ]

    # Use only matching tail lengths.
    count = min(
        len(month_dates),
        len(values),
    )

    observations = tuple(
        ProviderObservation(
            effective_date=month_dates[-count + i],
            value=values[-count + i],
        )
        for i in range(count)
        if start <= month_dates[-count + i] <= end
    )

    if not observations:
        raise ValueError(
            "SBP EasyData returned no remittance observations"
        )

    return ProviderResult(
        provider_key="",
        source_series_id=(
            "TS_GP_BOP_WR_M.WR0340"
        ),
        url=final_url,
        content=content,
        content_type=content_type or "text/html",
        parser_version=(
            "sbp-easydata-remittances-html-v1"
        ),
        retrieved_at=datetime.now(UTC),
        observations=observations,
    )
