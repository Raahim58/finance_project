from datetime import date

from app.providers.macro.sbp import SbpKeyIndicatorsProvider


def test_sbp_key_indicator_parser_preserves_effective_dates():
    html = b"""
    <html><body>
      <h3>SBP Policy Rate</h3><div>11.50% p.a.</div>
      <section>MTBs Tenor Cut-off Yield 1-M 11.70% 3-M 11.7499% 6-M 11.80% (as on Jun 23, 2026)</section>
    </body></html>
    """
    rows = SbpKeyIndicatorsProvider.parse(html, date(2026, 8, 10))
    by_key = {row.series_key: row for row in rows}
    assert by_key["sbp.policy_rate"].effective_date == date(2026, 8, 10)
    assert by_key["sbp.policy_rate"].value == 11.5
    assert by_key["sbp.tbill.3m_yield"].effective_date == date(2026, 6, 23)
    assert by_key["sbp.tbill.3m_yield"].value == 11.7499
