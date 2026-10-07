"""User-approved discovery feed; citations belong to fetched original publishers."""
import json
from hashlib import sha256
from datetime import UTC,datetime
from urllib.parse import urlsplit
from app.ingestion.evidence import Candidate,DiscoveryBatch
from app.providers.evidence.sources import HttpEvidenceSource
from app.providers.evidence.extraction import normalize_url

BASE='https://stock-market-analysis-7l5.pages.dev'
PUBLISHERS={'dawn.com':'Dawn','brecorder.com':'Business Recorder','tribune.com.pk':'Express Tribune',
    'mettisglobal.news':'Mettis Global','reuters.com':'Reuters','thenews.com.pk':'The News International','profit.pakistantoday.com.pk':'Profit Pakistan Today'}

class BriefingNewsSource(HttpEvidenceSource):
    def __init__(self,**kwargs):
        super().__init__('briefing_news','Original news publishers',BASE+'/news.json','briefing_news','pakistan_markets',**kwargs)

    def discover_since(self,cursor,limit):
        raw,_,_,_=self.fetcher(self.discovery_url)
        payload=json.loads(raw)
        if not isinstance(payload,list): raise ValueError('briefing_news_contract_changed')
        # Ranking is a curation hint, not a verified materiality/impact measure.
        entries=sorted(payload,key=lambda row:float(row.get('psx_impact_score') or 0),reverse=True)
        candidates=[];seen=set();now=datetime.now(UTC)
        for entry in entries:
            urls=entry.get('urls') or ([entry['url']] if entry.get('url') else [])
            for observed in urls:
                try: url=normalize_url(observed)
                except (TypeError,ValueError): continue
                host=(urlsplit(url).hostname or '').removeprefix('www.')
                if host.endswith('.pages.dev') or host in ('localhost','127.0.0.1'): continue
                if url in seen: continue
                seen.add(url)
                publisher=PUBLISHERS.get(host,host)
                candidates.append(Candidate(source_key=self.key,observed_url=url,canonical_url=url,external_id=url,
                    headline=str(entry.get('headline') or url),publisher=publisher,discovered_at=now,published_at=None,
                    discovery_method='curated_original_links',topic=self.topic,
                    metadata={'summary':str(entry.get('summary') or ''),'discovery_url':self.discovery_url,
                        'curated_sectors':entry.get('sectors_affected') or [],'curation_impact_unverified':entry.get('psx_impact_score'),
                        'publication_date_basis':'original_article_required'}))
        # A repeated, bounded poll must advance beyond already observed top
        # stories. Keep an original-URL identity rather than a positional offset
        # so feed insertions and score reordering do not skip the next story.
        hashes=[sha256(candidate.canonical_url.encode()).hexdigest() for candidate in candidates]
        next_hash=(cursor or {}).get('next_url_hash')
        start=hashes.index(next_hash) if next_hash in hashes else 0
        count=min(50,max(0,limit),len(candidates))
        selected=[candidates[(start+index)%len(candidates)] for index in range(count)]
        next_index=(start+count)%len(candidates) if candidates else 0
        return DiscoveryBatch(tuple(selected),{'checked_at':now.isoformat(),
            'next_url_hash':hashes[next_index] if hashes else None,
            'candidate_limit_reached':len(candidates)>count})
