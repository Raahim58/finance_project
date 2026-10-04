from dataclasses import replace
from datetime import UTC, datetime, date
from app.ingestion.evidence import Candidate
from app.ingestion.news_selection import classify_news
from app.ingestion.news_selection import prepare_material_candidate
from app.jobs.curated_news import rank_candidates


def test_material_news_rejects_promotional_and_engineering_articles():
    for title in ('Urea prices rise as gas supply falls', 'Cement dispatches recover',
                  'Red Sea blockade threatens shipping', 'Cotton demand falls after tariffs'):
        assert classify_news(title)['eligible']
    for title in ('Tracing RTL devices at cryogenic temperatures', 'World Cement spotlight interview',
                  'Football final in China', 'New fertilizer product launch',
                  'Implementing the Cyber Resilience Act: eBook',
                  'Why Can’t an AI System Answer a Metals Cost Question From The Price Alone?',
                  'AI Is Forcing Data Centers To Rethink Trust'):
        assert not classify_news(title)['eligible']


def test_shortlist_is_dated_deduplicated_and_month_bounded():
    c = Candidate('cotton_grower','https://example.com/1','Cotton prices rise','Cotton Grower',
        datetime(2026,10,1,tzinfo=UTC),'rss',published_at=datetime(2026,9,20,tzinfo=UTC))
    rows=[replace(c,observed_url=f'https://example.com/{i}') for i in range(10)]
    rows += [c,replace(c,published_at=None),replace(c,published_at=datetime(2025,1,1,tzinfo=UTC))]
    result=rank_candidates(rows,date(2026,7,1),date(2026,10,4),per_month=2)
    assert len(result)==2
    assert all(r.metadata['curated_news']['sectors']==['textile'] for r in result)


def test_shared_material_filter_bounds_live_news_and_preserves_archive_window():
    c = Candidate('cotton_grower', 'https://example.com/news', 'Cotton prices rise',
        'Cotton Grower', datetime(2026,10,4,tzinfo=UTC), 'rss')
    live = prepare_material_candidate(c)
    assert live.metadata['curated_news']['eligible']
    assert live.metadata['curated_news']['date_from'] == '2026-09-27'
    assert live.metadata['curated_news']['date_to'] == '2026-10-04'
    archive = replace(c, metadata={'priority_class':'historical',
        'curated_news':{'date_from':'2026-07-01','date_to':'2026-07-31'}})
    assert prepare_material_candidate(archive).metadata['curated_news']['date_from'] == '2026-07-01'
    assert not prepare_material_candidate(replace(c,headline='New fertilizer product launch')).metadata['curated_news']['eligible']
    announcement = replace(c, source_key='psx_announcements')
    assert prepare_material_candidate(announcement) is announcement


def test_live_discovery_rejects_irrelevant_titles_before_download(monkeypatch):
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.services.evidence_pipeline import ensure_source_config, persist_candidate
    monkeypatch.setattr(settings, 'evidence_material_news_enabled', True)
    candidate=Candidate('dawn','https://example.com/irrelevant','Football final in China',
        'Dawn',datetime(2026,10,4,tzinfo=UTC),'rss')
    with SessionLocal() as db:
        config=ensure_source_config(db,'dawn')[1]
        rejected,_=persist_candidate(db,config,candidate)
        assert rejected.status=='rejected' and rejected.artifact_id is None
        # A broader old keyword gate must not reopen a material-filter rejection.
        _, reopened= persist_candidate(db,config,candidate)
        assert not reopened and rejected.status=='rejected'
        accepted,_=persist_candidate(db,config,replace(candidate,
            observed_url='https://example.com/inflation',headline='Pakistan inflation rises'))
        assert accepted.status=='fetch_ready'
