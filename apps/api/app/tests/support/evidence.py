"""Offline evidence contracts and fixtures."""

from datetime import UTC, datetime
import hashlib
from app.ingestion.evidence import Candidate, DiscoveryBatch, ParsedEvidence, RawContent


class FixtureDawnSource:
    key = "dawn"
    now = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)

    def discover_since(self, cursor, limit):
        del cursor
        item = Candidate(
            source_key=self.key,
            observed_url="https://www.dawn.com/news/pass1",
            canonical_url="https://www.dawn.com/news/pass1",
            external_id="pass1-dawn-1",
            headline="Pakistan inflation and policy rate outlook",
            publisher="Dawn",
            discovered_at=self.now,
            published_at=self.now,
            discovery_method="rss_atom",
            topic="pakistan_macro",
        )
        return DiscoveryBatch((item,)[:limit], {"last_id": "pass1-dawn-1"})

    def fetch(self, candidate):
        html = b"""<html><head><script type="application/ld+json">{"@type":"NewsArticle","headline":"Pakistan inflation and policy rate outlook","datePublished":"2026-08-13T10:00:00Z","articleBody":"Pakistan inflation and the SBP policy rate remain central to the economic outlook. This narrative evidence does not create a structured numerical observation."}</script></head></html>"""
        return RawContent(candidate, html, "text/html", self.now, candidate.observed_url)

    def normalize(self, raw):
        from app.providers.evidence.extraction import extract_article

        return extract_article(raw)


class DuplicateDawnSource(FixtureDawnSource):
    def discover_since(self, cursor, limit):
        del cursor
        items = tuple(
            Candidate(
                source_key=self.key,
                observed_url=f"https://www.dawn.com/news/{suffix}",
                external_id=f"duplicate-{suffix}",
                headline="Pakistan inflation and policy rate outlook",
                publisher="Dawn",
                discovered_at=self.now,
                published_at=self.now,
                discovery_method="rss_atom",
                topic="pakistan_macro",
            )
            for suffix in ("a", "b")
        )
        return DiscoveryBatch(items[:limit], {})


class ClusteredDawnSource(DuplicateDawnSource):
    def normalize(self, raw):
        suffix = raw.candidate.observed_url.rsplit("/", 1)[-1]
        body = (
            "Pakistan inflation policy rate coverage with central bank context and monetary transmission."
            if suffix == "a"
            else "Pakistan budget tax revenue outlook with fiscal accounts and government financing details."
        )
        return ParsedEvidence(
            canonical_url=raw.candidate.observed_url,
            title=raw.candidate.headline,
            body=body,
            published_at=raw.candidate.published_at,
            source_key=self.key,
            body_sha256=hashlib.sha256(body.encode()).hexdigest(),
            parser_method="fixture",
            extraction_quality=0.9,
            simhash="0000000000000000" if suffix == "a" else "ffffffffffffffff",
        )


class IrrelevantDawnSource(FixtureDawnSource):
    def discover_since(self, cursor, limit):
        del cursor
        item = Candidate(
            self.key,
            "https://www.dawn.com/lifestyle/recipe",
            "A seasonal dessert recipe",
            "Dawn",
            self.now,
            "rss_atom",
            external_id="irrelevant-1",
        )
        return DiscoveryBatch((item,)[:limit], {})

    def fetch(self, candidate):
        raise AssertionError(f"irrelevant candidate was fetched: {candidate.observed_url}")


class BrokenDiscoverySource(FixtureDawnSource):
    def discover_since(self, cursor, limit):
        raise ValueError("fixture feed contract changed")
