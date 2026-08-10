import json
from datetime import date
from pathlib import Path

from app.providers.fundamentals.psx_financials import PsxFinancialsProvider


FIXTURES = Path(__file__).parent / "fixtures" / "providers" / "psx_financials"


def test_psx_financials_catalog_observed_contract():
    payload = json.loads((FIXTURES / "mebl_2025.sample.json").read_text())
    rows = PsxFinancialsProvider.parse_catalog(payload, "mebl")
    assert len(rows) == 3
    assert rows[-1].symbol == "MEBL"
    assert rows[-1].report_type == "annual"
    assert rows[-1].period_ended == "2025"
    assert rows[-1].posting_date == date(2026, 3, 5)
    assert rows[-1].report_url == "https://financials.psx.com.pk/lib/DownloadPDF.php?id=272066"
    assert rows[-1].report_id == "272066"


def test_psx_financials_ignores_unverified_report_links():
    payload = [{"Reports": "<a href='other.php?id=1'>Annual</a>", "period_ended": "2025", "posting_date": "2026-01-01"}]
    assert PsxFinancialsProvider.parse_catalog(payload, "MEBL") == []
