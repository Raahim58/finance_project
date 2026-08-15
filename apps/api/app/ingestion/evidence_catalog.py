"""Pass 1 source and topic configuration; construction performs no network I/O."""

from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.evidence import EvidenceSourceRegistry
from app.providers.evidence.sources import HttpEvidenceSource, PsxAnnouncementSource


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    base_url: str
    tier: str
    roles: tuple[str, ...]
    categories: tuple[str, ...]
    discovery_method: str
    poll_seconds: int
    historical_days: int | None
    enabled: bool = True


SOURCE_SPECS = (
    SourceSpec("psx_announcements", "PSX Announcements", "https://dps.psx.com.pk", "official", ("primary",), ("psx_company",), "psx_post", 120, 1825),
    SourceSpec("dawn", "Dawn", "https://www.dawn.com", "reporting", ("reporting",), ("pakistan_macro", "politics"), "rss", 300, 548),
    SourceSpec("business_recorder", "Business Recorder", "https://www.brecorder.com", "reporting", ("reporting",), ("pakistan_macro", "markets"), "rss", 300, 548),
    SourceSpec("mettis", "Mettis Global", "https://mettisglobal.news", "specialist", ("reporting",), ("pakistan_macro", "markets"), "listing", 300, 548),
    SourceSpec("sbp_releases", "State Bank of Pakistan", "https://www.sbp.org.pk", "official", ("primary",), ("pakistan_macro", "monetary_policy"), "listing", 300, 1825),
    SourceSpec("imf_news", "International Monetary Fund", "https://www.imf.org", "official", ("primary",), ("pakistan_macro", "global_macro"), "listing", 600, 1825),
    SourceSpec("gdelt", "GDELT DOC 2", "https://api.gdeltproject.org", "discovery", ("discovery",), ("global",), "gdelt", 900, 90),
)


TOPIC_QUERIES = {
    "pakistan_macro": '(Pakistan AND (IMF OR inflation OR budget OR tax OR reserves OR "policy rate" OR "current account" OR "USD PKR"))',
    "geopolitics": '(sanctions OR war OR conflict OR "Red Sea" OR "shipping disruption" OR "trade war")',
    "commodities": '(oil OR LNG OR gas OR coal OR cotton OR steel OR fertilizer OR urea OR "palm oil" OR lithium OR copper)',
    "technology": '(semiconductor OR DRAM OR NAND OR "AI chips" OR "cloud capex" OR "chip equipment")',
}


SECTOR_DRIVERS = {
    "textile": ("cotton", "usd/pkr", "electricity tariff", "gas tariff", "freight", "export policy"),
    "automobile": ("steel", "pkr", "lithium", "battery prices", "auto financing", "ev policy", "import tariff"),
    "technology": ("semiconductor", "dram", "nand", "ai capex", "cloud spending", "usd/pkr", "it exports"),
    "exploration & production": ("brent", "lng", "pkr", "opec", "middle east", "exploration discovery"),
    "commercial banks": ("policy rate", "kibor", "inflation", "government borrowing", "fx", "npl"),
}


def build_pass1_registry() -> EvidenceSourceRegistry:
    registry = EvidenceSourceRegistry()
    registry.register(PsxAnnouncementSource())
    registry.register(HttpEvidenceSource("dawn", "Dawn", "https://www.dawn.com/feeds/home", "rss", "pakistan"))
    registry.register(HttpEvidenceSource("business_recorder", "Business Recorder", "https://www.brecorder.com/feeds/latest-news", "rss", "pakistan"))
    registry.register(HttpEvidenceSource("mettis", "Mettis Global", "https://mettisglobal.news/latest/", "mettis", "pakistan_markets"))
    registry.register(HttpEvidenceSource("sbp_releases", "State Bank of Pakistan", "https://www.sbp.org.pk/media-center/", "listing", "pakistan_macro", link_pattern=r"^https://(?:www\.)?sbp\.org\.pk/(?:assets|press|media-center)/"))
    registry.register(HttpEvidenceSource("imf_news", "International Monetary Fund", "https://www.imf.org/en/news", "listing", "global_macro", link_pattern=r"^https://www\.imf\.org/en/news/(?:articles|press-releases|speech)/"))
    registry.register(HttpEvidenceSource("gdelt", "GDELT DOC 2", "https://api.gdeltproject.org/api/v2/doc/doc", "gdelt", "pakistan_macro", query=TOPIC_QUERIES["pakistan_macro"]))
    return registry
