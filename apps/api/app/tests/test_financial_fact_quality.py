from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.workstation import FinancialFact, Instrument
from app.providers.fundamentals.extraction import FINANCIAL_EXTRACTION_VERSION, FinancialPage, extract_facts
from app.services.financial_fact_repair import apply_reviewed_repair, fact_snapshot
from app.services.research_service import _derived_fundamentals, _display_facts


def test_growth_column_and_fiscal_date_are_not_values():
    facts, _ = extract_facts([FinancialPage(143, "Consolidated Financial Performance\nYear ended June 30, 2025\nPKR million except EPS\nFY2025 FY2024 Change (%)\nGross Revenue 559204 489363 14.3%\nEarnings Per Share (PKR) * 52.53 44.10 19.1%")], date(2025, 12, 31))
    assert [(f.taxonomy_key, f.value, f.period_end) for f in facts] == [
        ("gross_revenue", Decimal(559204000000), date(2025, 6, 30)),
        ("gross_revenue", Decimal(489363000000), date(2024, 6, 30)),
        ("earnings_per_share", Decimal("52.53"), date(2025, 6, 30)),
        ("earnings_per_share", Decimal("44.10"), date(2024, 6, 30)),
    ]


def test_rejects_narrative_volume_related_parties_and_percentage_sections():
    facts, _ = extract_facts([
        FinancialPage(1, "PKR million\nRevenue of PKR 559.2 billion, up 14.3% from PKR 489.4\nSales volumes increased 14% to 3 million tons\nNet profit for subsidiary was 11.8 billion"),
        FinancialPage(2, "Name of Related Party\nPKR\nSales 49361475"),
        FinancialPage(3, "PKR million\nVertical Analysis - (%) 2025 2024\nGross Profit 14.51 30.12"),
    ], date(2025, 6, 30))
    assert facts == []


def test_curly_thousands_and_notes_entity_scope():
    facts, _ = extract_facts([
        FinancialPage(1, "Notes to the Consolidated Financial Statements\n2025 2024\n(PKR in ‘000’)\nTotal Debt 191504104 213193043"),
        FinancialPage(2, "2025 2024\n(PKR in ‘000’)\nCash and cash equivalents 439589 509667\nRevenue 45144942 44458859"),
    ], date(2025, 6, 30))
    assert [(f.taxonomy_key, f.value) for f in facts] == [("debt", 191504104000), ("debt", 213193043000)]


def test_same_year_balance_dates_and_distinct_reporting_bases():
    facts, _ = extract_facts([
        FinancialPage(1, "Unconsolidated Statement of Financial Position\nDecember 31, June 30,\n2024 2024\nPKR in ‘000’\nTotal assets 255294751 234018090"),
        FinancialPage(2, "Consolidated Statement of Financial Position\nDecember 31, June 30,\n2024 2024\nPKR in ‘000’\nTotal assets 716594945 659661625"),
    ], date(2024, 12, 31))
    assert [(f.value, f.period_end, f.consolidated) for f in facts] == [
        (255294751000, date(2024, 12, 31), False), (234018090000, date(2024, 6, 30), False),
        (716594945000, date(2024, 12, 31), True), (659661625000, date(2024, 6, 30), True),
    ]


def test_ascending_years_prefer_statement_and_reject_mixed_duration_headers():
    facts, _ = extract_facts([
        FinancialPage(1, "Unconsolidated\nPKR million\n2023 2024 2025\nTotal assets 213079 234018 266748"),
        FinancialPage(2, "Unconsolidated Statement of Financial Position\nPKR in ‘000’\n2025 2024\nTotal assets 266748030 234018090"),
        FinancialPage(3, "Statement of Profit or Loss\nHalf Year ended Quarter ended\nDecember 31, December 31, December 31, December 31,\n2024 2023 2024 2023\nPKR in ‘000’\nGross profit 21989947 21820347 12163944 10990008"),
    ], date(2025, 6, 30))
    assert [(f.value, f.period_end.year) for f in facts] == [(213079000000, 2023), (234018090000, 2024), (266748030000, 2025)]


def fact(**kw):
    values = dict(instrument_id="instrument", taxonomy_key="revenue", period_type="annual", period_start=None,
                  period_end=date(2025, 6, 30), value=Decimal(100), unit="PKR", currency="PKR",
                  consolidated=True, version=1, confidence=Decimal("0.9"), diagnostics_json="{}")
    return FinancialFact(**(values | kw))


def test_comparisons_do_not_mix_basis_dates_or_unknown_interim_durations():
    current = fact()
    for prior in [fact(period_end=date(2024, 6, 30), consolidated=False), fact(period_end=date(2024, 12, 31))]:
        assert not _derived_fundamentals([current, prior])["growth"]
    interim = fact(period_type="interim", period_end=date(2024, 12, 31))
    assert not _derived_fundamentals([interim, fact(period_type="interim", period_end=date(2023, 12, 31))])["growth"]
    assert not _derived_fundamentals([current, fact(taxonomy_key="net_income", consolidated=False)])["ratios"]
    assert _derived_fundamentals([current, fact(period_end=date(2024, 6, 30), value=Decimal(50))])["growth"]["revenue"]["value"] == 1


def test_display_preserves_distinct_durations_and_excludes_rejected_values():
    rows = [fact(confidence=Decimal(0)), fact(period_start=date(2025, 1, 1)), fact(period_start=date(2025, 4, 1))]
    assert len(_display_facts(rows)) == 2


def repair_fixture(db):
    db.add(Instrument(id="instrument", symbol="TEST", name="Test"))
    db.add(Document(id="document", document_type="annual_report", title="Test", source_name="Test", content_hash="reviewed"))
    db.flush()
    old = fact(id="old", document_id="document", source_label="Revenue 100", page_number=1)
    other = fact(id="other", document_id=None)
    db.add_all([old, other]); db.flush()
    replacement = fact_snapshot(old) | {"id": "new", "value": "200", "version": 2}
    return {"repair_id": "test-repair", "extraction_version": FINANCIAL_EXTRACTION_VERSION,
            "documents": [{"document_id": "document", "instrument_id": "instrument", "content_hash": "reviewed",
                           "reason": "Confirmed source-column error", "before": [fact_snapshot(old)], "replacements": [replacement]}]}


def test_repair_is_idempotent_preserves_original_values_and_other_records():
    with SessionLocal() as db:
        manifest = repair_fixture(db)
        assert apply_reviewed_repair(db, manifest) == {"already_applied": False, "rejected": 1, "inserted": 1}
        assert apply_reviewed_repair(db, manifest)["already_applied"]
        assert db.get(FinancialFact, "old").value == 100
        assert db.get(FinancialFact, "old").confidence == 0
        assert db.get(FinancialFact, "other").confidence > 0
        assert db.get(FinancialFact, "new").value == 200
        assert len(list(db.scalars(select(FinancialFact)))) == 3


def test_repair_rejects_drift_before_mutating_anything():
    with SessionLocal() as db:
        manifest = repair_fixture(db)
        db.get(FinancialFact, "old").value = Decimal(101)
        with pytest.raises(ValueError, match="changed after review"):
            apply_reviewed_repair(db, manifest)
        assert db.get(FinancialFact, "old").confidence > 0
        assert db.get(FinancialFact, "new") is None


def test_decimal_note_references_and_closing_cash_are_not_subsidiary_values():
    facts, _ = extract_facts([FinancialPage(294,
        "Consolidated Statement of Cash Flows\nPKR in ‘000’\n2025 2024\n"
        "Cash and cash equivalents at the beginning of the year 77623341 70004715\n"
        "Cash and cash equivalents at the end of the year 38.1 131669488 77623341")], date(2025, 6, 30))
    assert [(f.taxonomy_key, f.value) for f in facts] == [("cash", 131669488000), ("cash", 77623341000)]


def test_revenue_before_tax_deductions_is_kept_separate_from_net_revenue():
    facts, _ = extract_facts([FinancialPage(288,
        "Consolidated Statement of Profit or Loss\nPKR in ‘000’\n2024 2023\n"
        "Revenue 31.1 489363447 459459165\nLess: Sales tax and excise duty 64681767 63863527\n"
        "Net Revenue 410995183 385125191")], date(2024, 6, 30))
    assert [(f.taxonomy_key, f.value) for f in facts] == [
        ("gross_revenue", 489363447000), ("gross_revenue", 459459165000),
        ("net_revenue", 410995183000), ("net_revenue", 385125191000)]


def test_exact_facts_reader_excludes_rejected_rows_and_keeps_basis_and_duration():
    from app.services.research_intelligence_service import exact_facts
    with SessionLocal() as db:
        manifest = repair_fixture(db)
        apply_reviewed_repair(db, manifest)
        result = exact_facts(db, db.get(Instrument, "instrument"), limit=1)
        assert result[0]["id"] == "fact:new"
        assert result[0]["accounting_basis"] == "consolidated"
        assert "period_start" in result[0]


def test_four_digit_fiscal_headers_do_not_assume_current_column_first():
    facts, _ = extract_facts([FinancialPage(1, "PKR million\nFY2024 FY2025 Change (%)\nGross Profit 123517 122738 (0.6%)")], date(2025, 6, 30))
    assert [(f.value, f.period_end) for f in facts] == [(123517000000, date(2024, 6, 30)), (122738000000, date(2025, 6, 30))]


def test_assistant_fact_context_excludes_rejected_rows_and_retains_period_start():
    from app.services.context_builder import ContextBuilder
    with SessionLocal() as db:
        manifest = repair_fixture(db)
        manifest['documents'][0]['replacements'][0]['period_start'] = '2024-07-01'
        apply_reviewed_repair(db, manifest)
        section, _ = ContextBuilder._company_facts(db, None, None, db.get(Instrument, 'instrument'))
        rows = section.data['fundamentals']
        assert 'old' not in {r['id'] for r in rows}
        assert next(r for r in rows if r['id'] == 'new')['period_start'] == date(2024, 7, 1)
