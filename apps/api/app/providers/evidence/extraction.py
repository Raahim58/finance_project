"""Deterministic URL normalization, article extraction, and fingerprints."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.ingestion.evidence import ParsedEvidence, RawContent

TRACKING_QUERY_KEYS = frozenset(
    {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
)
ARTICLE_TYPES = frozenset({"article", "newsarticle", "report", "analysisnewsarticle"})
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%-]*")
NUMBER_RE = re.compile(r"(?<!\w)(?:PKR|USD|Rs\.?|\$)?\s*-?\d[\d,]*(?:\.\d+)?\s*%?", re.I)


def normalize_url(url: str, base_url: str | None = None) -> str:
    """Return a stable HTTP(S) URL without fragments or tracking parameters."""

    resolved = urljoin(base_url or "", url.strip())
    parts = urlsplit(resolved)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"Unsupported evidence URL: {url!r}")
    host = parts.hostname.lower()
    port = parts.port
    netloc = host if port is None else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
        )
    )
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for date_format in ("%Y%m%dT%H%M%SZ", "%b %d, %Y %I:%M %p"):
            try:
                parsed = datetime.strptime(text, date_format).replace(tzinfo=UTC)
                break
            except ValueError:
                continue
    if parsed is None:
        from email.utils import parsedate_to_datetime

        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _json_ld_objects(soup: BeautifulSoup) -> Iterable[Mapping[str, object]]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or script.get_text() or "null")
        except (json.JSONDecodeError, TypeError):
            continue
        queue = payload if isinstance(payload, list) else [payload]
        for value in queue:
            if not isinstance(value, dict):
                continue
            graph = value.get("@graph")
            if isinstance(graph, list):
                yield from (item for item in graph if isinstance(item, dict))
            yield value


def _article_json_ld(soup: BeautifulSoup) -> Mapping[str, object] | None:
    for payload in _json_ld_objects(soup):
        raw_type = payload.get("@type", "")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(str(item).lower() in ARTICLE_TYPES for item in types):
            return payload
    return None


def _author_name(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, list):
        names = [name for item in value if (name := _author_name(item))]
        return ", ".join(names) or None
    text = str(value or "").strip()
    return text or None


def _fallback_body(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "aside", "form", "noscript"]):
        tag.decompose()
    container = soup.find("article") or soup.find("main") or soup.body
    if container is None:
        return ""
    paragraphs = [node.get_text(" ", strip=True) for node in container.find_all("p")]
    substantive = [text for text in paragraphs if len(text.split()) >= 5]
    if substantive:
        return "\n\n".join(substantive)
    return container.get_text(" ", strip=True)


def _simhash(text: str) -> str:
    weights = [0] * 64
    for token in TOKEN_RE.findall(text.lower()):
        bits = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
        for index in range(64):
            weights[index] += 1 if bits & (1 << index) else -1
    value = sum(1 << index for index, weight in enumerate(weights) if weight >= 0)
    return f"{value:016x}"


def extract_article(raw: RawContent) -> ParsedEvidence:
    """Extract JSON-LD first, then a conservative article/main paragraph fallback."""

    html = raw.content.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    payload = _article_json_ld(soup)
    canonical_node = soup.find("link", rel=lambda value: value and "canonical" in value)
    og_url = soup.find("meta", property="og:url")
    canonical_value = (
        (payload or {}).get("url")
        or (canonical_node.get("href") if canonical_node else None)
        or (og_url.get("content") if og_url else None)
        or raw.final_url
    )
    canonical_url = normalize_url(str(canonical_value), raw.final_url)
    headline_node = soup.find("h1")
    title = str((payload or {}).get("headline") or "").strip()
    if not title and headline_node:
        title = headline_node.get_text(" ", strip=True)
    title = title or raw.candidate.headline
    json_body = str((payload or {}).get("articleBody") or "").strip()
    body = json_body or _fallback_body(soup)
    parser_method = "json_ld_article_body" if json_body else "generic_html"
    if not body:
        raise ValueError("Article extraction produced no text")
    published = parse_datetime((payload or {}).get("datePublished")) or raw.candidate.published_at
    digest = hashlib.sha256(body.encode()).hexdigest()
    quality = min(1.0, 0.35 + len(body.split()) / 800)
    if json_body:
        quality = min(1.0, quality + 0.15)
    numbers = tuple(sorted({" ".join(match.group(0).split()) for match in NUMBER_RE.finditer(body)}))
    return ParsedEvidence(
        canonical_url=canonical_url,
        title=title,
        body=body,
        published_at=published,
        source_key=raw.candidate.source_key,
        body_sha256=digest,
        parser_method=parser_method,
        extraction_quality=quality,
        author=_author_name((payload or {}).get("author")),
        language=raw.candidate.language,
        important_number_fingerprints=numbers[:40],
        simhash=_simhash(f"{title}\n{body}"),
        metadata={"content_type": raw.content_type},
    )


def simhash_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
