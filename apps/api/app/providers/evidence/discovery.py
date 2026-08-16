"""Pure parsers for reusable evidence discovery formats."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import struct_time
from urllib.parse import urljoin
from urllib.parse import quote

import feedparser
from bs4 import BeautifulSoup
from lxml import etree

from app.ingestion.evidence import Candidate
from app.providers.evidence.extraction import normalize_url, parse_datetime


def _feed_time(entry: dict, key: str) -> datetime | None:
    value = entry.get(f"{key}_parsed")
    if isinstance(value, struct_time):
        return datetime(*value[:6], tzinfo=UTC)
    return parse_datetime(entry.get(key))


@dataclass(frozen=True)
class RssAtomDiscovery:
    source_key: str
    publisher: str
    topic: str | None = None
    base_url: str | None = None

    def parse(self, content: bytes, *, discovered_at: datetime | None = None) -> tuple[Candidate, ...]:
        parsed = feedparser.parse(content)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Invalid RSS/Atom feed: {parsed.bozo_exception}")
        now = discovered_at or datetime.now(UTC)
        rows: list[Candidate] = []
        for entry in parsed.entries:
            url = str(entry.get("link") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not url or not title:
                continue
            try:
                canonical = normalize_url(url, self.base_url)
            except ValueError:
                # A malformed entry must not invalidate an otherwise healthy
                # official feed. Source health captures an empty/invalid feed.
                continue
            rows.append(
                Candidate(
                    source_key=self.source_key,
                    # Fetch the resolved URL. Several official feeds (including
                    # EIA) publish root-relative entry links; retaining the raw
                    # link here makes the downstream bounded HTTP client reject
                    # an otherwise valid candidate before making a request.
                    observed_url=canonical,
                    canonical_url=canonical,
                    external_id=str(entry.get("id") or canonical),
                    headline=title,
                    publisher=self.publisher,
                    discovered_at=now,
                    published_at=_feed_time(entry, "published") or _feed_time(entry, "updated"),
                    discovery_method="rss_atom",
                    topic=self.topic,
                    language=str(entry.get("language") or "").strip() or None,
                    metadata={"summary": str(entry.get("summary") or "").strip()},
                )
            )
        return tuple(rows)


@dataclass(frozen=True)
class SitemapDiscovery:
    source_key: str
    publisher: str
    topic: str | None = None

    def parse(self, content: bytes, *, discovered_at: datetime | None = None) -> tuple[Candidate, ...]:
        try:
            root = etree.fromstring(content, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        except etree.XMLSyntaxError as exc:
            raise ValueError("Invalid sitemap XML") from exc
        now = discovered_at or datetime.now(UTC)
        rows: list[Candidate] = []
        for node in root.xpath("//*[local-name()='url']"):
            locations = node.xpath("./*[local-name()='loc']/text()")
            if not locations:
                continue
            canonical = normalize_url(str(locations[0]))
            titles = node.xpath(".//*[local-name()='title']/text()")
            dates = node.xpath(".//*[local-name()='publication_date']/text()") or node.xpath(
                "./*[local-name()='lastmod']/text()"
            )
            title = str(titles[0]).strip() if titles else canonical.rsplit("/", 1)[-1].replace("-", " ")
            rows.append(
                Candidate(
                    source_key=self.source_key,
                    observed_url=canonical,
                    canonical_url=canonical,
                    external_id=canonical,
                    headline=title,
                    publisher=self.publisher,
                    discovered_at=now,
                    published_at=parse_datetime(dates[0]) if dates else None,
                    discovery_method="news_sitemap" if titles else "sitemap",
                    topic=self.topic,
                )
            )
        return tuple(rows)


@dataclass(frozen=True)
class GdeltDiscovery:
    source_key: str = "gdelt"
    publisher: str = "GDELT discovery"
    topic: str | None = None

    def parse(self, payload: dict, *, discovered_at: datetime | None = None) -> tuple[Candidate, ...]:
        now = discovered_at or datetime.now(UTC)
        rows: list[Candidate] = []
        for article in payload.get("articles", []):
            if not isinstance(article, dict):
                continue
            url = str(article.get("url") or "").strip()
            title = str(article.get("title") or "").strip()
            if not url or not title:
                continue
            canonical = normalize_url(url)
            rows.append(
                Candidate(
                    source_key=self.source_key,
                    observed_url=url,
                    canonical_url=canonical,
                    external_id=canonical,
                    headline=title,
                    publisher=str(article.get("domain") or self.publisher),
                    discovered_at=now,
                    published_at=parse_datetime(article.get("seendate")),
                    discovery_method="gdelt_doc_api",
                    topic=self.topic,
                    language=str(article.get("language") or "").strip() or None,
                    metadata={"source_country": article.get("sourcecountry")},
                )
            )
        return tuple(rows)

    @staticmethod
    def request_params(query: str, limit: int) -> dict[str, str | int]:
        return {"query": query, "mode": "artlist", "format": "json", "maxrecords": min(limit, 250)}


@dataclass(frozen=True)
class ListingDiscovery:
    source_key: str
    publisher: str
    base_url: str
    link_pattern: str
    topic: str | None = None

    def parse(self, content: bytes, *, discovered_at: datetime | None = None) -> tuple[Candidate, ...]:
        soup = BeautifulSoup(content, "lxml")
        now = discovered_at or datetime.now(UTC)
        matcher = re.compile(self.link_pattern, re.I)
        rows: list[Candidate] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if not href or href.lower().startswith(
                ("#", "javascript:", "mailto:", "tel:", "data:")
            ):
                continue
            try:
                url = normalize_url(urljoin(self.base_url, href))
            except ValueError:
                # Navigation chrome often contains malformed or non-web links.
                # Skip the bad anchor instead of failing the whole source page.
                continue
            title = anchor.get_text(" ", strip=True)
            if not title or not matcher.search(url) or url in seen:
                continue
            seen.add(url)
            rows.append(
                Candidate(
                    source_key=self.source_key,
                    observed_url=url,
                    canonical_url=url,
                    external_id=url,
                    headline=title,
                    publisher=self.publisher,
                    discovered_at=now,
                    discovery_method="listing_page",
                    topic=self.topic,
                )
            )
        return tuple(rows)


def parse_sec_submissions(
    payload: dict,
    *,
    source_key: str = "sec_edgar_selected",
    allowed_forms: frozenset[str] = frozenset({"8-K", "10-K", "10-Q", "20-F", "6-K"}),
    limit: int = 40,
    discovered_at: datetime | None = None,
) -> tuple[Candidate, ...]:
    """Normalize one official EDGAR submissions response for an allowlisted CIK."""

    now = discovered_at or datetime.now(UTC)
    cik = str(payload.get("cik") or "").strip().zfill(10)
    company = str(payload.get("name") or cik).strip()
    recent = payload.get("filings", {}).get("recent", {})
    accession_numbers = recent.get("accessionNumber", [])
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    primary_documents = recent.get("primaryDocument", [])
    rows: list[Candidate] = []
    for index, accession in enumerate(accession_numbers):
        if len(rows) >= limit:
            break
        form = str(forms[index] if index < len(forms) else "").strip().upper()
        primary_document = str(
            primary_documents[index] if index < len(primary_documents) else ""
        ).strip()
        accession = str(accession).strip()
        if form not in allowed_forms or not accession or not primary_document or not cik.isdigit():
            continue
        filing_date = parse_datetime(
            filing_dates[index] if index < len(filing_dates) else None
        )
        accession_path = accession.replace("-", "")
        document_path = quote(primary_document, safe="/._-")
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession_path}/{document_path}"
        )
        rows.append(
            Candidate(
                source_key=source_key,
                observed_url=url,
                canonical_url=normalize_url(url),
                external_id=accession,
                headline=f"{company} {form} filing",
                publisher="U.S. Securities and Exchange Commission",
                discovered_at=now,
                published_at=filing_date,
                discovery_method="sec_submissions_api",
                topic="global_markets",
                metadata={
                    "accession_number": accession,
                    "cik": cik,
                    "company": company,
                    "form": form,
                    "summary": f"Official {form} filing by {company}",
                },
            )
        )
    return tuple(rows)


PSX_BASE_URL = "https://dps.psx.com.pk"


def _psx_category(title: str) -> str:
    normalized = title.lower()
    rules = (
        ("financial_results", ("financial result", "accounts for", "quarter ended")),
        ("dividend_payout", ("dividend", "payout")),
        ("bonus_issue", ("bonus issue",)),
        ("rights_issue", ("right issue", "rights issue")),
        ("board_meeting", ("board meeting",)),
        ("material_information", ("material information",)),
        ("management_change", ("director", "chief executive", "management change")),
        ("corporate_action", ("corporate action", "book closure")),
        ("acquisition_disposal", ("acquisition", "disposal")),
        ("contract_project", ("contract", "project")),
        ("regulatory_notice", ("regulation", "notice")),
    )
    return next((category for category, terms in rules if any(term in normalized for term in terms)), "general")


def parse_psx_announcements(content: bytes, *, discovered_at: datetime | None = None) -> tuple[Candidate, ...]:
    """Normalize the observed `/announcements` table response."""

    soup = BeautifulSoup(content, "lxml")
    now = discovered_at or datetime.now(UTC)
    rows: list[Candidate] = []
    for row in soup.select("#announcementsTable tbody tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 6:
            continue
        symbol = cells[2].get_text(" ", strip=True)
        company = cells[3].get_text(" ", strip=True)
        title = cells[4].get_text(" ", strip=True)
        published = parse_datetime(f"{cells[0].get_text(' ', strip=True)} {cells[1].get_text(' ', strip=True)}")
        attachment = cells[5].find("a", href=lambda value: value and value != "javascript:")
        image_link = cells[5].find("a", attrs={"data-images": True})
        attachment_url = None
        attachment_type = None
        if attachment:
            attachment_url = normalize_url(str(attachment["href"]), PSX_BASE_URL)
            attachment_type = "pdf"
        elif image_link:
            attachment_url = normalize_url(f"/download/image/{image_link['data-images']}", PSX_BASE_URL)
            attachment_type = "image"
        id_match = re.search(r"/(\d+)(?:-\d+)?(?:\.[A-Za-z]+)?$", attachment_url or "")
        announcement_id = id_match.group(1) if id_match else hashlib.sha256(
            f"{symbol}|{published}|{title}".encode()
        ).hexdigest()[:20]
        source_url = f"{PSX_BASE_URL}/announcements?id={announcement_id}"
        rows.append(
            Candidate(
                source_key="psx_announcements",
                observed_url=source_url,
                canonical_url=source_url,
                external_id=announcement_id,
                headline=title,
                publisher="Pakistan Stock Exchange",
                discovered_at=now,
                published_at=published,
                discovery_method="psx_announcements_post",
                topic="psx_company",
                metadata={
                    "symbol": symbol,
                    "company": company,
                    "category": _psx_category(title),
                    "attachment_url": attachment_url,
                    "attachment_type": attachment_type,
                },
            )
        )
    return tuple(rows)
