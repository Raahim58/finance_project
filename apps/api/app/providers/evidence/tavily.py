"""Bounded discovery pilot; search snippets are never ingested as source facts."""
from datetime import UTC, datetime
from urllib.parse import urlsplit
import httpx
from app.ingestion.evidence import Candidate, DiscoveryBatch
from app.providers.evidence.sources import HttpEvidenceSource
from app.providers.evidence.extraction import normalize_url

class TavilyDiscoverySource(HttpEvidenceSource):
    def __init__(self, *, api_key,query,domains,transport=None):
        if not domains or len(domains)>20: raise ValueError('tavily_requires_bounded_domains')
        super().__init__('tavily','Tavily discovery','https://api.tavily.com/search','tavily','markets')
        self.api_key=api_key;self.query=query;self.domains=tuple(domains);self.transport=transport

    def discover_since(self,cursor,limit):
        payload={'query':self.query,'search_depth':'basic','topic':'news','max_results':min(10,limit),
            'include_domains':list(self.domains),'include_answer':False,'include_raw_content':False,'auto_parameters':False}
        for field in ('start_date','end_date'):
            if (cursor or {}).get(field): payload[field]=cursor[field]
        with httpx.Client(timeout=20,transport=self.transport) as client:
            response=client.post(self.discovery_url,headers={'Authorization':'Bearer '+self.api_key},json=payload)
            response.raise_for_status();data=response.json()
        rows=[];now=datetime.now(UTC)
        for result in data.get('results',[])[:10]:
            url=normalize_url(result['url']);host=urlsplit(url).hostname or ''
            if not any(host==d or host.endswith('.'+d) for d in self.domains): continue
            rows.append(Candidate(source_key=self.key,observed_url=url,canonical_url=url,external_id=url,
                headline=result.get('title') or url,publisher=host,discovered_at=now,published_at=None,
                discovery_method='tavily_search',topic=self.topic,
                metadata={'discovery_query':self.query,'discovery_snippet_only':True}))
        return DiscoveryBatch(tuple(rows),{'last_search_at':now.isoformat(),'coverage_note':'Discovery pilot, not complete history'})
