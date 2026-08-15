"""Concrete synchronous Pass 1 evidence sources.

Scheduling, retries, and queue isolation belong to Pass 2. These sources are
small enough to run manually or under fixture tests without import-time I/O.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from app.ingestion.evidence import Candidate, DiscoveryBatch, ParsedEvidence, RawContent
from app.providers.evidence.discovery import (
    GdeltDiscovery,
    ListingDiscovery,
    RssAtomDiscovery,
    SitemapDiscovery,
    parse_psx_announcements,
)
from app.providers.evidence.extraction import extract_article
from app.providers.news.mettis import MettisProvider

USER_AGENT = "psx-ai-portfolio-agent/0.1 (bounded evidence ingestion)"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
HIGH_VALUE_PSX_CATEGORIES = frozenset(
    {
        "financial_results",
        "dividend_payout",
        "bonus_issue",
        "rights_issue",
        "material_information",
        "corporate_action",
        "acquisition_disposal",
        "contract_project",
        "regulatory_notice",
    }
)


class Fetcher(Protocol):
    def __call__(
        self,
        url: str,
        *,
        method: str = "GET",
        data: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> tuple[bytes, str, str, Mapping[str, str]]: ...


def bounded_http_fetch(
    url: str,
    *,
    method: str = "GET",
    data: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
) -> tuple[bytes, str, str, Mapping[str, str]]:
    """Fetch one URL with bounded streaming and validated redirect targets."""

    import ipaddress

    def validate(target: str) -> None:
        parts = urlsplit(target)
        host = parts.hostname
        if not host or parts.scheme not in {"http", "https"}:
            raise ValueError("Evidence fetch requires an HTTP(S) URL")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and (address.is_private or address.is_loopback or address.is_link_local):
            raise ValueError("Private-network evidence URLs are not allowed")

    current_url = url
    current_method = method.upper()
    current_data = data
    current_params = params
    with httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(6):
            validate(current_url)
            with client.stream(
                current_method,
                current_url,
                data=current_data,
                params=current_params,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Evidence redirect had no Location header")
                    current_url = urljoin(str(response.url), location)
                    if response.status_code == 303 or (
                        response.status_code in {301, 302} and current_method == "POST"
                    ):
                        current_method = "GET"
                        current_data = None
                    current_params = None
                    continue
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise ValueError("Evidence response exceeded the Pass 1 size limit")
                return (
                    bytes(content),
                    str(response.url),
                    response.headers.get("content-type", "application/octet-stream"),
                    dict(response.headers),
                )
        raise ValueError("Evidence response exceeded the redirect limit")


@dataclass
class HttpEvidenceSource:
    key: str
    publisher: str
    discovery_url: str
    discovery_kind: str
    topic: str | None = None
    query: str | None = None
    link_pattern: str | None = None
    fetcher: Fetcher = bounded_http_fetch

    def discover_since(self, cursor: Mapping[str, Any] | None, limit: int) -> DiscoveryBatch:
        params = None
        if self.discovery_kind == "gdelt":
            if not self.query:
                raise ValueError("GDELT sources require a bounded query")
            params = GdeltDiscovery.request_params(self.query, limit)
            historical_days = int((cursor or {}).get("historical_days", 0))
            if historical_days:
                params["timespan"] = f"{min(historical_days, 90)}d"
            if (cursor or {}).get("date_from") and (cursor or {}).get("date_to"):
                start = datetime.fromisoformat(str(cursor["date_from"]))
                end = datetime.fromisoformat(str(cursor["date_to"]))
                if (end - start).days > 90:
                    start = end - timedelta(days=90)
                params.pop("timespan", None)
                params["startdatetime"] = start.strftime("%Y%m%d000000")
                params["enddatetime"] = end.strftime("%Y%m%d235959")
        content, _, _, _ = self.fetcher(self.discovery_url, params=params)
        if self.discovery_kind == "rss":
            candidates = RssAtomDiscovery(self.key, self.publisher, self.topic).parse(content)
        elif self.discovery_kind == "sitemap":
            candidates = SitemapDiscovery(self.key, self.publisher, self.topic).parse(content)
        elif self.discovery_kind == "gdelt":
            candidates = GdeltDiscovery(self.key, self.publisher, self.topic).parse(json.loads(content))
            candidates = tuple(
                Candidate(
                    **{
                        **candidate.__dict__,
                        "metadata": {**dict(candidate.metadata), "query": self.query},
                    }
                )
                for candidate in candidates
            )
        elif self.discovery_kind == "listing":
            if not self.link_pattern:
                raise ValueError("Listing sources require a link pattern")
            candidates = ListingDiscovery(
                self.key, self.publisher, self.discovery_url, self.link_pattern, self.topic
            ).parse(content)
        elif self.discovery_kind == "mettis":
            now = datetime.now(UTC)
            candidates = tuple(
                Candidate(
                    source_key=self.key,
                    observed_url=item.url,
                    canonical_url=item.url,
                    external_id=item.url,
                    headline=item.title,
                    publisher=self.publisher,
                    discovered_at=now,
                    published_at=item.published_at,
                    discovery_method="publisher_listing",
                    topic=self.topic,
                    metadata={"summary": item.summary, "author": item.author},
                )
                for item in MettisProvider.parse_listing(
                    content.decode("utf-8", errors="replace")
                )
            )
        else:
            raise ValueError(f"Unknown discovery kind {self.discovery_kind!r}")
        return DiscoveryBatch(candidates[:limit], {"last_discovered_at": datetime.now(UTC).isoformat()})

    def fetch(self, candidate: Candidate) -> RawContent:
        content, final_url, content_type, headers = self.fetcher(candidate.observed_url)
        return RawContent(candidate, content, content_type, datetime.now(UTC), final_url, headers)

    def normalize(self, raw: RawContent) -> ParsedEvidence:
        return extract_article(raw)


@dataclass
class PsxAnnouncementSource:
    key: str = "psx_announcements"
    publisher: str = "Pakistan Stock Exchange"
    discovery_url: str = "https://dps.psx.com.pk/announcements"
    fetcher: Fetcher = bounded_http_fetch

    def discover_since(self, cursor: Mapping[str, Any] | None, limit: int) -> DiscoveryBatch:
        values = dict(cursor or {})
        offset = max(0, int(values.get("offset", 0)))
        count = min(max(limit, 1), 50)
        data = {
            "type": "C",
            "symbol": str(values.get("symbol") or ""),
            "query": "",
            "count": count,
            "offset": offset,
            "date_from": str(values.get("date_from") or ""),
            "date_to": str(values.get("date_to") or ""),
            "page": "annc",
        }
        content, _, _, _ = self.fetcher(self.discovery_url, method="POST", data=data)
        candidates = parse_psx_announcements(content)
        return DiscoveryBatch(candidates[:limit], {"offset": offset + len(candidates)})

    def fetch(self, candidate: Candidate) -> RawContent:
        attachment_url = candidate.metadata.get("attachment_url")
        if attachment_url and candidate.metadata.get("category") in HIGH_VALUE_PSX_CATEGORIES:
            content, final_url, content_type, headers = self.fetcher(str(attachment_url))
        else:
            content = json.dumps(dict(candidate.metadata), sort_keys=True).encode()
            final_url = candidate.observed_url
            content_type = "application/json"
            headers = {"x-evidence-fetch": "metadata-only"}
        return RawContent(candidate, content, content_type, datetime.now(UTC), final_url, headers)

    def normalize(self, raw: RawContent) -> ParsedEvidence:
        """Normalize metadata; high-value PDF extraction is delegated to the existing PDF path."""

        import hashlib

        metadata = dict(raw.candidate.metadata)
        body = "\n".join(
            value
            for value in (
                raw.candidate.headline,
                f"Company: {metadata.get('company')}" if metadata.get("company") else "",
                f"Symbol: {metadata.get('symbol')}" if metadata.get("symbol") else "",
                f"Category: {metadata.get('category')}" if metadata.get("category") else "",
            )
            if value
        )
        return ParsedEvidence(
            canonical_url=raw.candidate.canonical_url or raw.candidate.observed_url,
            title=raw.candidate.headline,
            body=body,
            published_at=raw.candidate.published_at,
            source_key=self.key,
            body_sha256=hashlib.sha256(body.encode()).hexdigest(),
            parser_method="psx_announcement_metadata_v1",
            extraction_quality=1.0,
            entity_keys=(str(metadata["symbol"]),) if metadata.get("symbol") else (),
            metadata={**metadata, "retrieved_content_type": raw.content_type},
        )
