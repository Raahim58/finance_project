"""Public dated publisher listings; article fetch/extraction reuse existing adapters."""

import re
from datetime import UTC, date, datetime
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.ingestion.evidence import Candidate, DiscoveryBatch
from app.providers.evidence.sources import HttpEvidenceSource

DATED_ARCHIVES = ("dawn", "guardian_world")


class DatedArchiveSource(HttpEvidenceSource):
    def __init__(self, key, **kwargs):
        if key not in DATED_ARCHIVES:
            raise ValueError("Unsupported dated publisher")
        name, base, topic = ("Dawn", "https://www.dawn.com", "pakistan") if key == "dawn" else (
            "The Guardian World", "https://www.theguardian.com", "geopolitics")
        super().__init__(key, name, base, "dated_archive", topic, **kwargs)

    def discover_since(self, cursor, limit):
        cursor = dict(cursor or {})
        day = date.fromisoformat(cursor["date_from"])
        if cursor.get("date_to", day.isoformat()) != day.isoformat():
            raise ValueError("Dated publisher slices must cover exactly one day")
        offset = int(cursor.get("offset", 0))
        if offset < 0 or not 1 <= limit <= 250:
            raise ValueError("Invalid dated archive offset or limit")
        suffix = f"/latest-news/{day.isoformat()}" if self.key == "dawn" else f"/world/{day.year}/{day.strftime('%b').lower()}/{day.day:02d}/all"
        url = self.discovery_url + suffix
        content, final_url, content_type, _ = self.fetcher(url)
        if "html" not in content_type.lower() or urlsplit(final_url).hostname != urlsplit(url).hostname:
            raise ValueError("Dated archive returned an unexpected content type or host")
        soup = BeautifulSoup(content, "lxml")
        candidates, seen = [], set()
        if self.key == "dawn":
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            if day.isoformat() not in title or "Archives" not in title:
                raise ValueError("Dawn archive date/title contract changed")
            for article in soup.select("article.story"):
                anchor = article.select_one("h2 a.story__link")
                timestamp = article.select_one("[datetime]")
                if not anchor or not timestamp:
                    continue
                published = datetime.fromisoformat(timestamp["datetime"])
                if published.tzinfo is None or published.astimezone(ZoneInfo("Asia/Karachi")).date() != day:
                    continue
                category = article.select_one(".badge")
                excerpt = article.select_one(".story__excerpt")
                candidates.append((anchor, published.astimezone(UTC), {
                    "category": category.get_text(" ", strip=True) if category else "",
                    "summary": excerpt.get_text(" ", strip=True) if excerpt else "",
                }))
        else:
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            if "World" not in title or "Guardian" not in title:
                raise ValueError("Guardian archive title contract changed")
            # URL supplies a date, not a publication timestamp. Article extraction
            # must supply the latter; never manufacture midnight as observed time.
            pattern = re.compile(rf"/world/(?:video/)?{day.year}/{day.strftime('%b').lower()}/{day.day:02d}/[^/]+")
            for anchor in soup.select("a[data-link-name='article']"):
                if pattern.search(anchor.get("href", "")):
                    candidates.append((anchor, None, {}))
        rows = []
        now = datetime.now(UTC)
        for anchor, published, metadata in candidates:
            canonical = urljoin(url, anchor.get("href", ""))
            if urlsplit(canonical).hostname != urlsplit(url).hostname:
                # Dawn legitimately mixes Images/Urdu sister-site stories into
                # its archive. They are not this adapter's article contract.
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            headline = anchor.get_text(" ", strip=True)
            if not headline:
                continue
            rows.append(Candidate(self.key, canonical, headline, self.publisher, now,
                "publisher_dated_archive", canonical_url=canonical, external_id=canonical,
                published_at=published, topic=self.topic,
                metadata={**metadata, "archive_url": final_url, "archive_date": day.isoformat()}))
        if not rows:
            raise ValueError("Dated archive contained no dated articles; coverage is unverified")
        return DiscoveryBatch(tuple(rows[offset:offset + limit]), {
            "offset": min(offset + limit, len(rows)), "exhausted": offset + limit >= len(rows)})
