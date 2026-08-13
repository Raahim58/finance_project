from dataclasses import dataclass
from datetime import date

from app.providers.fundamentals.extraction import extract_facts, parse_period_end


@dataclass
class Page:
    page_number: int
    text: str


def test_extracts_only_unambiguous_scaled_rows_with_provenance():
    facts, diagnostics = extract_facts([Page(7, "Amounts in PKR '000\nRevenue 1,250\nProfit after tax (125)\nTotal assets 3,000 2,800")], date(2025, 12, 31))
    assert diagnostics == []
    assert [(fact.taxonomy_key, fact.value, fact.page_number) for fact in facts] == [("revenue", 1_250_000, 7), ("net_income", -125_000, 7)]


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
