from dataclasses import dataclass
from datetime import date

from app.providers.fundamentals.extraction import extract_facts, parse_period_end


@dataclass
class Page:
    page_number: int
    text: str


def test_extracts_scaled_single_and_comparative_rows_with_provenance():
    facts, diagnostics = extract_facts([Page(7, "Amounts in PKR '000\nRevenue 1,250\nProfit after tax (125)\nTotal assets 3,000 2,800")], date(2025, 12, 31))
    assert diagnostics == []
    assert [(fact.taxonomy_key, fact.value, fact.period_end, fact.page_number) for fact in facts] == [
        ("revenue", 1_250_000, date(2025, 12, 31), 7),
        ("net_income", -125_000, date(2025, 12, 31), 7),
        ("assets", 3_000_000, date(2025, 12, 31), 7),
        ("assets", 2_800_000, date(2024, 12, 31), 7),
    ]


def test_rejects_facts_without_explicit_currency_scale():
    facts, diagnostics = extract_facts([Page(1, "Revenue 1,250")], date(2025, 12, 31))
    assert facts == []
    assert "scale" in diagnostics[0]


def test_period_end_parser_is_deterministic():
    assert parse_period_end("year ended 2025") == date(2025, 12, 31)
    assert parse_period_end("30-06-2025") == date(2025, 6, 30)
    assert parse_period_end("period ended June 30, 2025") == date(2025, 6, 30)


def test_per_share_facts_are_not_multiplied_by_statement_scale():
    facts, diagnostics = extract_facts(
        [Page(3, "Amounts in PKR '000\nEPS 12.50\nDividend per share 4.00")],
        date(2025, 12, 31),
    )
    assert diagnostics == []
    assert [(fact.taxonomy_key, fact.value) for fact in facts] == [
        ("earnings_per_share", 12.5),
        ("dividend_per_share", 4),
    ]


def test_parenthesized_reporting_units_are_normalized():
    facts, _ = extract_facts([Page(1, "Amounts in Rupees ('000)\nTotal assets 3,000")], date(2025, 12, 31))
    assert [(fact.taxonomy_key, fact.value) for fact in facts] == [('assets', 3_000_000)]


def test_each_table_uses_its_own_explicit_unit_heading():
    facts, _ = extract_facts([Page(1, "Rupees in millions\nTotal equity 2\nRupees in thousands\nRevenue 3,000")], date(2025, 12, 31))
    assert [(fact.taxonomy_key, fact.value) for fact in facts] == [('equity', 2_000_000), ('revenue', 3_000_000)]


def test_later_unit_header_is_not_applied_to_an_earlier_ambiguous_table():
    facts, diagnostics = extract_facts([Page(1, "Total assets 100\nRupees in millions\nTotal equity 2\nRupees in thousands\nRevenue 3,000")], date(2025, 12, 31))
    assert not any(fact.taxonomy_key == 'assets' for fact in facts)
    assert any('scale unknown' in message for message in diagnostics)
