from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

import httpx
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class MettisArticleMetadata:
    title: str
    url: str
    published_at: datetime | None = None
    summary: str | None = None
    author: str | None = None


class MettisProvider:
    source = "mettis"
    listing_url = "https://mettisglobal.news/latest/"
    parser_version = "mettis-html-metadata-v1"
    enabled = True

    @staticmethod
    def parse_listing(html: str) -> list[MettisArticleMetadata]:
        soup = BeautifulSoup(html, "html.parser")
        rows = []
        seen = set()
        for post in soup.select("div.post.PostList"):
            headline = post.select_one("h4.HeadlineStyle")
            link = headline.find_parent("a", href=True) if headline else None
            if headline is None or link is None:
                continue
            url = str(link["href"])
            if not url.startswith("https://mettisglobal.news/") or url in seen:
                continue
            summary_node = post.select_one("p.ListnewDes")
            summary = summary_node.get_text(" ", strip=True) if summary_node else ""
            rows.append(MettisArticleMetadata(headline.get_text(" ", strip=True), url, summary=summary or None))
            seen.add(url)
        return rows

    @staticmethod
    def parse_article_metadata(html: str, expected_url: str) -> MettisArticleMetadata:
        soup = BeautifulSoup(html, "html.parser")
        payload: dict[str, Any] | None = None
        for script in soup.find_all("script", type="application/ld+json"):
            try: candidate = json.loads(script.string or "{}")
            except json.JSONDecodeError: continue
            if isinstance(candidate, dict) and candidate.get("@type") in {"NewsArticle", "Article"}:
                payload = candidate; break
        if payload is None:
            raise ValueError("Mettis article JSON-LD contract is missing")
        canonical = soup.find("meta", property="og:url")
        url = str(canonical.get("content")) if canonical and canonical.get("content") else expected_url
        if url != expected_url or not url.startswith("https://mettisglobal.news/"):
            raise ValueError("Mettis canonical URL did not match the requested article")
        published = datetime.fromisoformat(str(payload["datePublished"]).replace("Z", "+00:00")) if payload.get("datePublished") else None
        description = str(payload.get("description") or "").strip() or None
        author = payload.get("author")
        if isinstance(author, dict): author = author.get("name")
        return MettisArticleMetadata(str(payload.get("headline") or "").strip(), url, published, description, str(author).strip() if author else None)

    def fetch_listing(self) -> list[MettisArticleMetadata]:
        with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate metadata ingestion)"}) as client:
            response = client.get(self.listing_url); response.raise_for_status()
            return self.parse_listing(response.text)

    def fetch_article_metadata(self, url: str) -> MettisArticleMetadata:
        if not url.startswith("https://mettisglobal.news/"):
            raise ValueError("Only observed Mettis article URLs are allowed")
        with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate metadata ingestion)"}) as client:
            response = client.get(url); response.raise_for_status()
            return self.parse_article_metadata(response.text, url)
