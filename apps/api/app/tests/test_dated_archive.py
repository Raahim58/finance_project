from datetime import date

import pytest

from app.providers.evidence.dated_archive import DatedArchiveSource
from app.services.evidence_history_service import _units


def source(key, html):
    return DatedArchiveSource(key, fetcher=lambda url: (html.encode(), url, "text/html", {}))


def test_dawn_preserves_timezone_category_and_paginates_without_skips():
    html = '<title>News Archives for Latest - 2026-10-03 - DAWN.COM</title>'
    for i in range(3):
        html += f'''<article class="story"><span class="badge">Business</span>
        <h2><a class="story__link" href="/news/{i}/oil">Oil outlook {i}</a></h2>
        <span datetime="2026-10-03T00:30:00+05:00"></span>
        <div class="story__excerpt">Policy and prices</div></article>'''
    adapter = source("dawn", html)
    cursor = {"date_from": "2026-10-03", "date_to": "2026-10-03"}
    first = adapter.discover_since(cursor, 2)
    second = adapter.discover_since({**cursor, **first.next_cursor}, 2)
    assert [c.headline for c in first.candidates + second.candidates] == ['Oil outlook 0', 'Oil outlook 1', 'Oil outlook 2']
    assert first.candidates[0].published_at.isoformat() == '2026-10-02T19:30:00+00:00'
    assert first.candidates[0].metadata['category'] == 'Business'
    assert second.next_cursor['exhausted']


def test_guardian_excludes_other_dates_and_does_not_invent_timestamp():
    adapter = source("guardian_world", '''<title>World news | The Guardian</title>
        <a data-link-name="article" href="/world/2026/oct/03/oil-war">Oil disruption</a>
        <a data-link-name="article" href="/world/2026/oct/02/old">Old</a>''')
    batch = adapter.discover_since({"date_from": "2026-10-03"}, 10)
    assert len(batch.candidates) == 1
    assert batch.candidates[0].published_at is None
    assert batch.candidates[0].metadata['archive_date'] == '2026-10-03'


def test_archive_navigation_page_is_not_successful_empty_coverage():
    adapter = source("dawn", '<title>Dawn</title><a href="/news/1">News</a>')
    with pytest.raises(ValueError, match='date/title'):
        adapter.discover_since({"date_from": "2026-10-03"}, 10)


def test_daily_units_cover_all_days_for_both_publishers():
    units = _units(('dawn', 'guardian_world'), query_text=None, symbol=None,
        preset_key='publisher_news_90d', date_from=date(2026, 10, 1), date_to=date(2026, 10, 3))
    assert len(units) == 6
    assert all(u['date_from'] == u['date_to'] for u in units)
    assert units[-1]['date_from'] == '2026-10-03'


def test_archive_rejects_foreign_hosts():
    adapter = source("dawn", '''<title>News Archives for Latest - 2026-10-03 - DAWN.COM</title>
        <article class="story"><h2><a class="story__link" href="https://evil.example/news/1">Oil</a></h2>
        <span datetime="2026-10-03T12:30:00+05:00"></span></article>''')
    with pytest.raises(ValueError, match='no dated articles'):
        adapter.discover_since({"date_from": "2026-10-03"}, 10)
