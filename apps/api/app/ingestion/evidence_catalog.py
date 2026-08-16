"""Pass 1 source and topic configuration; construction performs no network I/O."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.ingestion.evidence import EvidenceSourceRegistry
from app.providers.evidence.sources import HttpEvidenceSource, PsxAnnouncementSource, SecEdgarSource


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
    discovery_url: str | None = None
    topic: str | None = None
    link_pattern: str | None = None
    canary_group: str | None = None
    daily_discovery_budget: int = 100
    daily_fetch_budget: int = 15
    daily_selected_budget: int = 5
    daily_storage_budget_bytes: int = 100 * 1024 * 1024
    fallback: str = "retry_with_circuit_then_manual_review"


SOURCE_SPECS = (
    SourceSpec("psx_announcements", "PSX Announcements", "https://dps.psx.com.pk", "official", ("primary",), ("psx_company",), "psx_post", 120, 1825),
    SourceSpec("dawn", "Dawn", "https://www.dawn.com", "reporting", ("reporting",), ("pakistan_macro", "politics"), "rss", 300, 548, discovery_url="https://www.dawn.com/feeds/home", topic="pakistan"),
    SourceSpec("business_recorder", "Business Recorder", "https://www.brecorder.com", "reporting", ("reporting",), ("pakistan_macro", "markets"), "rss", 300, 548, discovery_url="https://www.brecorder.com/feeds/latest-news", topic="pakistan"),
    SourceSpec("mettis", "Mettis Global Evidence", "https://mettisglobal.news", "specialist", ("reporting",), ("pakistan_macro", "markets"), "mettis", 300, 548, False, discovery_url="https://mettisglobal.news/latest/", topic="pakistan_markets"),
    SourceSpec("sbp_releases", "State Bank of Pakistan", "https://www.sbp.org.pk", "official", ("primary",), ("pakistan_macro", "monetary_policy"), "listing", 300, 1825, discovery_url="https://www.sbp.org.pk/media-center/", topic="pakistan_macro", link_pattern=r"^https://(?:www\.)?sbp\.org\.pk/(?:assets|press|media-center)/"),
    SourceSpec("imf_news", "International Monetary Fund", "https://www.imf.org", "official", ("primary",), ("pakistan_macro", "global_macro"), "listing", 600, 1825, False, discovery_url="https://www.imf.org/en/news", topic="global_macro", link_pattern=r"^https://www\.imf\.org/en/news/(?:articles|press-releases|speech)/", fallback="disabled after repeated HTTP 403; use an official feed/API if verified"),
    SourceSpec("gdelt", "GDELT DOC 2", "https://api.gdeltproject.org", "discovery", ("discovery",), ("global",), "gdelt", 900, 90, False, discovery_url="https://api.gdeltproject.org/api/v2/doc/doc", topic="pakistan_macro", fallback="disabled after sustained HTTP 429 throttling; preserve existing corpus"),

    # Pass 4 official-source canary. These remain disabled until
    # EVIDENCE_PASS4_OFFICIAL_ENABLED=true is explicitly set.
    SourceSpec("mof_pakistan", "Pakistan Ministry of Finance", "https://www.finance.gov.pk", "official", ("primary",), ("pakistan_macro", "fiscal_policy"), "listing", 1800, 365, settings.evidence_pass4_official_enabled, "https://www.finance.gov.pk/updates.html", "pakistan_macro", r"^https://(?:www\.)?finance\.gov\.pk/.+\.(?:pdf|html?)$", "pass4_official", 50, 20, 8, 100 * 1024 * 1024, "secondary listing: budget_wing.html; then manual review"),
    SourceSpec("pbs_releases", "Pakistan Bureau of Statistics", "https://www.pbs.gov.pk", "official", ("primary",), ("pakistan_macro", "official_statistics"), "listing", 1800, 365, settings.evidence_pass4_official_enabled, "https://www.pbs.gov.pk/press-release/", "pakistan_macro", r"^https://(?:www\.)?pbs\.gov\.pk/(?:press-release|wp-content/uploads|sites/default/files)/", "pass4_official", 50, 20, 8, 150 * 1024 * 1024, "secondary listing: category/whats-new; then manual review"),
    SourceSpec("secp_releases", "Securities and Exchange Commission of Pakistan", "https://www.secp.gov.pk", "official", ("primary",), ("pakistan_markets", "regulation"), "listing", 1800, 365, settings.evidence_pass4_official_enabled, "https://www.secp.gov.pk/media-center/press-releases/", "pakistan_markets", r"^https://(?:www\.)?secp\.gov\.pk/(?:media-center|wp-content/uploads)/", "pass4_official", 75, 25, 10, 200 * 1024 * 1024, "secondary listing by current year; then manual review"),
    SourceSpec("nepra_releases", "National Electric Power Regulatory Authority", "https://nepra.org.pk", "official", ("primary",), ("pakistan_macro", "energy_regulation"), "listing", 3600, 365, settings.evidence_pass4_official_enabled, "https://www.nepra.org.pk/news.php", "pakistan_macro", r"^https://(?:www\.)?nepra\.org\.pk/(?:Press(?:%20| )Release|Admission(?:%20| )Notices|tariff|M%26E)/.+\.(?:pdf|jpe?g)$", "pass4_official", 40, 15, 6, 100 * 1024 * 1024, "official home/news archive; then manual review"),
    SourceSpec("ogra_releases", "Oil and Gas Regulatory Authority", "https://www.ogra.org.pk", "official", ("primary",), ("pakistan_macro", "energy_regulation"), "listing", 3600, 365, settings.evidence_pass4_official_enabled, "https://www.ogra.org.pk/press-releases-2", "pakistan_macro", r"^https://(?:www\.)?ogra\.org\.pk/(?:download|press-release).+", "pass4_official", 40, 15, 6, 100 * 1024 * 1024, "secondary listing: media-pr; then manual review"),
    SourceSpec("nccpl_notices", "National Clearing Company of Pakistan", "https://www.nccpl.com.pk", "official", ("primary",), ("pakistan_markets", "clearing_regulation"), "listing", 3600, 365, False, "https://www.nccpl.com.pk/legal-framework", "pakistan_markets", r"^https://(?:www\.)?nccpl\.com\.pk/(?:storage|legal-framework).+", "pass4_official", 30, 12, 5, 75 * 1024 * 1024, "disabled after verified HTTP 403; use bounded manual CSV/import"),
    SourceSpec("world_bank_news", "World Bank", "https://www.worldbank.org", "official", ("primary",), ("global_macro", "development"), "listing", 1800, 365, settings.evidence_pass4_official_enabled, "https://www.worldbank.org/en/news/all", "global_macro", r"^https://www\.worldbank\.org/en/news/(?:press-release|statement|feature)/", "pass4_official", 50, 15, 6, 100 * 1024 * 1024, "retry listing; then manual review"),
    SourceSpec("federal_reserve", "Federal Reserve Board", "https://www.federalreserve.gov", "official", ("primary",), ("global_macro", "monetary_policy"), "rss", 900, 365, settings.evidence_pass4_official_enabled, "https://www.federalreserve.gov/feeds/press_all.xml", "global_macro", None, "pass4_official", 50, 15, 6, 75 * 1024 * 1024, "official press-release listing"),
    SourceSpec("ecb_releases", "European Central Bank", "https://www.ecb.europa.eu", "official", ("primary",), ("global_macro", "monetary_policy"), "rss", 900, 365, settings.evidence_pass4_official_enabled, "https://www.ecb.europa.eu/rss/press.html", "global_macro", None, "pass4_official", 50, 15, 6, 75 * 1024 * 1024, "official press-release listing"),
    SourceSpec("bis_releases", "Bank for International Settlements", "https://www.bis.org", "official", ("primary",), ("global_macro", "financial_stability"), "rss", 1800, 365, settings.evidence_pass4_official_enabled, "https://www.bis.org/doclist/all_pressrels.rss", "global_macro", None, "pass4_official", 40, 12, 5, 75 * 1024 * 1024, "official media-centre listing"),
    SourceSpec("eia_releases", "U.S. Energy Information Administration", "https://www.eia.gov", "official", ("primary",), ("global_macro", "energy"), "rss", 1800, 365, settings.evidence_pass4_official_enabled, "https://www.eia.gov/rss/press_rss.xml", "global_macro", None, "pass4_official", 40, 12, 5, 75 * 1024 * 1024, "official press-room listing"),
    SourceSpec("opec_releases", "Organization of the Petroleum Exporting Countries", "https://www.opec.org", "official", ("primary",), ("global_macro", "energy"), "listing", 1800, 365, settings.evidence_pass4_official_enabled, "https://www.opec.org/press-releases.html", "global_macro", r"^https://www\.opec\.org/pr-detail/.+", "pass4_official", 40, 12, 5, 75 * 1024 * 1024, "official news listing; then manual review"),
    SourceSpec("sec_edgar_current", "SEC EDGAR Selected Issuers", "https://data.sec.gov", "official", ("primary",), ("global_markets", "regulation"), "sec_submissions", 900, 365, settings.evidence_pass4_official_enabled and bool(settings.evidence_sec_edgar_ciks.strip()), "https://data.sec.gov/submissions/", "global_markets", None, "pass4_official", 100, 20, 6, 150 * 1024 * 1024, "requires an explicit EVIDENCE_SEC_EDGAR_CIKS allowlist"),
    SourceSpec("ofac_actions", "U.S. Treasury OFAC", "https://ofac.treasury.gov", "official", ("primary",), ("geopolitics", "sanctions"), "listing", 1800, 365, settings.evidence_pass4_official_enabled, "https://ofac.treasury.gov/recent-actions", "geopolitics", r"^https://ofac\.treasury\.gov/recent-actions/.+", "pass4_official", 50, 15, 6, 75 * 1024 * 1024, "official sanctions-program pages; then manual review"),
)


TOPIC_QUERIES = {
    # DOC 2.0 permits one parenthesized OR block but does not support nested
    # Boolean blocks. Adjacent terms are conjunctive, so keep Pakistan outside.
    "pakistan_macro": 'Pakistan (IMF OR inflation OR budget OR tax OR reserves OR "policy rate" OR "current account" OR "USD PKR")',
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
    for spec in SOURCE_SPECS:
        if spec.key == "psx_announcements":
            continue
        if spec.key == "sec_edgar_current":
            ciks = tuple(
                dict.fromkeys(
                    item.strip().zfill(10)
                    for item in settings.evidence_sec_edgar_ciks.split(",")
                    if item.strip()
                )
            )
            if any(not cik.isdigit() or len(cik) != 10 for cik in ciks):
                raise ValueError("EVIDENCE_SEC_EDGAR_CIKS must contain comma-separated numeric CIKs")
            registry.register(SecEdgarSource(ciks=ciks, key=spec.key))
            continue
        if not spec.discovery_url:
            raise ValueError(f"Evidence source {spec.key} has no discovery URL")
        registry.register(
            HttpEvidenceSource(
                spec.key,
                spec.name,
                spec.discovery_url,
                spec.discovery_method,
                spec.topic,
                query=TOPIC_QUERIES["pakistan_macro"] if spec.key == "gdelt" else None,
                link_pattern=spec.link_pattern,
            )
        )
    return registry
