from dataclasses import replace
from datetime import UTC, datetime, date
from app.ingestion.evidence import Candidate
from app.ingestion.news_selection import classify_news
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
