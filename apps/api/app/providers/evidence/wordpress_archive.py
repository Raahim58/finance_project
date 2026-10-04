"""Bounded dated archives for the two publisher APIs verified from Oracle."""

import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

from app.ingestion.evidence import Candidate, DiscoveryBatch
from app.providers.evidence.sources import HttpEvidenceSource


ARCHIVES = {
    "gcaptain": ("gCaptain", "https://gcaptain.com"),
    "freightwaves": ("FreightWaves", "https://www.freightwaves.com"),
}


class WordPressArchiveSource(HttpEvidenceSource):
    def __init__(self, key, **kwargs):
        name, base = ARCHIVES[key]
        super().__init__(key, name, base + "/wp-json/wp/v2/posts", "wordpress_archive", "commodities", **kwargs)

    def discover_since(self, cursor, limit):
        cursor = dict(cursor or {})
        start = date.fromisoformat(cursor["date_from"])
        end = date.fromisoformat(cursor["date_to"])
        if start > end or (end - start).days > 7:
            raise ValueError("Archive slices require a dated window of at most seven days")
        count = min(max(limit, 1), 50)
        offset = max(0, int(cursor.get("offset", 0)))
        # Publisher filtering uses its local publication clock; overlap its
        # boundary, then enforce the requested dates using observed date_gmt.
        params = {"after": (start - timedelta(days=1)).isoformat() + "T00:00:00",
                  "before": (end + timedelta(days=2)).isoformat() + "T00:00:00",
                  "per_page": count, "offset": offset, "orderby": "date", "order": "asc",
                  "_fields": "id,date_gmt,link,title,excerpt,status"}
        content, final_url, _, headers = self.fetcher(self.discovery_url, params=params)
        payload = json.loads(content)
        if not isinstance(payload, list):
            raise ValueError("Publisher archive response must be a post list")
        candidates = []
        now = datetime.now(UTC)
        for row in payload:
            if urlsplit(row["link"]).hostname.removeprefix("www.") != urlsplit(self.discovery_url).hostname.removeprefix("www."):
                raise ValueError("Publisher archive returned a foreign article host")
            published = datetime.fromisoformat(row["date_gmt"].replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            published = published.astimezone(UTC)
            if not start <= published.date() <= end:
                continue
            title = BeautifulSoup(row["title"]["rendered"], "html.parser").get_text(" ", strip=True)
            summary = BeautifulSoup(row.get("excerpt", {}).get("rendered", ""), "html.parser").get_text(" ", strip=True)
            candidates.append(Candidate(source_key=self.key, observed_url=row["link"], canonical_url=row["link"],
                external_id=f"wordpress:{row['id']}", headline=title, publisher=self.publisher,
                discovered_at=now, published_at=published, discovery_method="publisher_dated_archive",
                topic=self.topic, metadata={"summary": summary[:2000], "archive_url": final_url,
                    "archive_date_from": start.isoformat(), "archive_date_to": end.isoformat()}))
        total = next((int(v) for k, v in headers.items() if k.lower() == "x-wp-total"), None)
        exhausted = offset + len(payload) >= total if total is not None else len(payload) < count
        return DiscoveryBatch(tuple(candidates), {"offset": offset + len(payload), "exhausted": exhausted})
