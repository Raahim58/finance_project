from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.market import Company
from app.models.workstation import CompanyScreeningSnapshot, IngestionCoverage, Instrument, StandardizedFinancialFact
from app.providers.fundamentals.dps_standardized import parse_company_page
from app.providers.fundamentals.extraction import extract_facts, parse_financial_pdf
from app.services.market_ingestion import sync_observed_dps_universe
from app.services.screening_service import compute_screening_snapshots, deep_instrument_ids
from app.services.coverage_service import is_queueable, reserve_and_publish


def _table(metric: str = "Sales") -> str:
    return f"""
    <html><h1>Financials</h1><p>All numbers in thousands (000's) except EPS</p>
    <table><tr><th></th><th>2025</th><th>2024</th></tr>
    <tr><td>{metric}</td><td>1,200</td><td>1,000</td></tr>
    <tr><td>Profit after Taxation</td><td>240</td><td>180</td></tr>
    <tr><td>EPS</td><td>4.2</td><td>3.1</td></tr></table>
    <table><tr><th></th><th>Q1 2026</th><th>Q1 2025</th></tr>
    <tr><td>{metric}</td><td>350</td><td>270</td></tr></table></html>
    """


def test_dps_standardized_parser_preserves_secondary_scale_and_sector_label():
    facts, diagnostics = parse_company_page(_table("Total Income"))
    assert diagnostics == []
    assert any(row.metric == "total_income" and row.period_key == "2025" and row.value == Decimal("1200000") for row in facts)
    assert any(row.metric == "earnings_per_share" and row.value == Decimal("4.2") for row in facts)
    assert any(row.period_type == "quarterly" and row.period_end == date(2026, 3, 31) for row in facts)


def test_dps_parser_deduplicates_responsive_clone_tables():
    table = _table()
    facts, _ = parse_company_page(table.replace("</html>", "") + _table().replace("<html>", ""))
    keys = [(row.metric, row.period_type, row.period_key) for row in facts]
    assert len(keys) == len(set(keys))


def test_dps_standardized_parser_reports_missing_without_zero_fill():
    facts, diagnostics = parse_company_page("<html><h1>Financials</h1><p>No record found</p></html>")
    assert facts == []
    assert "unavailable" in diagnostics[0]


def test_dynamic_universe_filters_non_ordinary_and_deactivates_absent_symbols():
    with SessionLocal() as db:
        count = sync_observed_dps_universe(db, [
            {"symbol": "AAA", "name": "A Limited", "sector": "Cement", "is_debt": False, "is_etf": False, "is_gem": False},
            {"symbol": "ETF1", "name": "Fund", "sector": "ETF", "is_debt": False, "is_etf": True, "is_gem": False},
        ])
        db.commit()
        assert count == 1
        assert list(db.scalars(select(Company.symbol).where(Company.is_active.is_(True)))) == ["AAA"]
        sync_observed_dps_universe(db, [])
        db.commit()
        assert db.scalar(select(Company).where(Company.symbol == "AAA")).is_active is False


def test_celery_has_only_required_phase2_workload_queues():
    routes = celery_app.conf.task_routes
    queues = {route["queue"] for name, route in routes.items() if name.startswith("phase2.")}
    assert queues == {"broad_fundamentals", "dps_history", "financial_download", "financial_extract"}
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_screening_keeps_missing_data_separate_and_promotes_observed_candidate():
    with SessionLocal() as db:
        sync_observed_dps_universe(db, [
            {"symbol": "FULL", "name": "Full Data", "sector": "Cement", "is_debt": False, "is_etf": False, "is_gem": False},
            {"symbol": "MISS", "name": "Missing Data", "sector": "Cement", "is_debt": False, "is_etf": False, "is_gem": False},
        ])
        full = db.scalar(select(Instrument).where(Instrument.symbol == "FULL"))
        for metric, values in {"revenue": (120, 100), "net_income": (30, 20), "earnings_per_share": (6, 4)}.items():
            for year, value in zip((2025, 2024), values, strict=True):
                db.add(StandardizedFinancialFact(instrument_id=full.id, metric=metric, period_type="annual", period_key=str(year), period_end=date(year, 12, 31), value=value, unit="PKR", currency="PKR", source="dps", source_url="https://dps.psx.com.pk/company/FULL"))
        db.commit()
        snapshots = compute_screening_snapshots(db, date(2026, 1, 2))
        by_symbol = {db.get(Instrument, row.instrument_id).symbol: row for row in snapshots}
        assert by_symbol["MISS"].completeness == 0
        assert by_symbol["MISS"].score is None
        assert by_symbol["MISS"].screenable is False
        assert by_symbol["FULL"].screenable is True
        assert by_symbol["FULL"].promoted is True
        assert full.id in deep_instrument_ids(db)


def test_coverage_key_is_durable_and_unique():
    with SessionLocal() as db:
        sync_observed_dps_universe(db, [{"symbol": "AAA", "name": "A", "sector": "Cement", "is_debt": False, "is_etf": False, "is_gem": False}])
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "AAA"))
        db.add(IngestionCoverage(instrument_id=instrument.id, dataset_type="price_history", period_key="2023-04", source="dps", status="complete", item_count=20))
        db.commit()
        row = db.scalar(select(IngestionCoverage).where(IngestionCoverage.period_key == "2023-04"))
        assert (row.dataset_type, row.status, row.item_count) == ("price_history", "complete", 20)


def test_phase2_queueability_treats_partial_and_live_reservations_as_terminal():
    now = datetime.now(UTC)
    row = IngestionCoverage(instrument_id="instrument", dataset_type="price_history", period_key="2025-01", source="dps", status="partial")
    assert is_queueable(row, now) is False
    row.status = "queued"; row.attempted_at = now
    assert is_queueable(row, now) is False
    row.status = "running"
    assert is_queueable(row, now) is False
    row.status = "failed"; row.retry_count = 1; row.attempted_at = now - timedelta(hours=1)
    assert is_queueable(row, now) is True
    row.retry_count = 3
    assert is_queueable(row, now) is False


def test_phase2_reservation_is_persisted_before_publish():
    class FakeTask:
        target_id = None
        observed_status = None

        def delay(self, *_args):
            with SessionLocal() as check:
                self.observed_status = check.scalar(select(IngestionCoverage.status).where(IngestionCoverage.id == self.target_id))

    with SessionLocal() as db:
        sync_observed_dps_universe(db, [{"symbol": "QUEUE", "name": "Queue", "sector": "Cement", "is_debt": False, "is_etf": False, "is_gem": False}])
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "QUEUE"))
        row = IngestionCoverage(instrument_id=instrument.id, dataset_type="price_history", period_key="2025-01", source="dps", status="missing")
        db.add(row); db.commit()
        task = FakeTask(); task.target_id = row.id
        assert reserve_and_publish(db, row, task, ("QUEUE", 2025, 1), datetime.now(UTC)) is True
        assert task.observed_status == "queued"


def test_blank_pdf_is_classified_for_selective_ocr_without_facts():
    from io import BytesIO
    from pypdf import PdfWriter

    writer = PdfWriter(); writer.add_blank_page(width=612, height=792)
    buffer = BytesIO(); writer.write(buffer)
    pages, classification, diagnostics = parse_financial_pdf(buffer.getvalue())
    assert len(pages) == 1
    assert classification == "scanned_or_sparse"
    assert "OCR" in diagnostics[0]


def test_image_only_financial_statement_uses_ocr_with_lower_confidence():
    import io
    import shutil

    import pytest
    from PIL import Image, ImageDraw, ImageFont

    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        pytest.skip("Poppler and Tesseract are required for OCR integration")
    image = Image.new("RGB", (1800, 2200), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    lines = [
        "STATEMENT OF FINANCIAL POSITION",
        "PKR in million",
        "Total assets 1,000 900",
        "Total liabilities 400 350",
        "Total equity 600 550",
    ]
    for index, line in enumerate(lines):
        draw.text((120, 180 + index * 110), line, fill="black", font=font)
    buffer = io.BytesIO(); image.save(buffer, format="PDF", resolution=150)
    pages, classification, diagnostics = parse_financial_pdf(buffer.getvalue())
    facts, fact_diagnostics = extract_facts(
        pages, date(2025, 12, 31), extraction_method="ocr", confidence=Decimal("0.700000")
    )
    assert classification == "ocr"
    assert any("selected 1" in message for message in diagnostics)
    assert {fact.taxonomy_key for fact in facts} == {"assets", "liabilities", "equity"}
    assert all(fact.extraction_method == "ocr" and fact.confidence == Decimal("0.700000") for fact in facts)
    assert not any("remain unavailable" in message for message in fact_diagnostics)
