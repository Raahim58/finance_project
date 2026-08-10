from datetime import UTC, datetime
from pathlib import Path

from app.providers.news.mettis import MettisProvider


FIXTURES = Path(__file__).parent / "fixtures" / "providers" / "mettis"
URL = "https://mettisglobal.news/Worker-remittances-rises-to-363bn-in-July-62521"


def test_mettis_observed_listing_contract():
    rows = MettisProvider.parse_listing((FIXTURES / "latest.sample.html").read_text())
    assert len(rows) == 1
    assert rows[0].url == URL
    assert rows[0].summary is None


def test_mettis_observed_article_metadata_contract():
    row = MettisProvider.parse_article_metadata((FIXTURES / "article_metadata.sample.html").read_text(), URL)
    assert row.title == "Worker remittances rises to $3.63bn in July"
    assert row.published_at == datetime(2026, 8, 10, 10, 6, 55, tzinfo=UTC)
    assert row.author == "MG News"
