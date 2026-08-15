"""Network-light evidence discovery and article normalization adapters."""

from app.providers.evidence.discovery import (
    GdeltDiscovery,
    ListingDiscovery,
    RssAtomDiscovery,
    SitemapDiscovery,
    parse_psx_announcements,
)
from app.providers.evidence.extraction import extract_article, normalize_url
from app.providers.evidence.sources import HttpEvidenceSource, PsxAnnouncementSource

__all__ = [
    "GdeltDiscovery",
    "HttpEvidenceSource",
    "ListingDiscovery",
    "PsxAnnouncementSource",
    "RssAtomDiscovery",
    "SitemapDiscovery",
    "extract_article",
    "normalize_url",
    "parse_psx_announcements",
]
