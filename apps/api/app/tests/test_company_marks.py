import struct
from datetime import UTC, datetime
from app.jobs.company_marks import profile_website, valid_icon
from app.models.market import CompanyMark
from app.db.session import SessionLocal


def test_website_identity_comes_from_profile_field():
    html = '<a href="https://ad.test">Ad</a><div class="item__head">WEBSITE</div><p><a href="https://issuer.test">Issuer</a></p>'
    assert profile_website(html) == 'https://issuer.test'
    assert profile_website('<div class="item__head">WEBSITE</div><p>Missing</p>') is None
    assert profile_website(html.replace('https://issuer.test', 'javascript:alert(1)')) is None


def test_rejects_placeholder_and_non_image_content():
    def png(width):
        return b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + struct.pack('>II', width, width)
    assert valid_icon(png(64))
    assert not valid_icon(png(16))
    assert not valid_icon(b'<html>error</html>')
    assert not valid_icon(png(64) + b'x' * 131072)


def test_logo_reads_stored_bytes_and_supports_browser_cache(client):
    content = b'\x89PNG\r\n\x1a\n' + b'x' * 30
    with SessionLocal() as db:
        db.add(CompanyMark(symbol='AAA', profile_source_url='https://dps.psx.com.pk/company/AAA',
            image_source_url='https://www.google.com/s2/favicons?domain=issuer.test',
            content=content, sha256='fixture-hash', status='available', checked_at=datetime.now(UTC)))
        db.commit()
    response = client.get('/market/company/AAA/logo')
    assert response.content == content
    assert response.headers['content-type'] == 'image/png'
    assert client.get('/market/company/AAA/logo', headers={'If-None-Match': response.headers['etag']}).status_code == 304
    assert client.get('/market/company/MISSING/logo').status_code == 404


def test_market_feed_includes_new_records_and_orders_by_date(client, monkeypatch):
    import app.api.routes.research_intelligence as route
    monkeypatch.setattr(route, 'event_records', lambda *a, **kw: [
        {'event_key': 'event:new', 'raw_event_ids': ['new'], 'occurred_at': datetime(2026, 10, 7, tzinfo=UTC)}])
    monkeypatch.setattr(route, 'event_views', lambda *a, **kw: [
        {'event_key': 'raw:old', 'raw_event_id': 'old', 'occurred_at': datetime(2026, 8, 13, tzinfo=UTC)},
        {'event_key': 'raw:new', 'raw_event_id': 'new', 'occurred_at': datetime(2026, 10, 7, tzinfo=UTC)}])
    body = client.get('/research/event-feed?limit=1').json()
    assert body['events'][0]['event_key'] == 'event:new'
    assert body['next_cursor'] == 1
    assert client.get('/research/event-feed?limit=1&cursor=1').json()['events'][0]['event_key'] == 'raw:old'


def test_batch_trends_preserve_recent_stored_closes(client):
    from app.services.market_ingestion import generate_mock_market_data
    from datetime import date
    with SessionLocal() as db:
        generate_mock_market_data(db, days=45, end_date=date(2026, 10, 7))
    batch = client.get('/market/trends?symbols=MEBL,FFC,MISSING').json()
    expected = client.get('/market/company/MEBL/history?limit=30').json()
    assert batch['MEBL'] == [row['close'] for row in expected]
    assert len(batch['MEBL']) == 30
    assert batch['MISSING'] == []
    assert client.get('/market/trends?symbols=' + ','.join(f'S{i}' for i in range(31))).status_code == 422
