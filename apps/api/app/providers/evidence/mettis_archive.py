"""Public Mettis LoadMore archive; bounded, monotone cursor with explicit gaps."""
from dataclasses import replace
from datetime import UTC, date, datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from app.ingestion.evidence import Candidate, DiscoveryBatch
from app.providers.evidence.sources import HttpEvidenceSource
from app.providers.news.mettis import MettisProvider

BASE='https://mettisglobal.news'

class MettisArchiveSource(HttpEvidenceSource):
    def __init__(self, *, cursor=None,date_from=None,date_to=None,**kwargs):
        super().__init__('mettis','Mettis Global Evidence',BASE+'/latest/','mettis','pakistan_markets',**kwargs)
        self.initial_cursor=cursor or {}
        self.start=date.fromisoformat(date_from) if date_from else None
        self.end=date.fromisoformat(date_to) if date_to else None

    def discover_since(self,cursor,limit):
        state=dict(self.initial_cursor or cursor or {})
        if state.get('complete'): return DiscoveryBatch((),state)
        if not state.get('last_news_id'):
            raw,_,_,_=self.fetcher(self.discovery_url)
            soup=BeautifulSoup(raw,'html.parser');button=soup.select_one('#loadMore[data-lastnewsid]')
            if not button: raise ValueError('mettis_archive_cursor_missing')
            state={'last_news_id':int(button['data-lastnewsid']),'category':button.get('data-category'),'initial_listing':True}
            now=datetime.now(UTC)
            rows=tuple(Candidate(source_key='mettis',observed_url=r.url,canonical_url=r.url,external_id=r.url,
                headline=r.title,publisher=self.publisher,discovered_at=now,published_at=r.published_at,
                discovery_method='publisher_listing',topic=self.topic,metadata={'summary':r.summary})
                for r in MettisProvider.parse_listing(raw.decode('utf-8',errors='replace')))
            return DiscoveryBatch(rows[:limit],state)
        import json
        params={'lastNewsID':state['last_news_id']}
        if state.get('category'): params['lastNewsCategory']=state['category']
        raw,_,_,_=self.fetcher(BASE+'/Home/LoadMore',params=params)
        payload=json.loads(raw)
        if not isinstance(payload,list) or len(payload)>50: raise ValueError('mettis_archive_contract_changed')
        rows=[];ids=[];dates=[];now=datetime.now(UTC)
        for item in payload:
            identifier=int(item['rowid']);ids.append(identifier)
            if identifier>=int(state['last_news_id']): raise ValueError('mettis_archive_cursor_not_monotone')
            url=urljoin(BASE+'/',str(item['link']))
            if not url.startswith(BASE+'/'): raise ValueError('mettis_archive_foreign_url')
            raw_date=str(item.get('publishedTime') or '')
            # Local/UTC article timestamp conflicts are retained. Date-only
            # archive filtering uses the publisher's date, no invented timezone.
            day=date.fromisoformat(raw_date[:10]) if raw_date else None
            if day: dates.append(day)
            if day and ((self.start and day<self.start) or (self.end and day>self.end)): continue
            title=BeautifulSoup(str((item.get('headings') or {}).get('heading',[None])[0] or item.get('heading') or ''),'html.parser').get_text(' ',strip=True)
            if not title: continue
            rows.append(Candidate(source_key='mettis',observed_url=url,canonical_url=url,external_id=url,
                headline=title,publisher=self.publisher,discovered_at=now,published_at=None,
                discovery_method='mettis_loadmore',topic=self.topic,metadata={'summary':str((item.get('descriptions') or {}).get('description',[''])[0]),
                    'publisher_timestamp_raw':raw_date,'publication_date_hint':str(day) if day else None,
                    'timestamp_status':'unverified_timezone','news_id':item.get('newsID'),'archive_row_id':identifier}))
        state={**state,'last_news_id':min(ids) if ids else state['last_news_id'],
            'complete':not payload or bool(self.start and dates and max(dates)<self.start),
            'coverage_note':'Public archive cursor traversal; not guaranteed complete historical coverage.'}
        return DiscoveryBatch(tuple(rows[:limit]),state)
