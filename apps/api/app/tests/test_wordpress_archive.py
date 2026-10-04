import json
from datetime import date

from app.providers.evidence.wordpress_archive import WordPressArchiveSource
from app.services.evidence_history_service import _units


def test_archive_uses_raw_offset_and_observed_utc_dates():
    def fetcher(url, **kwargs):
        assert kwargs["params"]["offset"] == 2
        return json.dumps([
            {"id": 1, "date_gmt": "2026-07-31T23:00:00", "link": "https://gcaptain.com/outside", "title": {"rendered": "Outside"}},
            {"id": 2, "date_gmt": "2026-08-01T13:20:00", "link": "https://gcaptain.com/story", "title": {"rendered": "LNG &amp; shipping disruption"}},
        ]).encode(), url, "application/json", {"X-WP-Total": "7"}
    source = WordPressArchiveSource("gcaptain", fetcher=fetcher)
    batch = source.discover_since({"date_from": "2026-08-01", "date_to": "2026-08-07", "offset": 2}, 2)
    assert len(batch.candidates) == 1
    assert batch.candidates[0].headline == "LNG & shipping disruption"
    assert batch.candidates[0].published_at.isoformat() == "2026-08-01T13:20:00+00:00"
    assert batch.next_cursor == {"offset": 4, "exhausted": False}


def test_archive_work_units_cover_dates_without_overlap():
    units = _units(("gcaptain", "freightwaves"), query_text=None, symbol=None,
                   preset_key="global_shipping_90d", date_from=date(2026, 8, 1), date_to=date(2026, 8, 10))
    assert [(u["source_key"], u["date_from"], u["date_to"]) for u in units] == [
        ("gcaptain", "2026-08-01", "2026-08-07"), ("gcaptain", "2026-08-08", "2026-08-10"),
        ("freightwaves", "2026-08-01", "2026-08-07"), ("freightwaves", "2026-08-08", "2026-08-10"),
    ]
