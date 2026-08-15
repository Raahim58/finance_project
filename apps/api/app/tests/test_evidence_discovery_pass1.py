from datetime import UTC, datetime

from app.providers.evidence.discovery import (
    GdeltDiscovery,
    ListingDiscovery,
    RssAtomDiscovery,
    SitemapDiscovery,
    parse_psx_announcements,
)
from app.providers.evidence.extraction import extract_article, normalize_url, simhash_distance
from app.ingestion.evidence import Candidate, RawContent


NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def test_rss_atom_and_url_normalization():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Dawn</title>
    <item><guid>dawn-1</guid><title>Pakistan policy rate update</title>
    <link>https://www.dawn.com/news/123/?utm_source=x&amp;b=2&amp;a=1#top</link>
    <pubDate>Thu, 13 Aug 2026 10:00:00 GMT</pubDate><description>Summary</description></item>
    </channel></rss>"""
    rows = RssAtomDiscovery("dawn", "Dawn", "pakistan_macro").parse(feed, discovered_at=NOW)
    assert len(rows) == 1
    assert rows[0].external_id == "dawn-1"
    assert rows[0].canonical_url == "https://www.dawn.com/news/123?a=1&b=2"
    assert rows[0].published_at == datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    assert normalize_url("/story/?utm_medium=rss", "https://EXAMPLE.com/base") == "https://example.com/story"


def test_news_sitemap_and_listing_discovery():
    sitemap = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
      xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"><url>
      <loc>https://example.com/economy/story</loc><news:news><news:publication_date>2026-08-13T09:00:00Z</news:publication_date>
      <news:title>Pakistan inflation eases</news:title></news:news></url></urlset>"""
    rows = SitemapDiscovery("example", "Example", "pakistan_macro").parse(sitemap, discovered_at=NOW)
    assert rows[0].headline == "Pakistan inflation eases"
    assert rows[0].discovery_method == "news_sitemap"

    html = b'<a href="/assets/documents/press-release/one.pdf">Policy decision</a><a href="/about">About</a>'
    listing = ListingDiscovery("sbp", "SBP", "https://www.sbp.org.pk/media-center/", r"/assets/documents/press-release/")
    assert [row.headline for row in listing.parse(html, discovered_at=NOW)] == ["Policy decision"]


def test_gdelt_response_normalization_and_request_bound():
    payload = {"articles": [{"url": "https://wire.example/story", "title": "Oil shipping risk", "seendate": "20260813T103000Z", "domain": "wire.example", "language": "English", "sourcecountry": "United States"}]}
    row = GdeltDiscovery(topic="geopolitics").parse(payload, discovered_at=NOW)[0]
    assert row.publisher == "wire.example"
    assert row.published_at == datetime(2026, 8, 13, 10, 30, tzinfo=UTC)
    assert GdeltDiscovery.request_params("oil", 999)["maxrecords"] == 250


def test_psx_announcement_normalization_from_observed_table_contract():
    html = b"""<table id="announcementsTable"><tbody><tr>
    <td>Aug 13, 2026</td><td>3:41 PM</td><td><a href="/company/AHL"><strong>AHL</strong></a></td>
    <td><a href="/company/AHL"><strong>Arif Habib Limited</strong></a></td>
    <td>AHL | Arif Habib Limited Board Meeting</td>
    <td><a href="/download/attachment/281173-1.pdf">PDF</a></td></tr></tbody></table>"""
    row = parse_psx_announcements(html, discovered_at=NOW)[0]
    assert row.external_id == "281173"
    assert row.metadata["symbol"] == "AHL"
    assert row.metadata["category"] == "board_meeting"
    assert row.metadata["attachment_url"] == "https://dps.psx.com.pk/download/attachment/281173-1.pdf"
    assert row.published_at == datetime(2026, 8, 13, 15, 41, tzinfo=UTC)


def test_json_ld_then_generic_html_extraction_and_fingerprints():
    candidate = Candidate("dawn", "https://example.com/story", "Fallback", "Dawn", NOW, "rss", topic="pakistan_macro")
    json_ld = b'''<html><head><link rel="canonical" href="https://example.com/story?utm_source=x">
    <script type="application/ld+json">{"@type":"NewsArticle","headline":"SBP holds policy rate","datePublished":"2026-08-13T10:00:00Z","author":{"name":"Reporter"},"articleBody":"Pakistan's policy rate remains 11 percent while reserves improve."}</script></head></html>'''
    parsed = extract_article(RawContent(candidate, json_ld, "text/html", NOW, candidate.observed_url))
    assert parsed.parser_method == "json_ld_article_body"
    assert parsed.author == "Reporter"
    assert parsed.canonical_url == "https://example.com/story"
    assert parsed.simhash and parsed.body_sha256

    generic = b"<html><main><h1>Oil update</h1><p>Shipping markets face material disruption in the Red Sea corridor today.</p><p>Oil prices responded as carriers changed routes.</p></main></html>"
    fallback = extract_article(RawContent(candidate, generic, "text/html", NOW, candidate.observed_url))
    assert fallback.parser_method == "generic_html"
    assert "changed routes" in fallback.body
    assert simhash_distance(fallback.simhash, fallback.simhash) == 0
